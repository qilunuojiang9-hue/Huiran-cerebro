#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 namespace 把一个分区剥离成可独立运行的赛博大脑库。

用途：多项目共用同一个库（用 namespace 分区），但对外提交/演示时，
      把某个项目的数据单独导出成一个干净的独立库，不带其它项目的内容。

用法：
    python export_namespace.py --namespace HomeForge --out D:/HomeForge-brain.db
        默认预演：只统计各表会导出多少行，不写文件

    python export_namespace.py --namespace HomeForge --out D:/HomeForge-brain.db --apply
        实际生成

    python export_namespace.py --namespace HomeForge --out x.db --apply --with-dict
        同时带上字典表（master_data / keyword_pack），一般不需要

设计要点：
  · 新库用 CyberBrain() 初始化，schema / 触发器 / 索引与主库一致
  · 用 ATTACH 直接 INSERT ... SELECT，保留原主键 → 外键关系天然正确
  · FTS 由触发器自动同步，无需手工重建
  · 只导出该 namespace 的行；子表（kb_chunk / entity_link / embeddings）靠父表关联
  · sys_profile 默认不导（含本机个人信息）
"""
import argparse
import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "cyber_brain.db")
sys.path.insert(0, HERE)


def q1(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return r[0] if r and r[0] is not None else 0


def plan(con, ns):
    """统计该 namespace 会导出多少行（预演用）"""
    doc_ids = "SELECT id FROM kb_document WHERE namespace=?"
    frag_ids = "SELECT id FROM memory_fragments WHERE namespace=?"
    ent_ids = "SELECT id FROM entity WHERE namespace=?"
    cnt_ids = "SELECT id FROM content_item WHERE namespace=?"
    chunk_ids = "SELECT id FROM kb_chunk WHERE doc_id IN (%s)" % doc_ids

    items = [
        ("entity", q1(con, "SELECT COUNT(*) FROM entity WHERE namespace=?", (ns,))),
        ("entity_link", q1(con,
            "SELECT COUNT(*) FROM entity_link WHERE from_id IN (%s) AND to_id IN (%s)"
            % (ent_ids, ent_ids), (ns, ns))),
        ("memory_fragments", q1(con, "SELECT COUNT(*) FROM memory_fragments WHERE namespace=?", (ns,))),
        ("kb_document", q1(con, "SELECT COUNT(*) FROM kb_document WHERE namespace=?", (ns,))),
        ("kb_chunk", q1(con, "SELECT COUNT(*) FROM kb_chunk WHERE doc_id IN (%s)" % doc_ids, (ns,))),
        ("content_item", q1(con, "SELECT COUNT(*) FROM content_item WHERE namespace=?", (ns,))),
        ("embeddings", q1(con, """
            SELECT COUNT(*) FROM embeddings WHERE
              (target_type='memory_fragment' AND target_id IN (%s))
           OR (target_type='content'         AND target_id IN (%s))
           OR (target_type='entity'          AND target_id IN (%s))
           OR (target_type='kb_chunk'        AND target_id IN (%s))
        """ % (frag_ids, cnt_ids, ent_ids, chunk_ids), (ns, ns, ns, ns))),
        ("rolling_summaries(不导)", q1(con, "SELECT COUNT(*) FROM rolling_summaries")),
    ]
    return items


def common_cols(con, table):
    """目标库与源库的公共列（按目标库顺序）。

    必须显式列出列名：老库经过多次 ALTER TABLE，列顺序与新库不同，
    用 SELECT * 会整体错位（实测：namespace 会拿到 created_at 的值）。
    """
    try:
        dst = [r[1] for r in con.execute("PRAGMA main.table_info(%s)" % table)]
    except sqlite3.Error:
        return []
    try:
        src = [r[1] for r in con.execute("PRAGMA src.table_info(%s)" % table)]
    except sqlite3.Error:
        return []
    return [c for c in dst if c in src]


def export(src, out, ns, with_dict=False):
    if os.path.abspath(src) == os.path.abspath(out):
        raise SystemExit("ERROR: --out 不能和源库同一个文件")
    if os.path.exists(out):
        raise SystemExit("ERROR: 目标已存在，先删掉或换个名字: %s" % out)

    from cyber_brain import CyberBrain
    # 用主库代码初始化一个全新的空库（schema/触发器/索引一致）
    nb = CyberBrain(out)
    nb.con.commit()
    nb.con.close()

    con = sqlite3.connect(out)
    con.execute("ATTACH DATABASE ? AS src", (src,))
    con.execute("PRAGMA foreign_keys=OFF")

    doc_ids = "SELECT id FROM src.kb_document WHERE namespace=?"
    frag_ids = "SELECT id FROM src.memory_fragments WHERE namespace=?"
    ent_ids = "SELECT id FROM src.entity WHERE namespace=?"
    cnt_ids = "SELECT id FROM src.content_item WHERE namespace=?"
    chunk_ids = "SELECT id FROM src.kb_chunk WHERE doc_id IN (%s)" % doc_ids

    steps = [
        ("entity", "namespace=?", (ns,)),
        ("entity_link",
         "from_id IN (%s) AND to_id IN (%s)" % (ent_ids, ent_ids), (ns, ns)),
        ("memory_fragments", "namespace=?", (ns,)),
        ("kb_document", "namespace=?", (ns,)),
        ("kb_chunk", "doc_id IN (%s)" % doc_ids, (ns,)),
        ("content_item", "namespace=?", (ns,)),
        ("embeddings", """
            (target_type='memory_fragment' AND target_id IN (%s))
         OR (target_type='content'         AND target_id IN (%s))
         OR (target_type='entity'          AND target_id IN (%s))
         OR (target_type='kb_chunk'        AND target_id IN (%s))
        """ % (frag_ids, cnt_ids, ent_ids, chunk_ids), (ns, ns, ns, ns)),
    ]
    if with_dict:
        steps += [
            ("master_data", "1=1", ()),
            ("keyword_pack", "1=1", ()),
        ]

    done = []
    for name, where, args in steps:
        cols = common_cols(con, name)
        if not cols:
            done.append((name, "SKIP (表不存在或列不匹配)"))
            continue
        cl = ",".join(cols)
        sql = "INSERT INTO %s(%s) SELECT %s FROM src.%s WHERE %s" % (name, cl, cl, name, where)
        try:
            cur = con.execute(sql, args)
            done.append((name, cur.rowcount))
        except sqlite3.Error as e:
            done.append((name, "FAIL (%s)" % str(e)[:70]))
        # 子表依赖父表已插入，故顺序不可乱

    con.commit()
    con.execute("DETACH DATABASE src")
    con.close()
    return done


def verify(out, ns):
    """导完后自检：能否检索、namespace 是否干净"""
    con = sqlite3.connect(out)
    c = con.cursor()
    rows = []
    rows.append(("fragments", c.execute("SELECT COUNT(*) FROM memory_fragments").fetchone()[0]))
    rows.append(("kb_document", c.execute("SELECT COUNT(*) FROM kb_document").fetchone()[0]))
    rows.append(("kb_chunk", c.execute("SELECT COUNT(*) FROM kb_chunk").fetchone()[0]))
    rows.append(("content_item", c.execute("SELECT COUNT(*) FROM content_item").fetchone()[0]))
    rows.append(("entity", c.execute("SELECT COUNT(*) FROM entity").fetchone()[0]))
    rows.append(("embeddings", c.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]))
    # namespace 洁净度
    dirty = 0
    for t in ("memory_fragments", "kb_document", "content_item", "entity"):
        dirty += c.execute("SELECT COUNT(*) FROM %s WHERE namespace IS NOT ? AND namespace IS NOT NULL"
                           % t, (ns,)).fetchone()[0]
    # FTS 可用性
    try:
        fts = c.execute("SELECT COUNT(*) FROM fragment_fts").fetchone()[0]
    except sqlite3.Error:
        fts = "FAIL"
    # 孤儿 chunk
    orphan = c.execute("SELECT COUNT(*) FROM kb_chunk WHERE doc_id NOT IN (SELECT id FROM kb_document)").fetchone()[0]
    con.close()
    return rows, dirty, fts, orphan


def main():
    ap = argparse.ArgumentParser(description="按 namespace 剥离成独立库")
    ap.add_argument("--namespace", required=True, help="要导出的分区名")
    ap.add_argument("--out", required=True, help="输出的 .db 路径")
    ap.add_argument("--src", default=DEFAULT_SRC, help="源库（默认 cyber_brain.db）")
    ap.add_argument("--apply", action="store_true", help="实际写入（不加则只预演）")
    ap.add_argument("--with-dict", action="store_true", help="同时带字典表")
    a = ap.parse_args()

    ns = a.namespace
    if not os.path.exists(a.src):
        raise SystemExit("源库不存在: %s" % a.src)

    con = sqlite3.connect(a.src)
    exist = q1(con, "SELECT COUNT(*) FROM memory_fragments WHERE namespace=?", (ns,))
    exist += q1(con, "SELECT COUNT(*) FROM kb_document WHERE namespace=?", (ns,))
    exist += q1(con, "SELECT COUNT(*) FROM content_item WHERE namespace=?", (ns,))
    print("=" * 64)
    print("源库 : %s" % a.src)
    print("分区 : %s" % ns)
    print("=" * 64)
    if exist == 0:
        print("⚠️  该 namespace 下没有任何数据（fragments/kb/content 全为 0）")
        print("    可先检查分区名大小写是否一致。")
        con.close()
        return

    print("\n[预演] 将导出的行数：")
    for name, n in plan(con, ns):
        print("   %-24s %6s" % (name, n))
    con.close()

    if not a.apply:
        print("\n（预演结束，未写入任何文件。确认后加 --apply 执行）")
        return

    print("\n[执行] 生成 %s ..." % a.out)
    done = export(a.src, a.out, ns, with_dict=a.with_dict)
    for name, n in done:
        print("   %-24s %s" % (name, n))

    rows, dirty, fts, orphan = verify(a.out, ns)
    print("\n[自检]")
    for n, v in rows:
        print("   %-16s %6s" % (n, v))
    print("   %-16s %s" % ("跨分区污染", "无 ✅" if dirty == 0 else "❌ %d 行" % dirty))
    print("   %-16s %s" % ("FTS 索引", "✅ %s 行" % fts if fts != "FAIL" else "❌ 失败"))
    print("   %-16s %s" % ("孤儿 chunk", "无 ✅" if orphan == 0 else "❌ %d 行" % orphan))
    size = os.path.getsize(a.out) / 1024 / 1024
    print("   %-16s %.1f MB" % ("文件大小", size))
    print("\n完成：%s" % a.out)


if __name__ == "__main__":
    main()
