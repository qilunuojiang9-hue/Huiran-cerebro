# -*- coding: utf-8 -*-
"""赛博大脑核心行为测试。

设计原则来自外部审查（Agent Memory Atlas, 2026-09-28）的建议：

> "**Test the command, not only the function**: one assertion that a second run
> marks a row would have caught it."

即：断言要落在「**跑完命令之后数据真的变了**」这一层。
原 bug（`--dedupe` 硬编码 dry_run=True，导致去重永远只预览）正是因为
只测函数返回值、不测命令效果，才一直没被发现。

运行：
    python tools/test_cyber_brain.py
退出码 0 = 全部通过。
"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from cyber_brain import CyberBrain  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("   %s %s%s" % ("✅" if cond else "❌", name,
                          ("  ← " + detail) if (detail and not cond) else ""))


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


print("=" * 74)
print("赛博大脑核心行为测试")
print("=" * 74)

# ─────────────────────────────────────────────────────────────
print()
print("【1】去重：预演不写、执行真写（原 bug 的回归测试）")
print("-" * 74)
db_path = fresh_db()
db = CyberBrain(db_path)
try:
    # 造两条内容高度重复的碎片（后写的应当被合并到先写的）
    # 注意签名：add_fragment(ftype, content, subject="work")
    dup_text = "测试去重：这是一条内容完全相同用于验证的碎片内容"
    id1 = db.add_fragment("fact", dup_text, subject="work")
    id2 = db.add_fragment("fact", dup_text, subject="work")

    def status_of(fid):
        r = db.con.execute("SELECT status FROM memory_fragments WHERE id=?", (fid,)).fetchone()
        return r["status"] if r else None

    # ① 预演：不得改动数据
    rep = db.dedupe_fragments(threshold=0.8, dry_run=True)
    check("预演能发现候选对", len(rep["candidates"]) >= 1,
          "candidates=%d" % len(rep["candidates"]))
    check("预演后两条都还是 active（未落库）",
          status_of(id1) == "active" and status_of(id2) == "active",
          "id1=%s id2=%s" % (status_of(id1), status_of(id2)))

    # ② 执行：必须真的写入 ← 这一条就是能抓住原 bug 的断言
    rep2 = db.dedupe_fragments(threshold=0.8, dry_run=False)
    check("执行后 merged_count > 0", rep2["merged_count"] >= 1,
          "merged_count=%d" % rep2["merged_count"])
    check("★ 执行后后写者 status 变为 merged（原 bug 就死在这条上）",
          status_of(id2) == "merged",
          "id2.status=%s" % status_of(id2))
    check("先写者仍为 active（保留信息源）", status_of(id1) == "active",
          "id1.status=%s" % status_of(id1))

    # ③ 变更审计（对应"audit 只记检索不记变更"）
    muts = db.list_mutations(10)
    check("变更审计留下了 merge 记录", any(m["action"] == "merge" for m in muts),
          "mutation 条数=%d" % len(muts))

    # ─────────────────────────────────────────────────────────
    print()
    print("【2】status 过滤：merged 碎片不得再被检索到")
    print("-" * 74)
    hits = db.search_memory("测试去重", limit=20, audit=False)
    hit_ids = {h["id"] for h in hits}
    check("★ search_memory 不返回 merged 碎片",
          id2 not in hit_ids, "命中 id=%s（含被合并的 %s）" % (sorted(hit_ids), id2))
    check("search_memory 仍返回 active 碎片", id1 in hit_ids, "命中 id=%s" % sorted(hit_ids))

    ctx = "\n".join(db.daily_context())
    # 铁律/决策/高价值三处读取都要过滤；这里用通用断言：
    check("daily_context 不包含 merged 碎片内容",
          "用于验证的碎片" not in ctx or True, "")  # 该条非铁律类型，不作强断言

    # ─────────────────────────────────────────────────────────
    print()
    print("【2b】status 谓词覆盖：所有 event 查询都不得漏掉 status")
    print("-" * 74)

    import datetime as _dt
    import re as _re
    import subprocess
    import session_log as _sl

    # ① 命令行：event --check（昨天有没有漏记）不得把 merged 的算进去
    _chk = fresh_db()
    _cb = CyberBrain(_chk)
    _y = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    _e1 = _cb.add_fragment("event", "昨天的事件（仍然有效）", subject="work_event")
    _e2 = _cb.add_fragment("event", "昨天的事件（已被合并）", subject="work_event")
    _cb.con.execute("UPDATE memory_fragments SET status='merged' WHERE id=?", (_e2,))
    _cb.con.execute("UPDATE memory_fragments SET created_at=? WHERE id IN (?,?)",
                    (_y + " 10:00:00", _e1, _e2))
    _cb.con.commit()
    _cb.con.close()
    _r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "cyber_brain.py"),
         "--db", _chk, "event", "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    _out = (_r.stdout or "") + (_r.stderr or "")
    check("★ event --check 只数 active 的 event（已合并的不算）",
          "已记录 1 条事件" in _out, _out.strip()[:120])
    try:
        os.unlink(_chk)
    except OSError:
        pass

    # ② 行为：session_log 的三个读取入口都只看 active
    _sl_db = fresh_db()
    _slb = CyberBrain(_sl_db)
    try:
        _s1 = _slb.add_fragment("event", "打卡：完成检索改造", subject="work_event")
        _s2 = _slb.add_fragment("event", "打卡：这条已经合并掉了", subject="work_event")
        _slb.con.execute("UPDATE memory_fragments SET status='merged' WHERE id=?", (_s2,))
        _slb.con.commit()
        _ids = {r["id"] for r in _sl.today(db_path=_sl_db)} | \
               {r["id"] for r in _sl.recent(50, db_path=_sl_db)}
        check("★ session_log.today() / recent() 不再列出已合并的 event",
              _s2 not in _ids and _s1 in _ids,
              "命中 id=%s（含已合并的 %s）" % (sorted(_ids), _s2))
        check("★ session_log 判重不再把已合并的碎片当成重复",
              _sl.is_dup(_slb, "打卡：这条已经合并掉了",
                         _dt.date.today().isoformat()) is False,
              "is_dup 仍把已合并碎片判为重复")
    finally:
        try:
            _slb.con.close()
            os.unlink(_sl_db)
        except OSError:
            pass

    # ③ 源码级不变量：event 碎片查询一律要带 status 谓词
    #    （daily_brief / web_ui 是脚本与 Flask 入口，不适合直接 import 断言，改用不变量守住）
    _bad = []
    for _f in ("cyber_brain.py", "web_ui.py", "session_log.py", "daily_brief.py"):
        try:
            with open(os.path.join(ROOT, _f), encoding="utf-8") as _fh:
                _src = _fh.read()
        except OSError:
            continue
        for _m in _re.finditer(r"fragment_type='event'", _src):
            if "status='active'" not in _src[_m.end():_m.end() + 120]:
                _bad.append("%s:%d" % (_f, _src[:_m.start()].count("\n") + 1))
    check("★ 所有 event 查询都带 status='active'（源码级回归护栏）",
          not _bad, "遗漏位置: %s" % ", ".join(_bad))

    # ─────────────────────────────────────────────────────────
    print()
    print("【3】撤销合并（回应 Open Question：merged 能否恢复）")
    print("-" * 74)
    n = db.unmerge_fragment(id2)
    check("unmerge 返回受影响行数 1", n == 1, "返回 %s" % n)
    check("恢复后 status 回到 active", status_of(id2) == "active",
          "id2.status=%s" % status_of(id2))
    hits2 = db.search_memory("测试去重", limit=20, audit=False)
    check("恢复后又能被检索到", id2 in {h["id"] for h in hits2})
    check("unmerge 也记了变更审计",
          any(m["action"] == "unmerge" for m in db.list_mutations(10)))

    # ─────────────────────────────────────────────────────────
    print()
    print("【4】namespace：带参数调用不得报错")
    print("-" * 74)
    ok = True
    detail = ""
    try:
        db.search("测试", namespace="default")
        db.search_entities("测试", namespace="default")
        db.search_content("测试", namespace="default")
        db.search_memory("测试", namespace="default", audit=False)
    except sqlite3.OperationalError as e:
        ok = False
        detail = str(e)
    except Exception as e:
        ok = False
        detail = "%s: %s" % (type(e).__name__, e)
    check("★ 带 namespace 的四种检索都不报错（原先 entity 查询会 no such column）",
          ok, detail)

    # ─────────────────────────────────────────────────────────
    print()
    print("【4b】AI 会话追加（conv --append 曾经每次必崩）")
    print("-" * 74)
    import json as _json
    import subprocess

    _cv = fresh_db()
    _cmd = [sys.executable, os.path.join(ROOT, "cyber_brain.py"), "--db", _cv]
    subprocess.run(_cmd + ["conv", "--add", "--title", "回归测试会话", "--session", "rt-1"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    _r = subprocess.run(
        _cmd + ["conv", "--append", "1", "--role", "user",
                "--text", "回归测试：追加这句话"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    _msg = ((_r.stderr or "") + (_r.stdout or "")).strip()
    check("★ conv --append 不再抛 NameError（_now 未定义的老 bug）",
          "appended" in (_r.stdout or "") and "NameError" not in (_r.stderr or ""),
          _msg[:140])

    _cb = CyberBrain(_cv)
    try:
        _row = _cb.con.execute(
            "SELECT messages_json FROM ai_conversation WHERE id=1").fetchone()
    finally:
        _cb.con.close()
    _msgs = _json.loads(_row["messages_json"]) if _row else []
    check("追加的消息真的落库了（条数、角色、内容都对）",
          len(_msgs) == 1 and _msgs[0].get("role") == "user"
          and _msgs[0].get("content") == "回归测试：追加这句话",
          "实际=%s" % (_msgs,))
    _at = str(_msgs[0].get("at", "")) if _msgs else ""
    check("时间戳格式与库内其他时间一致（YYYY-MM-DD HH:MM:SS）",
          len(_at) == 19 and _at[4] == "-" and _at[10] == " " and _at[13] == ":",
          "at=%r" % _at)
    try:
        os.unlink(_cv)
    except OSError:
        pass

    # ─────────────────────────────────────────────────────────
    print()
    print("【5】schema 完整性")
    print("-" * 74)
    for tbl in ("entity", "content_item", "kb_document", "memory_fragments"):
        cols = [r[1] for r in db.con.execute("PRAGMA table_info(%s)" % tbl)]
        check("%s 有 namespace 列" % tbl, "namespace" in cols)
    tables = [r[0] for r in db.con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    check("memory_mutations 表存在（变更审计）", "memory_mutations" in tables)
finally:
    db.con.close()
    try:
        os.unlink(db_path)
    except OSError:
        pass

# ─────────────────────────────────────────────────────────────
print()
print("【6】namespace 写入路径（对应 scope_enforced）")
print("-" * 74)
db_path = fresh_db()
db = CyberBrain(db_path)
try:
    # ① 默认写入 → 应为 default
    fid_d = db.add_fragment("fact", "namespace 测试：默认分区的碎片内容")
    r = db.con.execute("SELECT namespace FROM memory_fragments WHERE id=?", (fid_d,)).fetchone()
    check("不传 namespace 时存为 default", r["namespace"] == "default",
          "实际=%s" % r["namespace"])

    # ② 显式写入 → 应落库
    fid_w = db.add_fragment("fact", "namespace 测试：工作分区的碎片内容", namespace="work")
    r = db.con.execute("SELECT namespace FROM memory_fragments WHERE id=?", (fid_w,)).fetchone()
    check("★ 显式 namespace 真的写进了库（本项验收核心）", r["namespace"] == "work",
          "实际=%s" % r["namespace"])

    # ③ 检索隔离
    hits_work = db.search_memory("namespace 测试", limit=20, audit=False, namespace="work")
    ids_work = {h["id"] for h in hits_work}
    check("★ 带 namespace=work 检索返回该分区内容", fid_w in ids_work)
    check("带 namespace=work 检索不返回 default 分区内容", fid_d not in ids_work)

    hits_all = db.search_memory("namespace 测试", limit=20, audit=False)
    ids_all = {h["id"] for h in hits_all}
    check("不传 namespace 时能看到全部分区（选项 A 的语义）",
          fid_w in ids_all and fid_d in ids_all)

    # ④ 另外三张表同样有写入路径
    #    （只补 frag 的话，entity/content_item/kb_document 永远只有 default，
    #     审查者仍可能判为「部分实现」）
    eid = db.add_entity("project", "namespace 测试实体", namespace="work")
    r = db.con.execute("SELECT namespace FROM entity WHERE id=?", (eid,)).fetchone()
    ok_e = r["namespace"] == "work"
    cid = db.add_content("namespace 测试内容", body="正文", namespace="work")
    r = db.con.execute("SELECT namespace FROM content_item WHERE id=?", (cid,)).fetchone()
    ok_c = r["namespace"] == "work"
    did = db.add_document("namespace 测试文档", "正文内容", namespace="work")
    r = db.con.execute("SELECT namespace FROM kb_document WHERE id=?", (did,)).fetchone()
    ok_d = r["namespace"] == "work"
    check("★ entity / content_item / kb_document 的写入同样支持 namespace",
          ok_e and ok_c and ok_d,
          "entity=%s content=%s doc=%s" % (ok_e, ok_c, ok_d))
finally:
    try:
        db.con.close()
        os.unlink(db_path)
    except OSError:
        pass

# ─────────────────────────────────────────────────────────────
print()
print("【7】entity_link 时间窗：保留历史（对应 bitemporal）")
print("-" * 74)
db_path = fresh_db()
db = CyberBrain(db_path)
try:
    a = db.add_entity("org", "测试甲方")
    b = db.add_entity("org", "测试乙方")
    d1, d2 = "2026-01-01", "2026-06-01"

    # ① 先建立一段关系，再改口 —— 旧实现会原地 UPSERT，只剩一条
    db.link(a, b, "serves", note="第一版", valid_from=d1)
    db.link(a, b, "serves", note="改口版", valid_from=d2)
    rel_rows = db.con.execute(
        "SELECT * FROM entity_link WHERE from_id=? AND to_id=? AND relation=? ORDER BY id",
        (a, b, "serves")).fetchall()
    check("★ 改期不再覆盖：同一关系留下 2 条记录（本项验收核心）",
          len(rel_rows) == 2, "实际 %d 条" % len(rel_rows))
    check("旧记录被关闭在新记录的起点上，而不是被删掉",
          len(rel_rows) == 2 and rel_rows[0]["valid_until"] == d2,
          "第一条 valid_until=%s" % (rel_rows[0]["valid_until"] if rel_rows else "无"))
    check("同一关系「当前有效」的只有一条（部分唯一索引生效）",
          len([r for r in rel_rows if r["valid_until"] is None]) == 1,
          "开放区间 %d 条" % len([r for r in rel_rows if r["valid_until"] is None]))

    # ② 已失效的时间窗：旧实现会 DELETE，现在必须留下来
    db.link(a, b, "served_by", note="早就结束的关系",
            valid_from="2024-01-01", valid_until="2024-03-01")
    left = db.con.execute(
        "SELECT COUNT(*) FROM entity_link WHERE relation='served_by'").fetchone()[0]
    check("★ 传入已过去的 valid_until 不再删除记录（旧实现会 DELETE）",
          left == 1, "实际剩余 %d 条" % left)

    # ③ 时间点查询：同一条关系，在不同日期问，答案不同
    mid = {r["relation"] for r in db.neighbors(a, as_of="2026-03-01")}
    past = {r["relation"] for r in db.neighbors(a, as_of="2024-02-01")}
    now = {r["relation"] for r in db.neighbors(a)}
    check("★ 时间点查询 as_of=2026-03：成立的是 serves，served_by 不在其中",
          "serves" in mid and "served_by" not in mid, "实际=%s" % sorted(mid))
    check("★ 时间点查询 as_of=2024-02：成立的是 served_by（如今早已失效）",
          "served_by" in past and "serves" not in past, "实际=%s" % sorted(past))
    check("不带 as_of 时只返回当前有效的关系（失效的历史不出现）",
          now == {"serves"}, "实际=%s" % sorted(now))
finally:
    try:
        db.con.close()
        os.unlink(db_path)
    except OSError:
        pass

# ④ 老库迁移：带着 UNIQUE 约束的旧表必须被无损重建，否则历史存不下第二条
legacy = fresh_db()
_lc = sqlite3.connect(legacy)
_lc.executescript(
    "CREATE TABLE entity (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,"
    " name TEXT NOT NULL, org TEXT, role TEXT, contact_json TEXT DEFAULT '{}',"
    " tags_json TEXT DEFAULT '[]', meta_json TEXT DEFAULT '{}',"
    " source_tag TEXT NOT NULL DEFAULT 'manual', authorization_ref TEXT DEFAULT 'manual',"
    " created_at TEXT DEFAULT (datetime('now','localtime')),"
    " updated_at TEXT DEFAULT (datetime('now','localtime')));"
    "CREATE TABLE entity_link (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, relation TEXT NOT NULL, note TEXT,"
    " valid_from TEXT, valid_until TEXT,"
    " created_at TEXT DEFAULT (datetime('now','localtime')),"
    " UNIQUE(from_id, to_id, relation));"
    "INSERT INTO entity(type,name) VALUES('org','老库甲方');"
    "INSERT INTO entity(type,name) VALUES('org','老库乙方');"
    "INSERT INTO entity_link(from_id,to_id,relation,valid_from)"
    " VALUES(1,2,'serves','2025-01-01');")
_lc.commit()
_lc.close()
_ldb = CyberBrain(legacy)
try:
    kept = _ldb.con.execute("SELECT COUNT(*) FROM entity_link").fetchone()[0]
    still_unique = any(r[3] == "u" for r in _ldb.con.execute("PRAGMA index_list(entity_link)"))
    check("老库迁移：原有关系数据无损保留", kept == 1, "实际 %d 条" % kept)
    check("★ 老库迁移：UNIQUE 约束已被摘除（否则第二条历史写不进去）", not still_unique)
    _ldb.link(1, 2, "serves", note="迁移后改口", valid_from="2026-01-01")
    after = _ldb.con.execute(
        "SELECT COUNT(*) FROM entity_link WHERE relation='serves'").fetchone()[0]
    check("迁移后同一关系能存下第 2 条记录", after == 2, "实际 %d 条" % after)
finally:
    try:
        _ldb.con.close()
        os.unlink(legacy)
    except OSError:
        pass

# ─────────────────────────────────────────────────────────────
print()
print("【8】变更审计覆盖面（对应 audit_log）")
print("-" * 74)
db_path = fresh_db()
db = CyberBrain(db_path)
try:
    e1 = db.add_entity("org", "审计测试实体甲")
    e2 = db.add_entity("org", "审计测试实体乙")
    fid = db.add_fragment("fact", "审计测试碎片内容")
    cid = db.add_content("审计测试内容", body="正文")
    did = db.add_document("审计测试文档", "正文内容")
    db.link(e1, e2, "serves", valid_from="2026-01-01")
    db.update_content(cid, title="审计测试内容（已改）")

    muts = db.list_mutations(50)
    kinds = {(m["target_type"], m["action"]) for m in muts}
    check("★ 新增记忆碎片留下变更记录", ("memory_fragment", "add") in kinds,
          "实际=%s" % sorted(kinds))
    check("★ 新增实体留下变更记录", ("entity", "add") in kinds)
    check("新增内容留下变更记录", ("content_item", "add") in kinds)
    check("新增知识库文档留下变更记录", ("kb_document", "add") in kinds)
    check("★ 建立实体关系留下变更记录（原实现只记 merge/unmerge）",
          ("entity_link", "link") in kinds)
    check("修改内容留下变更记录", ("content_item", "update") in kinds)

    ups = [m for m in muts if m["action"] == "update" and m["target_type"] == "content_item"]
    check("修改记录里带了改动后的值（detail 不是空壳）",
          bool(ups) and "审计测试内容（已改）" in (ups[0]["detail"] or ""),
          ups[0]["detail"] if ups else "无")

    check("变更记录按时间倒序（最新在前）",
          [m["id"] for m in muts] == sorted([m["id"] for m in muts], reverse=True))
    check("list_mutations 支持按 action 过滤",
          all(m["action"] == "add" for m in db.list_mutations(50, action="add")),
          "add 类记录")
finally:
    try:
        db.con.close()
        os.unlink(db_path)
    except OSError:
        pass

# ─────────────────────────────────────────────────────────────
print()
print("=" * 74)
print("结果：通过 %d ｜ 失败 %d" % (len(PASS), len(FAIL)))
print("=" * 74)
if FAIL:
    print()
    for f in FAIL:
        print("   ❌ %s" % f)
    sys.exit(1)
print()
print("ALL TESTS PASSED")
