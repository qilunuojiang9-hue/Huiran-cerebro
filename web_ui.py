#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
塞博大脑 Web 界面（本地零操作使用）
启动：python web_ui.py  然后浏览器打开 http://127.0.0.1:8899
依赖：Flask（已装）、fastembed（向量检索，已装）

v2 更新：
- 搜索结果点击查看「详情抽屉」（含轻量 Markdown 渲染）
- 实体关系图谱：展示实体↔实体（entity_link）与实体↔文档（entity_doc）
- 内容条目支持在线编辑 / 删除
- 搜索分组筛选 + 展开全部
- Ctrl+K 聚焦搜索、视觉打磨
"""
import json
import os
import threading
from flask import Flask, request, jsonify
from cyber_brain import CyberBrain

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "cyber_brain.db")
app = Flask(__name__)
_lock = threading.Lock()
db = CyberBrain(DB)


def _ark_key():
    """读取火山方舟 API Key（~/.workbuddy/ark_config.json 或环境变量）。"""
    import urllib.request
    key = os.environ.get("ARK_API_KEY") or ""
    try:
        p = os.path.expanduser("~/.workbuddy/ark_config.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                key = key or (json.load(f).get("ARK_API_KEY") or "")
    except Exception:
        pass
    return key.strip()


_OLLAMA_BASE = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip().rstrip("/")


def _llm_chat(messages, model="deepseek-v4-flash-ga-260731", max_tokens=900, temperature=0.4,
              prefer_local=True):
    """AI 电脑中枢：本地 Ollama 优先，云端火山方舟兜底。

    prefer_local=True 时：如果设置了 OLLAMA_BASE_URL（或本机 11434 有 Ollama），
    先把 model 名映射到本地模型并调用；本地失败或未启用，才回退火山方舟。
    """
    import urllib.request
    # ---- 本地 Ollama 优先 ----
    if prefer_local:
        ok, ans = _ollama_chat(messages, model=model, max_tokens=max_tokens,
                               temperature=temperature)
        if ok:
            return True, ans
        # 本地失败（未装/未启动/模型缺失）→ 静默回退云端
    # ---- 云端火山方舟兜底 ----
    key = _ark_key()
    if not key:
        return False, "未配置火山方舟 API Key（~/.workbuddy/ark_config.json），且本地 Ollama 不可用"
    url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    body = json.dumps({
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        return True, d["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return False, f"LLM HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    except Exception as e:
        return False, f"LLM 调用失败: {e}"


def _ollama_chat(messages, model="deepseek-v4-flash-ga-260731", max_tokens=900, temperature=0.4):
    """调本地 Ollama（OpenAI 兼容端点 /v1/chat/completions）。

    模型名映射：云端模型名 → 本地可跑模型（先查 sys_profile 模型台账，再查内置映射表）。
    返回 (ok, text_or_error)；本地不可用返回 (False, 原因)。
    """
    import urllib.request
    try:
        url = _OLLAMA_BASE + "/v1/chat/completions"
        # 探测 Ollama 是否存活（2 秒超时）
        try:
            with urllib.request.urlopen(_OLLAMA_BASE + "/api/tags", timeout=2) as r:
                tags = json.loads(r.read().decode("utf-8")).get("models", [])
        except Exception:
            return False, "本地 Ollama 未启动或未设置 OLLAMA_BASE_URL"
        local_models = {m.get("name", "").split(":")[0]: m.get("name") for m in tags}
        lm = _local_model_for(model, local_models)
        if not lm:
            return False, "本地无可用模型"
        body = json.dumps({
            "model": lm, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=120) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        return True, d["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return False, f"Ollama HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    except Exception as e:
        return False, f"Ollama 调用失败: {e}"


# 云端模型名 → 本地模型名映射（按任务类型，越靠前越优先）
_LOCAL_MODEL_MAP = [
    # 推理/编程
    ("deepseek", "deepseek-r1:7b"),
    ("r1", "deepseek-r1:7b"),
    # 通用聊天
    ("qwen3", "qwen3:8b"),
    ("qwen", "qwen3:8b"),
    # 通用备用
    ("llama", "llama3.1:8b"),
    ("gemma", "gemma3:4b"),
    # 兜底：取第一个本地模型
    ("", None),
]


def _local_model_for(model, local_models):
    """把云端模型名映射到本地已装模型；优先查 sys_profile 台账，再查内置映射。"""
    # 1) 用户显式指定本地模型名（model 本身就是本地名）
    if model in local_models:
        return local_models[model]
    # 2) 内置映射表
    for key, target in _LOCAL_MODEL_MAP:
        if key and key in model.lower():
            # 映射目标按基础名匹配已装模型
            base = target.split(":")[0]
            if base in local_models:
                return local_models[base]
    # 3) 兜底：第一个已装模型
    if local_models:
        return sorted(local_models.values())[0]
    return None



def _run(fn, *a, **k):
    with _lock:
        return fn(*a, **k)


def _bg_index():
    try:
        with _lock:
            db.index_vectors()
    except Exception:
        pass


def _row(r):
    return dict(r) if r is not None else None


@app.get("/")
def index():
    return HTML


@app.get("/api/stats")
def api_stats():
    return jsonify(_run(db.stats))


@app.post("/api/search")
def api_search():
    d = request.get_json(force=True, silent=True) or {}
    q = (d.get("q") or "").strip()
    if not q:
        return jsonify({"error": "q 必填"}), 400
    limit = int(d.get("limit") or 8)
    ns = (d.get("namespace") or "").strip() or None
    return jsonify(_run(db.search, q, limit=limit, namespace=ns))


@app.post("/api/recall")
def api_recall():
    d = request.get_json(force=True, silent=True) or {}
    q = d.get("q") or ""
    lines = _run(db.recall, q if q.strip() else None)
    return jsonify(lines)


@app.get("/api/probe")
def api_probe():
    """AI 电脑中枢：硬件探针 + 本地模型台账。

    返回本机 CPU / 内存 / GPU(显存) / 磁盘 / Ollama 已装模型 / 推理引擎状态，
    供 Web UI「电脑大脑」标签页展示。所有探测均容错，探测失败项返回 None。
    """
    import platform as _plat
    import shutil as _shutil
    info = {
        "hostname": _plat.node(),
        "os": _plat.system() + " " + _plat.release(),
        "python": _plat.python_version(),
        "cpu": None, "cpu_cores": None,
        "mem_total_gb": None, "mem_free_gb": None,
        "gpu": [],            # [{"name":..., "vram_gb":...}]
        "disk_free_gb": None, "disk_total_gb": None,
        "ollama": {"up": False, "base": _OLLAMA_BASE, "models": []},
        "engine": "local" if _ollama_up() else "cloud",
    }
    try:
        import psutil as _ps
        info["cpu"] = _ps.cpu_freq().current if _ps.cpu_freq() else None
        info["cpu_cores"] = _ps.cpu_count(logical=True)
        vm = _ps.virtual_memory()
        info["mem_total_gb"] = round(vm.total / 2**30, 1)
        info["mem_free_gb"] = round(vm.available / 2**30, 1)
    except Exception:
        pass
    # GPU（NVIDIA 用 nvidia-smi，其它容错）
    try:
        import subprocess as _sp
        out = _sp.run(["nvidia-smi", "--query-gpu=name,memory.total",
                       "--format=csv,noheader,nounits"],
                      capture_output=True, text=True, timeout=5).stdout.strip()
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                info["gpu"].append({"name": parts[0], "vram_gb": round(int(parts[1]) / 1024, 1)})
    except Exception:
        pass
    try:
        du = _shutil.disk_usage("/")
        info["disk_free_gb"] = round(du.free / 2**30, 1)
        info["disk_total_gb"] = round(du.total / 2**30, 1)
    except Exception:
        pass
    # Ollama 模型台账
    try:
        import urllib.request
        with urllib.request.urlopen(_OLLAMA_BASE + "/api/tags", timeout=2) as r:
            tags = json.loads(r.read().decode("utf-8")).get("models", [])
        info["ollama"]["up"] = True
        for m in tags:
            name = m.get("name", "")
            info["ollama"]["models"].append({
                "name": name,
                "size_gb": round((m.get("size") or 0) / 2**30, 2),
                "family": (m.get("details") or {}).get("family", ""),
                "quant": (m.get("details") or {}).get("quantization_level", ""),
            })
    except Exception:
        info["ollama"]["up"] = False
    return jsonify(info)


def _ollama_up():
    """轻量探测 Ollama 是否存活。"""
    try:
        import urllib.request
        with urllib.request.urlopen(_OLLAMA_BASE + "/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


@app.get("/api/profile")
def api_profile():
    """AI 电脑中枢：系统台账（模型/硬件/设置）。key 可选。"""
    key = request.args.get("key") or None
    return jsonify(_run(db.get_profile, key))


@app.post("/api/profile")
def api_profile_set():
    """AI 电脑中枢：写入系统台账。body: {key, value, kind?, note?}"""
    d = request.get_json(force=True, silent=True) or {}
    key = (d.get("key") or "").strip()
    if not key:
        return jsonify({"error": "key 必填"}), 400
    _run(db.set_profile, key, d.get("value"), kind=d.get("kind") or "setting",
         note=d.get("note"))
    return jsonify({"ok": True})


@app.post("/api/ask")
def api_ask():
    """P2 LLM RAG 问答：检索相关记忆/文档 → 拼 prompt → 火山方舟生成答案 → 返回引用来源。"""
    d = request.get_json(force=True, silent=True) or {}
    q = (d.get("q") or "").strip()
    if not q:
        return jsonify({"error": "q 必填"}), 400
    ns = (d.get("namespace") or "").strip() or None
    # 1) 检索增强：记忆 + 语义 + 知识库
    ctx = []
    try:
        for r in _run(db.search_memory, q, limit=6, audit=False, namespace=ns):
            ctx.append(("[记忆#" + str(r["id"]) + "] " + (r["content"] or "")).strip())
    except Exception:
        pass
    try:
        for h in _run(db.search_semantic, q, limit=6, namespace=ns):
            if h["type"] in ("memory_fragment", "kb_chunk"):
                ctx.append(("[" + h["type"] + "#" + str(h["id"]) + "] " + (h["text"] or "")).strip())
    except Exception:
        pass
    # 实体信息也带上（客户/平台等关键事实）
    try:
        import json as _json
        for e in _run(db.search_entities, q, limit=6, namespace=ns):
            e = dict(e)
            extra = ""
            meta = e.get("meta_json") or "{}"
            try:
                m = _json.loads(meta) if isinstance(meta, str) else (meta or {})
                if isinstance(m, dict):
                    parts = [str(v) for k, v in m.items()
                             if k in ("industry", "status", "upload_pack", "desc", "profile") and v]
                    if parts:
                        extra = "；" + "；".join(parts)
            except Exception:
                pass
            ctx.append(("[实体#" + str(e["id"]) + " " + (e["name"] or "") + "]" +
                        (" " + (e["org"] or "") if e["org"] else "") + extra).strip())
    except Exception:
        pass
    # 客户台账关系（汉全出海 → serves → 各客户），让"服务哪些客户"能答出具体名字
    # 时间有效性：valid_until 已过期（<今天）的客户关系不再计入
    try:
        with _lock:
            today = __import__("datetime").date.today().isoformat()
            custs = db.con.execute(
                "SELECT e.name, e.meta_json FROM entity_link l "
                "JOIN entity e ON e.id=l.to_id WHERE l.relation='serves' "
                "AND (l.valid_until IS NULL OR l.valid_until>=?) "
                "ORDER BY e.id", (today,)).fetchall()
        if custs:
            names = []
            for c in custs:
                c = dict(c)
                meta = c.get("meta_json") or "{}"
                try:
                    m = _json.loads(meta) if isinstance(meta, str) else (meta or {})
                    ind = (m or {}).get("industry", "") if isinstance(m, dict) else ""
                except Exception:
                    ind = ""
                names.append((c.get("name") or "") + (f"（{ind}）" if ind else ""))
            if names:
                ctx.append("[客户台账] 汉全出海服务客户：" + "、".join(names))
    except Exception:
        pass
    seen, uniq = set(), []
    for c in ctx:
        k = c[:40]
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    ctx = uniq[:18]
    refs = [{"kind": ("实体" if c.startswith("[实体") else "记忆"),
             "src": c[:100]} for c in ctx[:8]]
    # 2) 拼 prompt
    sys_p = ("你是赛博大脑的问答助手。基于下面检索到的资料回答问题。"
             "若资料不足以回答，明确说'资料中未找到'，不要编造。"
             "回答用简体中文，简洁、分点。")
    user_p = "检索到的资料：\n" + ("\n".join(ctx) if ctx else "（无）") + \
             "\n\n问题：" + q
    ok, ans = _llm_chat([{"role": "system", "content": sys_p},
                         {"role": "user", "content": user_p}])
    if not ok:
        return jsonify({"answer": "", "error": ans}), 502
    return jsonify({"answer": ans, "refs": refs, "ctx_n": len(ctx)})



@app.get("/api/daily")
def api_daily():
    return jsonify(_run(db.daily_context))


@app.post("/api/add")
def api_add():
    d = request.get_json(force=True, silent=True) or {}
    kind = d.get("kind")
    result = None
    try:
        if kind == "content":
            tags = d.get("tags") or []
            if not tags and (d.get("body") or d.get("title")):
                tags = _auto_tag((d.get("title") or "") + "\n" + (d.get("body") or ""))
            result = {"id": _run(db.add_content, d.get("title", ""), d.get("body", ""),
                                 ctype=d.get("type", "note"), status=d.get("status", "draft"),
                                 category=d.get("category"), tags=tags or None,
                                 source_tag=d.get("source_tag", "manual"))}
        elif kind == "entity":
            result = {"id": _run(db.add_entity, d.get("type", "other"), d.get("name", ""),
                                 org=d.get("org"), role=d.get("role"), tags=d.get("tags"))}
        elif kind == "fragment":
            tags = d.get("tags") or []
            if not tags and d.get("content"):
                tags = _auto_tag(d.get("content"))
            result = {"id": _run(db.add_fragment, d.get("ftype", "fact"), d.get("content", ""),
                                 subject=d.get("subject", "work"), tags=tags or None)}
        elif kind == "doc":
            result = {"id": _run(db.add_document, d.get("title", ""), d.get("text", ""),
                                 source=d.get("source"))}
        elif kind == "link":
            _run(db.link, int(d.get("from")), int(d.get("to")),
                 d.get("relation", ""), d.get("note"),
                 valid_from=d.get("valid_from"), valid_until=d.get("valid_until"))
            result = {"ok": True}
        else:
            return jsonify({"error": "未知 kind"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    if kind in ("content", "fragment", "doc"):
        threading.Thread(target=_bg_index, daemon=True).start()
    return jsonify(result)


def _auto_tag(text, max_tags=4):
    """P2 自动打标：用 LLM 给文本生成 2-4 个简短标签。失败返回 []。"""
    text = (text or "").strip()
    if not text or len(text) < 8:
        return []
    try:
        sys_p = ("你是标签生成器。给下面文本生成 2-4 个中文标签（每个不超过 6 个字），"
                 "用逗号分隔，只输出标签本身，不要序号和解释。")
        ok, ans = _llm_chat([{"role": "system", "content": sys_p},
                             {"role": "user", "content": text[:800]}], max_tokens=60, temperature=0.2)
        if not ok:
            return []
        tags = [t.strip() for t in ans.replace("，", ",").split(",") if t.strip()]
        return tags[:max_tags]
    except Exception:
        return []


@app.get("/api/list")
def api_list():
    kind = request.args.get("kind", "content")
    typ = request.args.get("type")
    with _lock:
        if kind == "content":
            rows = db.list_content(typ, limit=200)
        elif kind == "entity":
            rows = db.list_entities(typ, limit=200)
        elif kind == "fragment":
            rows = db.list_fragments(typ, limit=200)
        elif kind == "doc":
            rows = db.list_documents(limit=200)
        else:
            return jsonify({"error": "未知 kind"}), 400
    return jsonify([dict(r) for r in rows])


@app.post("/api/index")
def api_index():
    d = request.get_json(force=True, silent=True) or {}
    with _lock:
        n = db.index_vectors(reset=bool(d.get("reset")))
        total = db.stats()["embeddings"]
    return jsonify({"added": n, "total": total})


# ---------------------------------------------------------------- v2 新增接口

@app.get("/api/detail")
def api_detail():
    """统一详情：kind=content|entity|doc|memory|chunk"""
    kind = request.args.get("kind", "")
    rid = request.args.get("id", "")
    try:
        rid = int(rid)
    except Exception:
        return jsonify({"error": "id 必须为数字"}), 400
    with _lock:
        if kind == "content":
            row = db.get_content(rid)
            data = _row(row)
        elif kind == "entity":
            row = db.get_entity(rid)
            if not row:
                return jsonify({"error": "实体不存在"}), 404
            ent = _row(row)
            links = db.neighbors(rid)                       # entity_link
            docs = [dict(r) for r in db.con.execute(
                "SELECT ed.relation AS relation, d.id AS doc_id, d.title AS title, "
                "d.source AS source, d.created_at AS created_at "
                "FROM entity_doc ed JOIN kb_document d ON d.id=ed.doc_id "
                "WHERE ed.entity_id=?", (rid,))]
            data = {"entity": ent, "links": links, "docs": docs}
        elif kind == "doc":
            row = db.con.execute("SELECT * FROM kb_document WHERE id=?", (rid,)).fetchone()
            if not row:
                return jsonify({"error": "文档不存在"}), 404
            data = {"doc": _row(row),
                    "chunks": [dict(r) for r in db.get_document_chunks(rid)]}
        elif kind in ("memory", "fragment"):
            row = db.con.execute("SELECT * FROM memory_fragments WHERE id=?", (rid,)).fetchone()
            data = _row(row)
        elif kind == "chunk":
            row = db.con.execute("SELECT * FROM kb_chunk WHERE id=?", (rid,)).fetchone()
            if not row:
                return jsonify({"error": "片段不存在"}), 404
            ch = _row(row)
            doc_id = ch["doc_id"]
            drow = db.con.execute("SELECT * FROM kb_document WHERE id=?", (doc_id,)).fetchone()
            data = {"doc": _row(drow),
                    "chunks": [dict(r) for r in db.get_document_chunks(doc_id)],
                    "highlight": rid}
        else:
            return jsonify({"error": "未知 kind"}), 400
    return jsonify({"kind": kind, "data": data})


@app.post("/api/update")
def api_update():
    d = request.get_json(force=True, silent=True) or {}
    kind = d.get("kind")
    rid = int(d.get("id", 0) or 0)
    if kind != "content" or not rid:
        return jsonify({"error": "仅支持 content 更新"}), 400
    fields = {}
    for k in ("title", "body", "status", "category", "content_type", "platform",
              "source_type", "source_tag", "tags"):
        if k in d and d[k] is not None:
            fields[k] = d[k]
    try:
        _run(db.update_content, rid, **fields)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    threading.Thread(target=_bg_index, daemon=True).start()
    return jsonify({"ok": True, "id": rid})


@app.post("/api/delete")
def api_delete():
    d = request.get_json(force=True, silent=True) or {}
    kind = d.get("kind")
    rid = int(d.get("id", 0) or 0)
    if kind != "content" or not rid:
        return jsonify({"error": "仅支持 content 删除"}), 400
    with _lock:
        db.delete_content(rid)
    return jsonify({"ok": True, "id": rid})


@app.get("/api/entity_search")
def api_entity_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    with _lock:
        rows = db.search_entities(q, limit=50)
    out = [{"id": r["id"], "name": r["name"], "type": r["type"],
            "org": r["org"] or ""} for r in rows]

    # 排序优化：精确名 > 名称前缀 > 名称包含 > 仅组织字段命中
    def rank(e):
        n, o = e["name"], e["org"]
        if n == q:
            return 0
        if n.startswith(q):
            return 1
        if q in n:
            return 2
        if q in o:
            return 3
        return 4
    out.sort(key=lambda e: (rank(e), -e["id"]))
    return jsonify(out[:20])


@app.get("/api/graph")
def api_graph():
    """返回实体关系图：节点 + 边。可选 center=<id> 做 1 跳子图。"""
    center = request.args.get("center", "").strip()
    try:
        center = int(center) if center else None
    except Exception:
        center = None
    with _lock:
        nodes = [dict(r) for r in db.con.execute(
            "SELECT id, name, type, org, role FROM entity ORDER BY id")]
        edges = [dict(r) for r in db.con.execute(
            "SELECT from_id, to_id, relation, valid_from, valid_until FROM entity_link")]
        # 时间有效性过滤：valid_until 已过期（<今天）的边不再画入图谱
        today = __import__("datetime").date.today().isoformat()
        edges = [e for e in edges
                 if not e.get("valid_until") or e["valid_until"] >= today]
    deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        deg[e["from_id"]] = deg.get(e["from_id"], 0) + 1
        deg[e["to_id"]] = deg.get(e["to_id"], 0) + 1
    if center:
        keep = {center}
        for e in edges:
            if e["from_id"] == center:
                keep.add(e["to_id"])
            if e["to_id"] == center:
                keep.add(e["from_id"])
        nodes = [n for n in nodes if n["id"] in keep]
    else:
        keep = {n["id"] for n in nodes}
    out_nodes = [{"id": n["id"], "name": n["name"], "type": n["type"],
                  "org": n["org"] or "", "role": n["role"] or "",
                  "degree": deg.get(n["id"], 0)} for n in nodes]
    out_edges = [{"from": e["from_id"], "to": e["to_id"],
                  "relation": e["relation"] or "",
                  "valid_from": e.get("valid_from") or "",
                  "valid_until": e.get("valid_until") or ""} for e in edges
                 if e["from_id"] in keep and e["to_id"] in keep]
    return jsonify({"nodes": out_nodes, "edges": out_edges, "total": len(out_nodes)})


@app.get("/api/conflicts")
def api_conflicts():
    """P0 冲突消解：返回记忆打架候选（只读，不删不改）。"""
    limit = int(request.args.get("limit", 80))
    return jsonify({"conflicts": _run(db.detect_conflicts, limit)})


@app.get("/api/links")
def api_links():
    """列出所有实体关系（含时间窗口），供前台展示/编辑。"""
    with _lock:
        rows = [dict(r) for r in db.con.execute(
            "SELECT l.id, l.from_id, a.name AS from_name, l.to_id, b.name AS to_name, "
            "l.relation, l.note, l.valid_from, l.valid_until, l.created_at "
            "FROM entity_link l JOIN entity a ON a.id=l.from_id JOIN entity b ON b.id=l.to_id "
            "ORDER BY l.id DESC LIMIT 300")]
    return jsonify({"links": rows})


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>塞博大脑 · Cyber Brain</title>
<style>
:root{--bg:#f4f6fa;--card:#ffffff;--line:#e3e8f0;--ink:#1f2937;--sub:#6b7280;--blue:#185FA5;--blue-l:#e6f1fb;--amber:#b45309;--amber-l:#fdf3e7;--green:#0f6e56;--green-l:#e1f5ee;--red:#a32d2d;--red-l:#fcebeb;--violet:#6d28d9;--violet-l:#f1e9fd}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;font-size:14px;line-height:1.6}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px 80px}
header{position:sticky;top:0;z-index:20;background:rgba(244,246,250,.92);backdrop-filter:blur(6px);display:flex;align-items:center;gap:12px;padding:14px 0 12px;margin-bottom:12px;flex-wrap:wrap;border-bottom:1px solid var(--line)}
header h1{font-size:20px;font-weight:700;color:var(--blue);letter-spacing:.5px}
header .tag{font-size:12px;color:var(--sub);background:var(--blue-l);border:1px solid #cfe3f7;padding:2px 10px;border-radius:999px}
.searchbar{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.searchbar input{flex:1;min-width:240px;padding:11px 15px;border:1px solid var(--line);border-radius:10px;font-size:15px;background:#fff;outline:none}
.searchbar input:focus{border-color:var(--blue);box-shadow:0 0 0 3px var(--blue-l)}
.btn{padding:9px 18px;border:0;border-radius:10px;cursor:pointer;font-size:14px;font-weight:500;transition:filter .15s}
.btn:hover{filter:brightness(.96)}
.btn.blue{background:var(--blue);color:#fff}
.btn.amber{background:var(--amber);color:#fff}
.btn.violet{background:var(--violet);color:#fff}
.btn.gray{background:#eef1f6;color:var(--ink);border:1px solid var(--line)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.hint{font-size:12px;color:var(--sub);margin:2px 0 10px}
.kbd{font-family:ui-monospace,Menlo,Consolas,monospace;background:#fff;border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:0 5px;font-size:11px}
.tabs{display:flex;gap:6px;margin:14px 0 12px;border-bottom:2px solid var(--line);flex-wrap:wrap}
.tab{padding:8px 16px;cursor:pointer;color:var(--sub);border-bottom:3px solid transparent;margin-bottom:-2px;font-size:14px}
.tab.on{color:var(--blue);border-bottom-color:var(--blue);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:12px}
.card h3{font-size:14px;color:var(--sub);font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.card h3 .n{background:var(--blue-l);color:var(--blue);border-radius:999px;padding:0 8px;font-size:12px}
.recall{border-left:4px solid var(--amber);background:var(--amber-l)}
.recall h3{color:var(--amber)}
.filterbar{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 4px}
.fchip{padding:3px 11px;border-radius:999px;border:1px solid var(--line);background:#fff;cursor:pointer;font-size:12px;color:var(--sub);user-select:none}
.fchip.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.item{padding:9px 10px;border:1px solid transparent;border-bottom:1px dashed var(--line);border-radius:8px;cursor:pointer;transition:background .12s}
.item:hover{background:var(--blue-l);border-color:#cfe3f7}
.item:last-child{border-bottom:0}
.item .t{font-weight:600}
.item .s{color:var(--sub);font-size:12px}
.item .b{color:#374151;margin-top:2px;white-space:pre-wrap;font-size:13px}
.score{display:inline-block;min-width:52px;text-align:center;font-size:12px;border-radius:6px;padding:1px 6px;margin-right:6px}
.score.hi{background:var(--green-l);color:var(--green)}
.score.mid{background:var(--amber-l);color:var(--amber)}
.score.lo{background:var(--red-l);color:var(--red)}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center}
.stat .v{font-size:22px;font-weight:700;color:var(--blue)}
.stat .k{font-size:12px;color:var(--sub);margin-top:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}
label{display:block;font-size:12px;color:var(--sub);margin:8px 0 4px}
input,select,textarea{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-size:14px;background:#fff;outline:none;font-family:inherit}
textarea{min-height:90px;resize:vertical}
input:focus,select:focus,textarea:focus{border-color:var(--blue)}
.form-row{display:flex;gap:8px;flex-wrap:wrap}
.form-row>*{flex:1;min-width:120px}
.form-actions{margin-top:12px;display:flex;gap:8px;justify-content:flex-end}
.hidden{display:none}
.msg{position:fixed;right:18px;bottom:18px;background:#111827;color:#fff;padding:10px 16px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .3s;z-index:99;max-width:70vw}
.msg.show{opacity:.95}
.empty{color:var(--sub);text-align:center;padding:24px;font-size:13px}
.pill{display:inline-block;font-size:11px;padding:1px 8px;border-radius:999px;margin-left:6px;background:#eef1f6;color:var(--sub)}
.pill.type{background:var(--blue-l);color:var(--blue)}
.pill.status{background:var(--green-l);color:var(--green)}
.pill.violet{background:var(--violet-l);color:var(--violet)}
.list-tabs{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.ltab{padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:#fff;cursor:pointer;font-size:13px;color:var(--sub)}
.ltab.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.linkform{display:grid;grid-template-columns:1fr 1fr 1.2fr 1fr;gap:8px;align-items:end}
.linkform label{margin:0}
.tinybtn{font-size:12px;padding:3px 9px;border-radius:7px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--sub)}
.tinybtn:hover{background:#f0f3f8}
/* 详情抽屉 */
.overlay{position:fixed;inset:0;background:rgba(15,23,42,.42);z-index:50;opacity:0;pointer-events:none;transition:opacity .2s}
.overlay.show{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;height:100%;width:min(640px,94vw);background:#fff;z-index:60;box-shadow:-8px 0 30px rgba(0,0,0,.18);transform:translateX(100%);transition:transform .24s ease;display:flex;flex-direction:column}
.drawer.show{transform:translateX(0)}
.drawer-head{display:flex;align-items:center;gap:8px;padding:14px 16px;border-bottom:1px solid var(--line);background:var(--blue-l)}
.drawer-head .tt{font-weight:700;color:var(--blue);font-size:15px;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.drawer-body{padding:16px;overflow:auto;flex:1}
.md h1,.md h2,.md h3{color:var(--blue);margin:14px 0 6px;line-height:1.3}
.md h1{font-size:18px}.md h2{font-size:16px}.md h3{font-size:14px}
.md p{margin:8px 0}
.md ul,.md ol{margin:8px 0 8px 22px}
.md li{margin:3px 0}
.md code{background:#f1f5f9;padding:1px 5px;border-radius:5px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.md pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:10px;overflow:auto;margin:8px 0}
.md pre code{background:none;color:inherit;padding:0}
.md a{color:var(--blue);text-decoration:underline}
.md strong{color:var(--ink)}
.rel{display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px;cursor:pointer;transition:background .12s}
.rel:hover{background:var(--blue-l)}
.rel .badge{font-size:11px;padding:1px 8px;border-radius:999px;background:var(--violet-l);color:var(--violet)}
.rel .badge.doc{background:var(--green-l);color:var(--green)}
.rel .arrow{color:var(--sub);font-size:12px}
.chunk{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px;font-size:13px;white-space:pre-wrap}
.chunk.hl{border-color:var(--amber);background:var(--amber-l)}
.chunk .seq{font-size:11px;color:var(--sub);margin-bottom:3px}
.editgrid{display:grid;gap:10px}
.editgrid textarea{min-height:160px}
.modal-btns{display:flex;gap:8px;margin-top:14px;justify-content:flex-end}
.closex{font-size:20px;cursor:pointer;color:var(--sub);line-height:1}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>塞博大脑</h1>
  <span class="tag">三源融合 · 工作知识库</span>
  <span id="embInfo" class="tag"></span>
</header>

<div class="searchbar">
  <input id="q" placeholder="搜什么？例如：收款 / 企鹅号 / 选题 / 发布红线 / 德孚润滑油" onkeydown="if(event.key==='Enter')doSearch()">
  <input id="ns" placeholder="命名空间(可选: 默认 default)" style="max-width:180px" title="多项目隔离：只搜某个命名空间">
  <button class="btn blue" onclick="doSearch()">搜索</button>
  <button class="btn amber" onclick="doRecall()">回忆（防遗忘）</button>
  <button class="btn gray" onclick="doDaily()">开工上下文</button>
  <button class="btn violet" onclick="reindex()">重建索引</button>
</div>
<div class="hint">提示：搜索结果 <b>点击任意条目</b> 可看完整详情（含 Markdown 渲染、实体关系、关联文档）；按 <span class="kbd">Ctrl</span>+<span class="kbd">K</span> 聚焦搜索框。</div>

<div id="results"></div>

<div class="tabs">
  <div class="tab on" data-tab="search" onclick="switchTab('search')">检索</div>
  <div class="tab" data-tab="add" onclick="switchTab('add')">录入</div>
  <div class="tab" data-tab="browse" onclick="switchTab('browse')">浏览</div>
  <div class="tab" data-tab="rel" onclick="switchTab('rel')">实体关系</div>
  <div class="tab" data-tab="graph" onclick="switchTab('graph')">关系图谱</div>
  <div class="tab" data-tab="ask" onclick="switchTab('ask')">AI 问答</div>
  <div class="tab" data-tab="conflict" onclick="switchTab('conflict')">冲突检测</div>
</div>

<div id="panel-search" class="panel">
  <div class="card"><div class="empty">输入关键词搜索：命中内容 / 实体 / 记忆 / 知识库，以及「语义相似」结果；点「回忆」带回记忆碎片 + 滚动摘要防遗忘。</div></div>
</div>

<div id="panel-add" class="panel hidden">
  <div class="list-tabs" id="addTabs">
    <span class="ltab on" data-kind="content" onclick="switchAdd('content')">内容/笔记</span>
    <span class="ltab" data-kind="entity" onclick="switchAdd('entity')">实体</span>
    <span class="ltab" data-kind="fragment" onclick="switchAdd('fragment')">记忆碎片</span>
    <span class="ltab" data-kind="doc" onclick="switchAdd('doc')">文档入库</span>
    <span class="ltab" data-kind="link" onclick="switchAdd('link')">关联</span>
  </div>
  <div class="card" id="form-content">
    <div class="grid">
      <div>
        <label>标题 *</label><input id="c_title">
        <label>正文</label><textarea id="c_body"></textarea>
      </div>
      <div>
        <div class="form-row">
          <div><label>类型</label><select id="c_type"><option value="note">笔记</option><option value="task">任务</option><option value="decision">决策</option><option value="meeting">会议</option><option value="idea">想法</option><option value="issue">问题</option><option value="article">文章</option></select></div>
          <div><label>类目/赛道</label><input id="c_cat" placeholder="独立站/跨境支付/..."></div>
        </div>
        <label>标签（逗号分隔）</label><input id="c_tags" placeholder="标签1,标签2">
        <label>来源标记（合规）</label><input id="c_src" placeholder="manual / web / content_brain">
      </div>
    </div>
    <div class="form-actions"><button class="btn blue" onclick="addContent()">保存内容</button></div>
  </div>
  <div class="card hidden" id="form-entity">
    <div class="grid">
      <div>
        <label>名称 *</label><input id="e_name">
        <label>所属组织</label><input id="e_org">
      </div>
      <div>
        <div class="form-row">
          <div><label>类型</label><select id="e_type"><option value="org">组织/公司</option><option value="person">人</option><option value="project">项目</option><option value="account">账号</option><option value="platform">平台</option><option value="product">产品</option><option value="tool">工具</option><option value="other">其他</option></select></div>
          <div><label>角色/备注</label><input id="e_role"></div>
        </div>
        <label>标签（逗号分隔）</label><input id="e_tags">
      </div>
    </div>
    <div class="form-actions"><button class="btn blue" onclick="addEntity()">保存实体</button></div>
  </div>
  <div class="card hidden" id="form-fragment">
    <label>记忆内容 *（事实/偏好/情绪/知识/决策）</label><textarea id="f_content"></textarea>
    <div class="form-row">
      <div><label>类型</label><select id="f_type"><option value="fact">事实</option><option value="knowledge">知识</option><option value="decision">决策</option><option value="preference">偏好</option><option value="emotion">情绪</option></select></div>
      <div><label>主体</label><input id="f_subject" value="work"></div>
      <div><label>标签</label><input id="f_tags" placeholder="发布,合规,..."></div>
    </div>
    <div class="form-actions"><button class="btn blue" onclick="addFragment()">保存记忆</button></div>
  </div>
  <div class="card hidden" id="form-doc">
    <label>文档标题 *</label><input id="d_title">
    <label>文档内容（自动分块进知识库）</label><textarea id="d_text" style="min-height:140px"></textarea>
    <label>来源</label><input id="d_source" placeholder="URL / 文件路径 / 出处">
    <div class="form-actions"><button class="btn blue" onclick="addDoc()">入库</button></div>
  </div>
  <div class="card hidden" id="form-link">
    <div class="linkform">
      <div><label>从（实体ID）</label><input id="l_from" type="number"></div>
      <div><label>到（实体ID）</label><input id="l_to" type="number"></div>
      <div><label>关系</label><input id="l_rel" placeholder="belongs_to / partner / ..."></div>
      <div><label>备注</label><input id="l_note"></div>
      <div><label>生效日（可选）</label><input id="l_valid_from" placeholder="YYYY-MM-DD，留空=一直有效"></div>
      <div><label>失效日（可选）</label><input id="l_valid_until" placeholder="YYYY-MM-DD，留空=永不过期"></div>
    </div>
    <div class="form-actions"><button class="btn blue" onclick="addLink()">建立关联</button></div>
  </div>
</div>

<div id="panel-browse" class="panel hidden">
  <div class="card"><div class="stats" id="statGrid"></div></div>
  <div class="card">
    <div class="list-tabs" id="listTabs">
      <span class="ltab on" data-kind="content" onclick="switchList('content')">内容</span>
      <span class="ltab" data-kind="entity" onclick="switchList('entity')">实体</span>
      <span class="ltab" data-kind="fragment" onclick="switchList('fragment')">记忆</span>
      <span class="ltab" data-kind="doc" onclick="switchList('doc')">知识库</span>
    </div>
    <div id="listFilter" class="filterbar hidden"></div>
    <div id="listBody"><div class="empty">加载中...</div></div>
  </div>
</div>

<div id="panel-rel" class="panel hidden">
  <div class="card">
    <label>按名称查实体（支持模糊，回车搜索）</label>
    <div class="form-row">
      <div style="flex:3"><input id="relQ" placeholder="如：汉全科技 / 德孚 / 慕思" onkeydown="if(event.key==='Enter')searchEntity()"></div>
      <div style="flex:1"><button class="btn blue" onclick="searchEntity()">查实体</button></div>
    </div>
    <div id="relMatches" style="margin-top:8px"></div>
  </div>
  <div id="relDetail"></div>
</div>

<div id="panel-graph" class="panel hidden">
  <div class="card">
    <h3>实体关系知识图谱 <span class="n">力导向可视化</span></h3>
    <div class="hint">拖拽节点排布 · 单击节点查看详情（复用记忆抽屉）· 悬停高亮关联 · 滚轮缩放 · 双击空白重置视图</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0">
      <button class="btn gray" onclick="Grestart()">重新布局</button>
      <button class="btn gray" onclick="Gfit()">自适应视图</button>
      <select id="gCenterSel" onchange="GcenterChange()" style="width:auto;max-width:240px"><option value="">全量图谱</option></select>
      <span id="gInfo" class="hint"></span>
    </div>
    <canvas id="gcanvas" style="width:100%;height:580px;border:1px solid var(--line);border-radius:12px;background:#fff;cursor:grab;touch-action:none"></canvas>
  </div>
</div>

<div id="panel-ask" class="panel hidden">
  <div class="card">
    <h3>AI 问答 <span class="n">RAG · 检索增强</span></h3>
    <div class="hint">直接对赛博大脑提问，例如「我们给慕思定过什么红线？」「汉全出海服务哪些客户？」「发布铁律是什么？」。答案由火山方舟 LLM 基于库内记忆/文档生成。</div>
    <div class="form-row">
      <div style="flex:3"><input id="askQ" placeholder="问赛博大脑一个问题…" onkeydown="if(event.key==='Enter')askBrain()"></div>
      <div style="flex:1"><button class="btn violet" onclick="askBrain()">提问</button></div>
    </div>
    <div id="askRes" style="margin-top:12px"><div class="empty">输入问题开始 RAG 问答</div></div>
  </div>
</div>

<div id="panel-conflict" class="panel hidden">
  <div class="card">
    <h3>冲突检测 <span class="n">记忆打架 · 只读报告</span></h3>
    <div class="hint">扫描记忆碎片，找出互相矛盾的信息（行业/配置/状态/价格等敏感字段）。只报告、不删除、不修改，供你人工确认后处理。</div>
    <div class="form-row">
      <div style="flex:1"><button class="btn amber" onclick="scanConflicts()">扫描冲突</button></div>
    </div>
    <div id="conflictRes" style="margin-top:12px"><div class="empty">点击「扫描冲突」检查记忆是否打架</div></div>
  </div>
</div>

<!-- 详情抽屉 -->
<div class="overlay" id="overlay" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer">
  <div class="drawer-head">
    <span class="tt" id="drawerTitle">详情</span>
    <span id="drawerMeta" class="pill"></span>
    <span class="closex" onclick="closeDrawer()">×</span>
  </div>
  <div class="drawer-body" id="drawerBody"></div>
</div>

<div class="msg" id="toast"></div>
</div>
<script>
const $=id=>document.getElementById(id);
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove('show'),2800);}
function esc(s){return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function trunc(s,n){s=(s||'');return s.length>n?s.slice(0,n)+'…':s;}
function scoreCls(x){return x>=0.5?'hi':x>=0.35?'mid':'lo';}

/* 轻量 Markdown 渲染（离线、先转义防 XSS） */
function md(src){
  src=(src==null?'':String(src));
  const lines=src.replace(/\r\n/g,'\n').split('\n');
  let html='',inCode=false,codeBuf=[],listType=null;
  const flushList=()=>{if(listType){html+=listType==='ol'?'</ol>':'</ul>';listType=null;}};
  const inline=t=>esc(t)
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/[*][*]([^[*]+)[*][*]/g,'<strong>$1</strong>')
    .replace(/[*]([^[*]+)[*]/g,'<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:[/][/][^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  for(let raw of lines){
    if(raw.trim().startsWith('```')){
      if(!inCode){inCode=true;codeBuf=[];}
      else{inCode=false;html+='<pre><code>'+esc(codeBuf.join('\n'))+'</code></pre>';}
      continue;
    }
    if(inCode){codeBuf.push(raw);continue;}
    const line=raw.replace(/\t/g,'  ');
    if(/^###\s+/.test(line)){flushList();html+='<h3>'+inline(line.replace(/^###\s+/,''))+'</h3>';}
    else if(/^##\s+/.test(line)){flushList();html+='<h2>'+inline(line.replace(/^##\s+/,''))+'</h2>';}
    else if(/^#\s+/.test(line)){flushList();html+='<h1>'+inline(line.replace(/^#\s+/,''))+'</h1>';}
    else if(/^\s*[-*]\s+/.test(line)){if(listType!=='ul'){flushList();html+='<ul>';listType='ul';}html+='<li>'+inline(line.replace(/^\s*[-*]\s+/,''))+'</li>';}
    else if(/^\s*\d+\.\s+/.test(line)){if(listType!=='ol'){flushList();html+='<ol>';listType='ol';}html+='<li>'+inline(line.replace(/^\s*\d+\.\s+/,''))+'</li>';}
    else if(line.trim()===''){flushList();}
    else {flushList();html+='<p>'+inline(line)+'</p>';}
  }
  flushList();
  if(inCode)html+='<pre><code>'+esc(codeBuf.join('\n'))+'</code></pre>';
  return html;
}

/* ============ 搜索分组过滤 ============ */
let _lastRes=null;
const ALL_GROUPS=[['semantic','语义相似'],['content','内容'],['entities','实体'],['memory','记忆'],['kb','知识库'],['keyword_packs','关键词组']];
let _activeGroups=new Set(ALL_GROUPS.map(g=>g[0]));

function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.tab===name));
  document.querySelectorAll('.panel').forEach(p=>p.classList.add('hidden'));
  $('panel-'+name).classList.remove('hidden');
  if(name==='browse'){loadStats();loadList('content');}
  if(name==='graph'){loadGraph();}
}
function switchAdd(kind){
  document.querySelectorAll('#addTabs .ltab').forEach(t=>t.classList.toggle('on',t.dataset.kind===kind));
  ['content','entity','fragment','doc','link'].forEach(k=>$('form-'+k).classList.toggle('hidden',k!==kind));
}
function switchList(kind){
  document.querySelectorAll('#listTabs .ltab').forEach(t=>t.classList.toggle('on',t.dataset.kind===kind));
  buildListFilter(kind);
  loadList(kind);
}

function doSearch(){
  const q=$('q').value.trim(); if(!q){toast('请输入关键词');return;}
  const ns=$('ns')?$('ns').value.trim():'';
  fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q,limit:8,namespace:ns||undefined})})
    .then(r=>r.json()).then(render).catch(e=>toast('搜索失败 '+e));
}
function doRecall(){
  const q=$('q').value.trim();
  fetch('/api/recall',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})})
    .then(r=>r.json()).then(lines=>{
      const html='<div class="card recall"><h3>回忆 · 防遗忘上下文</h3>'+(lines.length?lines.map(l=>'<div class="item" onclick="toast(\'已显示\')"><div class="b">'+esc(l)+'</div></div>').join(''):'<div class="empty">暂无记忆</div>')+'</div>';
      $('results').innerHTML=html;
    }).catch(e=>toast('回忆失败 '+e));
}
function doDaily(){
  fetch('/api/daily').then(r=>r.json()).then(lines=>{
    const text=lines.join('\n');
    const html='<div class="card recall"><h3>每日开工上下文 <span class="n">'+lines.length+'</span></h3>'+
      '<div style="margin-bottom:10px"><button class="btn amber" onclick="copyDaily()">一键复制 · 贴回会话开头</button></div>'+
      '<div class="md" style="font-size:12px;color:#374151;white-space:pre-wrap;max-height:360px;overflow:auto">'+esc(text)+'</div></div>';
    window._dailyText=text;
    $('results').innerHTML=html;
  }).catch(e=>toast('加载失败 '+e));
}
function copyDaily(){
  const t=window._dailyText||'';
  (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject())
    .then(()=>toast('已复制，可贴回会话开头'))
    .catch(()=>{const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('已复制（兼容模式）');});
}

/* 结果卡片：可点击打开详情 */
function cardItem(html,kind,id,extra){
  return '<div class="item" data-kind="'+kind+'" data-id="'+id+'"'+(extra||'')+' onclick="openDetail(this)">'+html+'</div>';
}
function render(res){
  if(res.error){toast(res.error);return;}
  _lastRes=res;
  $('results').innerHTML=renderGroups(res,true);
  renderFilterbar();
}
function renderGroups(res,limit){
  let h='';
  for(const [key,title,arr] of ALL_GROUPS.map(g=>[g[0],g[1],res[g[0]]])){
    if(!_activeGroups.has(key))continue;
    if(!arr||!arr.length)continue;
    h+='<div class="card"><h3>'+title+' <span class="n">'+arr.length+'</span>'+
       (limit&&arr.length>6?'<span class="tinybtn" style="margin-left:auto" onclick="expandGroup(\''+key+'\')">展开全部 '+arr.length+' 条</span>':'')+'</h3>';
    const slice=limit?arr.slice(0,6):arr;
    for(const i of slice){
      if(key==='semantic'){
        const k=i.type==='kb_chunk'?'chunk':'content';
        h+=cardItem('<span class="score '+scoreCls(i.score)+'">'+i.score.toFixed(2)+'</span><span class="t">['+i.type+'#'+i.id+']</span> <span class="b">'+esc(trunc(i.text,90))+'</span>',k,i.id);
      }else if(key==='content'){
        h+=cardItem('<span class="t">'+esc(i.title)+'</span><span class="pill type">'+esc(i.content_type)+'</span><span class="pill status">'+esc(i.status)+'</span><div class="s">#'+i.id+' · '+esc(i.category||'')+' · '+esc(i.updated_at||'')+'</div><div class="b">'+esc(trunc(i.body,120))+'</div>','content',i.id);
      }else if(key==='entities'){
        h+=cardItem('<span class="t">'+esc(i.name)+'</span><span class="pill type">'+esc(i.type)+'</span><div class="s">#'+i.id+' · '+esc(i.org||'')+(i.role?' · '+esc(i.role):'')+'</div>','entity',i.id);
      }else if(key==='memory'){
        h+=cardItem('<span class="pill type">'+esc(i.fragment_type)+'</span><span class="b">'+esc(trunc(i.content,120))+'</span><div class="s">#'+i.id+' · '+esc(i.subject||'')+'</div>','memory',i.id);
      }else if(key==='kb'){
        h+=cardItem('<span class="t">'+esc(i.title)+'</span><div class="s">doc#'+i.doc_id+' · chunk#'+i.id+'</div><div class="b">'+esc(trunc(i.content,120))+'</div>','chunk',i.id);
      }else{
        h+=cardItem('<span class="t">'+esc(i.name)+'</span><div class="s">'+esc((i.words||[]).slice(0,8).join(' · '))+'</div>','x','0');
      }
    }
    h+='</div>';
  }
  return h||'<div class="card"><div class="empty">没有命中，换个词试试，或点「回忆」看记忆。</div></div>';
}
function expandGroup(key){ if(_lastRes) $('results').innerHTML=renderGroups(_lastRes,false); }
function renderFilterbar(){
  if(!_lastRes)return;
  const bar='<div class="filterbar">'+ALL_GROUPS.map(([k,t])=>{
    const n=(_lastRes[k]||[]).length; if(!n)return '';
    const on=_activeGroups.has(k)?'on':'';
    return '<span class="fchip '+on+'" data-g="'+k+'" onclick="toggleGroup(this)">'+t+' '+n+'</span>';
  }).join('')+'</div>';
  $('results').insertAdjacentHTML('afterbegin',bar);
}
function toggleGroup(el){const g=el.dataset.g;if(_activeGroups.has(g))_activeGroups.delete(g);else _activeGroups.add(g);render(_lastRes);}

/* ============ 详情抽屉 ============ */
function openDetail(el){
  const kind=el.dataset.kind, id=el.dataset.id;
  if(kind==='x')return;
  fetch('/api/detail?kind='+encodeURIComponent(kind)+'&id='+encodeURIComponent(id))
    .then(r=>r.json()).then(d=>{
      if(d.error){toast(d.error);return;}
      showDrawer(d);
    }).catch(e=>toast('详情加载失败 '+e));
}
function showDrawer(d){
  const k=d.kind, x=d.data;
  let title='',meta='',body='';
  if(k==='content'){
    title=x.title||'(无标题)'; meta='content#'+x.id+' · '+esc(x.content_type)+' · '+esc(x.status);
    body='<div class="md">'+md(x.body)+'</div>'+
      '<div class="hint">分类：'+esc(x.category||'-')+' ｜ 来源：'+esc(x.source_tag||'-')+' ｜ 更新：'+esc(x.updated_at||'-')+'</div>'+
      '<div class="modal-btns"><button class="btn gray" onclick="editContent('+x.id+')">编辑</button><button class="btn" style="background:var(--red);color:#fff" onclick="delContent('+x.id+')">删除</button></div>';
  }else if(k==='entity'){
    const e=x.entity;
    title=e.name; meta='entity#'+e.id+' · '+esc(e.type);
    let rel='';
    (x.links||[]).forEach(l=>{rel+='<div class="rel" data-kind="entity" data-id="'+l.other+'" onclick="openDetail(this)"><span class="badge">'+esc(l.relation||'关联')+'</span><span>'+esc(l.other_name)+'</span><span class="arrow">#'+l.other+' · '+esc(l.other_type)+'</span></div>';});
    (x.docs||[]).forEach(l=>{rel+='<div class="rel" data-kind="doc" data-id="'+l.doc_id+'" onclick="openDetail(this)"><span class="badge doc">文档</span><span>'+esc(l.title)+'</span><span class="arrow">'+(l.relation?esc(l.relation)+' · ':'')+'#'+l.doc_id+'</span></div>';});
    body='<div class="hint">所属组织：'+esc(e.org||'-')+(e.role?' ｜ 角色：'+esc(e.role):'')+'</div>'+
      '<h3 style="color:var(--blue);margin:12px 0 6px">关系网络（实体↔实体 via entity_link）</h3>'+(rel||'<div class="empty">暂无实体关联</div>')+
      '<h3 style="color:var(--blue);margin:14px 0 6px">关联文档（via entity_doc）</h3>'+((x.docs&&x.docs.length)?'':(rel?'<div class="empty">暂无关联文档</div>':''));
  }else if(k==='doc'||k==='chunk'){
    const dd=x.doc; title=dd.title; meta='doc#'+dd.id+' · '+(x.chunks?x.chunks.length:'?')+' chunks';
    let ch='';
    (x.chunks||[]).forEach(c=>{ch+='<div class="chunk'+(x.highlight==c.id?' hl':'')+'"><div class="seq">#'+c.seq+(x.highlight==c.id?' · 命中':(c.id?' · chunk#'+c.id:''))+'</div>'+md(c.content)+'</div>';});
    body='<div class="hint">来源：'+esc(dd.source||'-')+' ｜ 创建：'+esc(dd.created_at||'-')+'</div><h3 style="color:var(--blue);margin:10px 0 6px">文档分块</h3>'+ch;
  }else if(k==='memory'||k==='fragment'){
    title='记忆碎片 #'+x.id; meta=esc(x.fragment_type)+' · '+esc(x.subject||'')+(x.importance==='high'?' · ⭐高价值':'');
    body='<div class="md">'+md(x.content)+'</div><div class="hint">标签：'+esc((x.tags||''))+' ｜ 来源：'+esc(x.source_ref||'-')+' ｜ 创建：'+esc(x.created_at||'-')+'</div>';
  }
  $('drawerTitle').textContent=title;
  $('drawerMeta').textContent=meta;
  $('drawerBody').innerHTML=body;
  $('overlay').classList.add('show');$('drawer').classList.add('show');
}
function closeDrawer(){$('overlay').classList.remove('show');$('drawer').classList.remove('show');}
function editContent(id){
  fetch('/api/detail?kind=content&id='+id).then(r=>r.json()).then(d=>{
    const x=d.data;
    const body='<div class="editgrid">'+
      '<div><label>标题</label><input id="ed_title" value="'+esc(x.title||'')+'"></div>'+
      '<div class="form-row"><div><label>类型</label><input id="ed_type" value="'+esc(x.content_type||'')+'"></div><div><label>状态</label><input id="ed_status" value="'+esc(x.status||'')+'"></div><div><label>类目</label><input id="ed_cat" value="'+esc(x.category||'')+'"></div></div>'+
      '<div><label>正文（支持 Markdown）</label><textarea id="ed_body">'+esc(x.body||'')+'</textarea></div>'+
      '<div><label>标签（逗号分隔）</label><input id="ed_tags" value="'+esc(x.tags_json?JSON.parse(x.tags_json).join(','):'')+'"></div>'+
      '</div><div class="modal-btns"><button class="btn gray" onclick="showContentBack('+id+')">取消</button><button class="btn blue" onclick="saveContent('+id+')">保存</button></div>';
    $('drawerBody').innerHTML=body;
  });
}
function showContentBack(id){
  fetch('/api/detail?kind=content&id='+id).then(r=>r.json()).then(d=>showDrawer(d));
}
function saveContent(id){
  const tags=$('ed_tags').value.trim();
  const body={kind:'content',id:id,title:$('ed_title').value,body:$('ed_body').value,status:$('ed_status').value,category:$('ed_cat').value,content_type:$('ed_type').value,tags:tags?tags.split(','):[]};
  fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(d=>{if(d.error){toast('失败：'+d.error);return;}toast('已保存');showContentBack(id);loadStats();}).catch(e=>toast('保存失败 '+e));
}
function delContent(id){
  if(!confirm('确认删除该内容条目？此操作不可恢复。'))return;
  fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'content',id})})
    .then(r=>r.json()).then(d=>{if(d.error){toast('失败：'+d.error);return;}toast('已删除 #'+id);closeDrawer();loadStats();}).catch(e=>toast('删除失败 '+e));
}

function reindex(){
  toast('正在重建向量索引，稍等...');
  fetch('/api/index',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reset:true})})
    .then(r=>r.json()).then(d=>{toast('向量索引完成：+'+d.added+' 条，共 '+d.total+' 条');loadStats();}).catch(e=>toast('重建失败 '+e));
}

/* ============ 录入 ============ */
function addContent(){
  const body={kind:'content',title:$('c_title').value,body:$('c_body').value,type:$('c_type').value,category:$('c_cat').value,tags:$('c_tags').value?$('c_tags').value.split(','):null,source_tag:$('c_src').value||'manual'};
  postAdd(body,['c_title','c_body','c_cat','c_tags']);
}
function addEntity(){
  const body={kind:'entity',type:$('e_type').value,name:$('e_name').value,org:$('e_org').value,role:$('e_role').value,tags:$('e_tags').value?$('e_tags').value.split(','):null};
  postAdd(body,['e_name','e_org','e_role','e_tags']);
}
function addFragment(){
  const body={kind:'fragment',ftype:$('f_type').value,content:$('f_content').value,subject:$('f_subject').value,tags:$('f_tags').value?$('f_tags').value.split(','):null};
  postAdd(body,['f_content','f_tags']);
}
function addDoc(){
  const body={kind:'doc',title:$('d_title').value,text:$('d_text').value,source:$('d_source').value};
  postAdd(body,['d_title','d_text','d_source']);
}
function addLink(){
  const body={kind:'link',from:$('l_from').value,to:$('l_to').value,relation:$('l_rel').value,
              note:$('l_note').value,valid_from:$('l_valid_from').value,valid_until:$('l_valid_until').value};
  postAdd(body,['l_from','l_to','l_rel','l_note','l_valid_from','l_valid_until']);
}
function postAdd(body,clearIds){
  fetch('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(d=>{
      if(d.error){toast('失败：'+d.error);return;}
      toast('已保存 id='+d.id);
      clearIds.forEach(id=>{const el=$(id);if(el)el.value='';});
      loadStats();
    }).catch(e=>toast('保存失败 '+e));
}

/* ============ 浏览 ============ */
let _listKind='content';
function buildListFilter(kind){
  _listKind=kind;const box=$('listFilter');box.classList.remove('hidden');box.innerHTML='';
  let opts=[];
  if(kind==='content')opts=[['','全部'],['note','笔记'],['task','任务'],['decision','决策'],['article','文章'],['issue','问题']];
  else if(kind==='entity')opts=[['','全部'],['org','组织'],['person','人'],['product','产品'],['platform','平台'],['project','项目']];
  else if(kind==='fragment')opts=[['','全部'],['fact','事实'],['knowledge','知识'],['decision','决策'],['preference','偏好']];
  else if(kind==='doc'){box.innerHTML='';box.classList.add('hidden');return;}
  opts.forEach(([v,t])=>{const s=document.createElement('span');s.className='fchip'+(v===''?' on':'');s.textContent=t;s.dataset.v=v;s.onclick=()=>{document.querySelectorAll('#listFilter .fchip').forEach(c=>c.classList.remove('on'));s.classList.add('on');loadList(kind,v);};box.appendChild(s);});
}
function loadList(kind,typ){
  _listKind=kind;
  fetch('/api/list?kind='+kind+(typ?'&type='+encodeURIComponent(typ):'')).then(r=>r.json()).then(rows=>{
    if(!Array.isArray(rows)){toast('加载失败');return;}
    if(!rows.length){$('listBody').innerHTML='<div class="empty">暂无数据</div>';return;}
    let h='';
    for(const i of rows){
      if(kind==='content')h+=cardItem('<span class="t">'+esc(i.title)+'</span><span class="pill type">'+esc(i.content_type)+'</span><span class="pill status">'+esc(i.status)+'</span><div class="s">#'+i.id+' · '+esc(i.category||'')+' · '+esc(i.updated_at||'')+'</div><div class="b">'+esc(trunc(i.body,140))+'</div>','content',i.id);
      else if(kind==='entity')h+=cardItem('<span class="t">'+esc(i.name)+'</span><span class="pill type">'+esc(i.type)+'</span><div class="s">#'+i.id+' · '+esc(i.org||'')+(i.role?' · '+esc(i.role):'')+'</div>','entity',i.id);
      else if(kind==='fragment')h+=cardItem('<span class="pill type">'+esc(i.fragment_type)+'</span><span class="b">'+esc(i.content)+'</span><div class="s">#'+i.id+' · '+esc(i.subject||'')+' · '+esc(i.created_at||'')+'</div>','memory',i.id);
      else h+=cardItem('<span class="t">'+esc(i.title)+'</span><div class="s">#'+i.id+' · '+i.chunks+' chunks · '+esc(i.created_at||'')+'</div>','doc',i.id);
    }
    $('listBody').innerHTML=h;
  }).catch(e=>toast('列表加载失败 '+e));
}

/* ============ 实体关系 ============ */
function searchEntity(){
  const q=$('relQ').value.trim();if(!q){toast('请输入实体名');return;}
  fetch('/api/entity_search?q='+encodeURIComponent(q)).then(r=>r.json()).then(rows=>{
    if(!rows.length){$('relMatches').innerHTML='<div class="empty">未找到匹配实体</div>';return;}
    $('relMatches').innerHTML=rows.map(r=>'<div class="rel" data-kind="entity" data-id="'+r.id+'" onclick="openDetail(this)"><span class="badge">'+esc(r.type)+'</span><span>'+esc(r.name)+'</span><span class="arrow">#'+r.id+(r.org?' · '+esc(r.org):'')+'</span></div>').join('');
  }).catch(e=>toast('搜索失败 '+e));
}

/* ============ 关系图谱（力导向可视化） ============ */
let G=null, Gnodes=[], Gedges=[], Gidmap={}, Grun=false, Galpha=0;
let Gcam={x:0,y:0,scale:1}, Gdrag=null, Ghover=null, Gmoved=false, Gdpr=1;
let gcanvas=null, gctx=null;

const GCOLORS={org:'#185FA5',person:'#6d28d9',product:'#0f6e56',platform:'#b45309',project:'#a32d2d',account:'#2563eb',tool:'#0891b2',other:'#64748b'};
function Gcolor(t){return GCOLORS[t]||GCOLORS.other;}
function Gradius(n){return 7 + Math.min(n.degree,12)*1.4;}

function loadGraph(){
  const sel=$('gCenterSel');
  const center=sel?sel.value:'';
  const url='/api/graph'+(center?('?center='+encodeURIComponent(center)):'');
  fetch(url).then(r=>r.json()).then(d=>{
    if(d.error){toast(d.error);return;}
    G=d;
    if(!center && sel){
      const cur=sel.value;
      sel.innerHTML='<option value="">全量图谱（'+(G.nodes||[]).length+' 实体 / '+(G.edges||[]).length+' 关系）</option>'+
        (G.nodes||[]).map(n=>'<option value="'+n.id+'">'+esc(n.name)+' 的子图</option>').join('');
      sel.value=cur;
    }
    $('gInfo').textContent='节点 '+(G.nodes||[]).length+' · 边 '+(G.edges||[]).length;
    initGraph();
  }).catch(e=>toast('图谱加载失败 '+e));
}
function initGraph(){
  gcanvas=$('gcanvas'); gctx=gcanvas.getContext('2d');
  const W=gcanvas.clientWidth||960, H=gcanvas.clientHeight||580;
  Gdpr=window.devicePixelRatio||1;
  gcanvas.width=W*Gdpr; gcanvas.height=H*Gdpr;
  Gnodes=(G.nodes||[]).map(n=>({...n, x:W/2+(Math.random()-0.5)*W*0.6, y:H/2+(Math.random()-0.5)*H*0.6, vx:0, vy:0}));
  Gidmap={}; Gnodes.forEach(n=>Gidmap[n.id]=n);
  Gedges=(G.edges||[]).map(e=>({a:Gidmap[e.from], b:Gidmap[e.to], rel:e.relation})).filter(e=>e.a&&e.b);
  Gcam={x:0,y:0,scale:1};
  Gfit(false); Gbind(); Grestart();
}
function Grestart(){ Galpha=1; if(!Grun){Grun=true; requestAnimationFrame(Gtick);} }
function Gtick(){
  stepForce();
  if(Galpha>0.02){ requestAnimationFrame(Gtick); } else { Grun=false; drawGraph(); }
}
function stepForce(){
  const W=gcanvas.clientWidth||960, H=gcanvas.clientHeight||580;
  const k=70;
  for(let i=0;i<Gnodes.length;i++){
    const a=Gnodes[i];
    for(let j=i+1;j<Gnodes.length;j++){
      const b=Gnodes[j];
      let dx=a.x-b.x, dy=a.y-b.y;
      let d2=dx*dx+dy*dy; if(d2<0.01){d2=0.01; dx=Math.random()-0.5; dy=Math.random()-0.5;}
      const d=Math.sqrt(d2);
      const f=(k*k)/d2;
      const fx=dx/d*f, fy=dy/d*f;
      a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy;
    }
  }
  const L=90;
  for(const e of Gedges){
    const a=e.a, b=e.b;
    let dx=b.x-a.x, dy=b.y-a.y; let d=Math.sqrt(dx*dx+dy*dy)||0.01;
    const f=(d-L)*0.02;
    const fx=dx/d*f, fy=dy/d*f;
    a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy;
  }
  for(const n of Gnodes){ n.vx+=(W/2-n.x)*0.002; n.vy+=(H/2-n.y)*0.002; }
  for(const n of Gnodes){
    if(Gdrag&&Gdrag.n===n){ n.vx=0; n.vy=0; continue; }
    n.x+=n.vx*Galpha; n.y+=n.vy*Galpha;
    n.vx*=0.85; n.vy*=0.85;
  }
  Galpha*=0.98;
}
function Gfit(animate){
  if(!Gnodes.length||!gcanvas)return;
  let minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;
  for(const n of Gnodes){minx=Math.min(minx,n.x);miny=Math.min(miny,n.y);maxx=Math.max(maxx,n.x);maxy=Math.max(maxy,n.y);}
  const W=gcanvas.clientWidth||960, H=gcanvas.clientHeight||580;
  const pad=60;
  const bw=Math.max(maxx-minx,1), bh=Math.max(maxy-miny,1);
  const s=Math.min((W-pad*2)/bw,(H-pad*2)/bh,2);
  Gcam.scale=s;
  Gcam.x=W/2-(minx+maxx)/2*s;
  Gcam.y=H/2-(miny+maxy)/2*s;
  if(animate!==false)drawGraph();
}
function g2s(x,y){ return [x*Gcam.scale+Gcam.x, y*Gcam.scale+Gcam.y]; }
function s2g(x,y){ return [(x-Gcam.x)/Gcam.scale, (y-Gcam.y)/Gcam.scale]; }
function drawGraph(){
  if(!gctx||!gcanvas)return;
  const W=gcanvas.clientWidth||960, H=gcanvas.clientHeight||580;
  gctx.setTransform(Gdpr,0,0,Gdpr,0,0);
  gctx.clearRect(0,0,W,H);
  gctx.lineWidth=1;
  for(const e of Gedges){
    const a=e.a, b=e.b; if(!a||!b)continue;
    const [ax,ay]=g2s(a.x,a.y), [bx,by]=g2s(b.x,b.y);
    const hot=(Ghover&&(Ghover.n===a||Ghover.n===b));
    gctx.strokeStyle=hot?'#185FA5':'#cbd5e1';
    gctx.globalAlpha=hot?0.9:0.5;
    gctx.beginPath(); gctx.moveTo(ax,ay); gctx.lineTo(bx,by); gctx.stroke();
    gctx.globalAlpha=1;
  }
  for(const n of Gnodes){
    const [x,y]=g2s(n.x,n.y);
    const r=Gradius(n)*Math.max(Gcam.scale,0.6);
    const hot=(Ghover&&Ghover.n===n);
    gctx.beginPath(); gctx.arc(x,y,r,0,Math.PI*2);
    gctx.fillStyle=Gcolor(n.type);
    gctx.globalAlpha=hot?1:0.9;
    gctx.fill();
    gctx.globalAlpha=1;
    gctx.lineWidth=hot?3:1.5; gctx.strokeStyle=hot?'#111827':'#ffffff'; gctx.stroke();
    gctx.fillStyle='#1f2937'; gctx.font=(hot?'bold ':'')+'12px "Microsoft YaHei",sans-serif';
    gctx.textAlign='center'; gctx.textBaseline='top';
    gctx.fillText(n.name, x, y+r+2);
  }
}
function Gpick(mx,my){
  for(let i=Gnodes.length-1;i>=0;i--){
    const n=Gnodes[i]; const [x,y]=g2s(n.x,n.y); const r=Gradius(n)*Math.max(Gcam.scale,0.6);
    if((mx-x)*(mx-x)+(my-y)*(my-y)<=r*r)return n;
  }
  return null;
}
function Gbind(){
  gcanvas=$('gcanvas'); if(gcanvas._bound)return; gcanvas._bound=true;
  gcanvas.addEventListener('mousedown',e=>{
    const rect=gcanvas.getBoundingClientRect(); const mx=e.clientX-rect.left, my=e.clientY-rect.top;
    const n=Gpick(mx,my); Gmoved=false;
    if(n){ Gdrag={n:n,ox:mx,oy:my}; gcanvas.style.cursor='grabbing'; }
  });
  window.addEventListener('mousemove',e=>{
    if(Gdrag===null)return;
    const rect=gcanvas.getBoundingClientRect(); const mx=e.clientX-rect.left, my=e.clientY-rect.top;
    if(Math.abs(mx-Gdrag.ox)>3||Math.abs(my-Gdrag.oy)>3)Gmoved=true;
    const [gx,gy]=s2g(mx,my); Gdrag.n.x=gx; Gdrag.n.y=gy; Gdrag.n.vx=0; Gdrag.n.vy=0;
    Galpha=Math.max(Galpha,0.3); if(!Grun){Grun=true;requestAnimationFrame(Gtick);}
  });
  window.addEventListener('mouseup',()=>{
    if(Gdrag){
      if(!Gmoved){ const el={dataset:{kind:'entity',id:Gdrag.n.id}}; openDetail(el); }
      Gdrag=null; if(gcanvas)gcanvas.style.cursor='grab';
    }
  });
  gcanvas.addEventListener('mousemove',e=>{
    if(Gdrag)return;
    const rect=gcanvas.getBoundingClientRect(); const mx=e.clientX-rect.left, my=e.clientY-rect.top;
    const n=Gpick(mx,my);
    const nh=n?{n:n}:null;
    if((Ghover&&Ghover.n)!==(nh&&nh.n)){ Ghover=nh; drawGraph(); gcanvas.style.cursor=n?'pointer':'grab'; }
  });
  gcanvas.addEventListener('mouseleave',()=>{ if(!Gdrag){Ghover=null;drawGraph();} });
  gcanvas.addEventListener('wheel',e=>{
    e.preventDefault();
    const rect=gcanvas.getBoundingClientRect(); const mx=e.clientX-rect.left, my=e.clientY-rect.top;
    const factor=e.deltaY<0?1.12:0.89;
    const [gx,gy]=s2g(mx,my);
    Gcam.scale*=factor;
    Gcam.x=mx-gx*Gcam.scale; Gcam.y=my-gy*Gcam.scale;
    drawGraph();
  },{passive:false});
  gcanvas.addEventListener('dblclick',()=>{ Gcam={x:0,y:0,scale:1}; Gfit(); });
}
function GcenterChange(){ loadGraph(); }

/* ============ AI 问答（RAG） ============ */
function askBrain(){
  const q=$('askQ').value.trim(); if(!q){toast('请输入问题');return;}
  const res=$('askRes');
  res.innerHTML='<div class="empty">检索库中…（最多 60 秒）</div>';
  fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q})})
    .then(r=>r.json()).then(d=>{
      if(d.error){res.innerHTML='<div class="card" style="border-color:var(--red)"><b>出错了：</b>'+esc(d.error)+'</div>';return;}
      let refs='';
      if(d.refs&&d.refs.length){
        refs='<div class="hint" style="margin-top:10px">引用来源（'+d.ctx_n+' 条上下文）：</div>'+
          d.refs.map(r=>'<div class="rel" style="cursor:default"><span class="badge">'+esc(r.kind)+'</span><span>'+esc(r.src)+'</span></div>').join('');
      }
      res.innerHTML='<div class="card" style="border-left:4px solid var(--violet)"><div class="md">'+md(d.answer||'')+'</div>'+refs+'</div>';
    }).catch(e=>{res.innerHTML='<div class="empty">问答失败：'+esc(e)+'</div>';});
}

/* ============ P0 冲突检测 ============ */
function scanConflicts(){
  const res=$('conflictRes');
  res.innerHTML='<div class="empty">扫描记忆中…</div>';
  fetch('/api/conflicts').then(r=>r.json()).then(d=>{
    const cs=d.conflicts||[];
    if(!cs.length){res.innerHTML='<div class="card"><b>没有发现冲突。</b>记忆是干净的。</div>';return;}
    res.innerHTML='<div class="hint">发现 <b>'+cs.length+'</b> 组潜在冲突（强冲突=同一属性不同值，优先处理）：</div>'+
      cs.map(c=>'<div class="card" style="border-color:'+(c.strong?'var(--red)':'var(--amber)')+';margin-top:8px">'+
        '<div class="hint">#'+c.a_id+' ↔ #'+c.b_id+' · 重叠度 '+c.sim+' · 命中 ['+(c.shared_hits||[]).join('、')+']'+
        (c.strong?' · <b style="color:var(--red)">冲突属性：'+(c.conflict_attrs||[]).join('、')+'</b>':'')+'</div>'+
        '<div class="md" style="font-size:12px;opacity:.9">['+esc(c.a.slice(0,90))+']</div>'+
        '<div class="md" style="font-size:12px;opacity:.9">['+esc(c.b.slice(0,90))+']</div></div>').join('');
  }).catch(e=>{res.innerHTML='<div class="empty">扫描失败：'+esc(e)+'</div>';});
}

/* ============ 统计 ============ */
function loadStats(){
  fetch('/api/stats').then(r=>r.json()).then(s=>{
    if(!s)return;
    $('embInfo').textContent='向量索引 '+s.embeddings+' 条';
    const items=[['entity','实体'],['content_item','内容'],['memory_fragments','记忆'],['kb_chunk','知识库块'],['rolling_summaries','滚动摘要'],['retrieval_audits','检索审计'],['ai_conversation','会话'],['master_data','字典']];
    $('statGrid').innerHTML=items.map(([k,l])=>'<div class="stat"><div class="v">'+(s[k]??0)+'</div><div class="k">'+l+'</div></div>').join('');
  }).catch(()=>{});
}

/* 快捷键 */
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('q').focus();$('q').select();}});

loadStats();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print("塞博大脑 Web 界面 → http://127.0.0.1:8899")
    app.run(host="127.0.0.1", port=8899, debug=False, threaded=True)
