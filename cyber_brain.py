#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
塞博大脑 Cyber Brain —— 个人工作知识库
三源融合：
  公司库 aiyingxiao   -> 数据骨架（content_item / kb 三件套 / ai_conversation / master_data / 合规标记）
  邻舍.EXE           -> 记忆层（memory_fragments / rolling_summaries / retrieval_audits / memory_relations）
  content_brain      -> 工作域（entity / entity_link：项目·客户·账号·平台·产品）
引擎：SQLite 单文件 + FTS5(trigram) 中文分词；向量列预留（未来 sqlite-vss / pgvector）

用法：
  python cyber_brain.py --db cyber_brain.db <子命令> ...
  python cyber_brain.py --db cyber_brain.db search "关键词"
  python cyber_brain.py --db cyber_brain.db recall "发布"      # 防遗忘：命中记忆碎片+滚动摘要
"""
import sqlite3
import json
import sys
import os
import datetime

__all__ = ["CyberBrain", "ENTITY_TYPES", "CONTENT_TYPES", "FRAGMENT_TYPES"]

ENTITY_TYPES = ["person", "org", "project", "account", "platform", "product", "tool", "other"]
CONTENT_TYPES = ["note", "article", "task", "decision", "meeting", "idea", "issue", "report"]
FRAGMENT_TYPES = ["fact", "preference", "emotion", "knowledge", "decision",
                  "iron_rule", "event", "pitfall"]

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS entity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  org TEXT,
  role TEXT,
  contact_json TEXT DEFAULT '{}',
  tags_json TEXT DEFAULT '[]',
  meta_json TEXT DEFAULT '{}',
  source_tag TEXT NOT NULL DEFAULT 'manual',
  authorization_ref TEXT DEFAULT 'manual',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_entity_type ON entity(type);
CREATE INDEX IF NOT EXISTS idx_entity_name ON entity(name);

CREATE TABLE IF NOT EXISTS entity_link (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_id INTEGER NOT NULL REFERENCES entity(id),
  to_id INTEGER NOT NULL REFERENCES entity(id),
  relation TEXT NOT NULL,
  note TEXT,
  valid_from TEXT,     -- 关系生效时间（ISO 日期），可空=一直生效
  valid_until TEXT,    -- 关系失效时间（ISO 日期），可空=永不过期；查询/图谱过滤已过期边
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(from_id, to_id, relation)
);

-- 实体 ↔ 知识库文档 关联（2026-09-04：客户/项目实体挂到具体文档，如采集脚本/报告/知识库包）
CREATE TABLE IF NOT EXISTS entity_doc (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL REFERENCES entity(id),
  doc_id INTEGER NOT NULL REFERENCES kb_document(id),
  relation TEXT NOT NULL DEFAULT 'has_doc',
  note TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(entity_id, doc_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_entity_doc_entity ON entity_doc(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_doc_doc ON entity_doc(doc_id);

CREATE TABLE IF NOT EXISTS content_item (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content_type TEXT NOT NULL DEFAULT 'note',
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  body_json TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  parent_id INTEGER REFERENCES content_item(id),
  category TEXT,
  platform TEXT,
  tags_json TEXT DEFAULT '[]',
  kb_ids TEXT DEFAULT '[]',
  keyword_refs_json TEXT DEFAULT '{}',
  entity_ids TEXT DEFAULT '[]',
  source_type TEXT NOT NULL DEFAULT 'manual',
  source_tag TEXT NOT NULL DEFAULT 'manual',
  authorization_ref TEXT DEFAULT 'manual',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_content_type ON content_item(content_type);
CREATE INDEX IF NOT EXISTS idx_content_status ON content_item(status);
CREATE INDEX IF NOT EXISTS idx_content_updated ON content_item(updated_at);

CREATE TABLE IF NOT EXISTS kb_document (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  file_name TEXT,
  mime TEXT,
  source TEXT,
  parse_status TEXT DEFAULT 'uploaded',
  source_tag TEXT DEFAULT 'manual',
  authorization_ref TEXT DEFAULT 'manual',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS kb_chunk (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES kb_document(id),
  seq INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  dimension_tags_json TEXT DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS kb_embedding (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chunk_id INTEGER NOT NULL REFERENCES kb_chunk(id),
  model TEXT DEFAULT 'pending',
  vector BLOB,
  status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS ai_conversation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  session_key TEXT UNIQUE,
  messages_json TEXT DEFAULT '[]',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS master_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  sort INTEGER DEFAULT 0,
  UNIQUE(category, code)
);

CREATE TABLE IF NOT EXISTS keyword_pack (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  grp TEXT,
  words_json TEXT DEFAULT '[]',
  enabled INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS ingest_source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,
  name TEXT,
  authorization_ref TEXT NOT NULL,
  auth_scope TEXT,
  retention_days INTEGER DEFAULT 90,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS ingest_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES ingest_source(id),
  target_type TEXT NOT NULL,
  target_id INTEGER NOT NULL,
  source_tag TEXT NOT NULL,
  collected_at TEXT DEFAULT (datetime('now','localtime')),
  raw_meta_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS embeddings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT NOT NULL,
  target_id INTEGER NOT NULL,
  vector BLOB NOT NULL,
  model TEXT DEFAULT 'bge-small-zh-v1.5',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_emb_target ON embeddings(target_type, target_id);

CREATE TABLE IF NOT EXISTS memory_fragments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fragment_type TEXT NOT NULL DEFAULT 'fact',
  subject TEXT DEFAULT 'work',
  content TEXT NOT NULL,
  entities TEXT DEFAULT '[]',
  tags TEXT DEFAULT '[]',
  status TEXT DEFAULT 'active',
  source_ref TEXT,
  embedding_state TEXT DEFAULT 'disabled',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_frag_type ON memory_fragments(fragment_type);
CREATE INDEX IF NOT EXISTS idx_frag_status ON memory_fragments(status);

CREATE TABLE IF NOT EXISTS rolling_summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_key TEXT NOT NULL,
  start_ref TEXT,
  end_ref TEXT,
  summary TEXT NOT NULL,
  checkpoint_version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_roll_scope ON rolling_summaries(scope_key);

CREATE TABLE IF NOT EXISTS memory_retrieval_audits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  mode TEXT NOT NULL,
  candidate_sources TEXT DEFAULT '{}',
  hits_ids TEXT DEFAULT '[]',
  fallback_reason TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS memory_relations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_frag_id INTEGER NOT NULL,
  to_frag_id INTEGER NOT NULL,
  action TEXT DEFAULT 'link',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sys_profile (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL UNIQUE,
  value TEXT,
  kind TEXT DEFAULT 'model',      -- model | hardware | setting
  note TEXT,
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(title, body, tokenize='trigram');
CREATE VIRTUAL TABLE IF NOT EXISTS fragment_fts USING fts5(content, tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS content_ai AFTER INSERT ON content_item BEGIN
  INSERT INTO content_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS content_ad AFTER DELETE ON content_item BEGIN
  DELETE FROM content_fts WHERE rowid=old.id;
END;
CREATE TRIGGER IF NOT EXISTS content_au AFTER UPDATE ON content_item BEGIN
  DELETE FROM content_fts WHERE rowid=old.id;
  INSERT INTO content_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS frag_ai AFTER INSERT ON memory_fragments BEGIN
  INSERT INTO fragment_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS frag_ad AFTER DELETE ON memory_fragments BEGIN
  DELETE FROM fragment_fts WHERE rowid=old.id;
END;
CREATE TRIGGER IF NOT EXISTS frag_au AFTER UPDATE ON memory_fragments BEGIN
  DELETE FROM fragment_fts WHERE rowid=old.id;
  INSERT INTO fragment_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


def _jl(v):
    """list/dict -> JSON 字符串；None -> '[]'"""
    if v is None:
        return "[]"
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _parse(s, default):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default


class CyberBrain:
    def __init__(self, db_path):
        self.db_path = db_path
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMA)
        # 迁移：老库 entity_link 补 valid_from / valid_until 列 + 索引（幂等）
        try:
            cols = [r[1] for r in self.con.execute("PRAGMA table_info(entity_link)")]
            if "valid_from" not in cols:
                self.con.execute("ALTER TABLE entity_link ADD COLUMN valid_from TEXT")
            if "valid_until" not in cols:
                self.con.execute("ALTER TABLE entity_link ADD COLUMN valid_until TEXT")
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_entity_link_valid ON entity_link(valid_until)")
            self.con.commit()
        except Exception:
            pass
        self.con.commit()
        self._vec_engine = None
        # AI 电脑中枢：初始化默认系统台账（幂等）
        try:
            if not self.con.execute("SELECT 1 FROM sys_profile WHERE key='role'").fetchone():
                self.con.execute(
                    "INSERT INTO sys_profile(key,value,kind,note) VALUES('role','电脑中枢','setting',"
                    "'定位：AI 电脑的大脑（记忆+模型路由+硬件探针）')")
                self.con.commit()
        except Exception:
            pass

    # ------------------------------------------------- 实体
    def add_entity(self, etype, name, org=None, role=None, contact=None, tags=None,
                   meta=None, source_tag="manual", authorization_ref="manual", if_exists="skip"):
        name = (name or "").strip()
        if not name:
            raise ValueError("name 必填")
        if etype not in ENTITY_TYPES:
            raise ValueError(f"type 必须是 {ENTITY_TYPES}")
        if if_exists == "skip":
            r = self.con.execute("SELECT id FROM entity WHERE name=? AND type=?", (name, etype)).fetchone()
            if r:
                return r["id"]
        cur = self.con.execute(
            "INSERT INTO entity(type,name,org,role,contact_json,tags_json,meta_json,source_tag,authorization_ref)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (etype, name, org, role, _jl(contact), _jl(tags), _jl(meta), source_tag, authorization_ref))
        self.con.commit()
        return cur.lastrowid

    def link(self, a, b, relation, note=None, valid_from=None, valid_until=None):
        """建立实体关系。支持时间有效性：valid_until 过期后该关系不再出现在图谱/邻居。

        若已存在同 (from,to,relation) 关系，则更新其时间窗口与备注（而非忽略）。
        """
        if valid_until:
            # 已过期的时间窗口：直接删除旧关系（避免残留死边）
            if valid_until < __import__("datetime").date.today().isoformat():
                self.con.execute("DELETE FROM entity_link WHERE from_id=? AND to_id=? AND relation=?",
                                 (a, b, relation))
                self.con.commit()
                return
        self.con.execute(
            "INSERT INTO entity_link(from_id,to_id,relation,note,valid_from,valid_until) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(from_id,to_id,relation) DO UPDATE SET "
            "note=excluded.note, valid_from=excluded.valid_from, valid_until=excluded.valid_until",
            (a, b, relation, note, valid_from, valid_until))
        self.con.commit()

    def get_entity(self, eid):
        return self.con.execute("SELECT * FROM entity WHERE id=?", (eid,)).fetchone()

    def find_entity(self, name, etype=None):
        if etype:
            return self.con.execute("SELECT * FROM entity WHERE name=? AND type=?", (name, etype)).fetchone()
        return self.con.execute("SELECT * FROM entity WHERE name=? ORDER BY id LIMIT 1", (name,)).fetchone()

    def list_entities(self, etype=None, limit=50):
        if etype:
            return self.con.execute("SELECT * FROM entity WHERE type=? ORDER BY updated_at DESC LIMIT ?",
                                    (etype, limit)).fetchall()
        return self.con.execute("SELECT * FROM entity ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()

    def search_entities(self, q, limit=30, namespace=None):
        like = f"%{q}%"
        if namespace:
            return self.con.execute(
                "SELECT * FROM entity WHERE (name LIKE ? OR org LIKE ?) AND namespace=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (like, like, namespace, limit)).fetchall()
        return self.con.execute(
            "SELECT * FROM entity WHERE name LIKE ? OR org LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (like, like, limit)).fetchall()

    def neighbors(self, eid):
        """返回实体的邻居（仅未过期的关系）。"""
        out = []
        today = __import__("datetime").date.today().isoformat()
        for r in self.con.execute(
                "SELECT l.to_id AS other, l.relation, e.name AS other_name, e.type AS other_type, "
                "l.valid_from, l.valid_until "
                "FROM entity_link l JOIN entity e ON e.id=l.to_id "
                "WHERE l.from_id=? AND (l.valid_until IS NULL OR l.valid_until>=?)", (eid, today)):
            out.append(dict(r))
        for r in self.con.execute(
                "SELECT l.from_id AS other, l.relation, e.name AS other_name, e.type AS other_type, "
                "l.valid_from, l.valid_until "
                "FROM entity_link l JOIN entity e ON e.id=l.from_id "
                "WHERE l.to_id=? AND (l.valid_until IS NULL OR l.valid_until>=?)", (eid, today)):
            out.append(dict(r))
        return out

    # ------------------------------------------------- 内容
    def add_content(self, title, body="", ctype="note", status="draft", category=None, platform=None,
                    tags=None, entity_ids=None, body_json=None, source_type="manual",
                    source_tag="manual", authorization_ref="manual", parent_id=None, keyword_refs=None):
        if ctype not in CONTENT_TYPES:
            raise ValueError(f"content_type 必须是 {CONTENT_TYPES}")
        cur = self.con.execute(
            "INSERT INTO content_item(content_type,title,body,body_json,status,category,platform,"
            "tags_json,entity_ids,source_type,source_tag,authorization_ref,parent_id,keyword_refs_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ctype, title, body, body_json, status, category, platform,
             _jl(tags), _jl(entity_ids), source_type, source_tag, authorization_ref,
             parent_id, _jl(keyword_refs)))
        self.con.commit()
        return cur.lastrowid

    def get_content(self, cid):
        return self.con.execute("SELECT * FROM content_item WHERE id=?", (cid,)).fetchone()

    def update_content(self, cid, **kw):
        if not kw:
            return
        sets = []
        params = []
        for k, v in kw.items():
            if k in ("tags", "entity_ids", "keyword_refs"):
                sets.append(f"{k}_json=?")
                params.append(_jl(v))
            elif k in ("title", "body", "status", "category", "platform", "content_type",
                       "source_type", "source_tag", "authorization_ref"):
                sets.append(f"{k}=?")
                params.append(v)
            else:
                raise ValueError(f"不支持的字段: {k}")
        sets.append("updated_at=datetime('now','localtime')")
        params.append(cid)
        self.con.execute(f"UPDATE content_item SET {', '.join(sets)} WHERE id=?", params)
        self.con.commit()

    def list_content(self, ctype=None, status=None, limit=50):
        sql = "SELECT * FROM content_item WHERE 1=1"
        p = []
        if ctype:
            sql += " AND content_type=?"
            p.append(ctype)
        if status:
            sql += " AND status=?"
            p.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        p.append(limit)
        return self.con.execute(sql, p).fetchall()

    def delete_content(self, cid):
        self.con.execute("DELETE FROM content_item WHERE id=?", (cid,))
        self.con.commit()

    # ------------------------------------------------- 检索（混合策略）
    def _fts_ids(self, fts_table, cols, q, limit):
        q = (q or "").strip()
        if len(q) < 3:
            return None
        try:
            cur = self.con.execute(
                f"SELECT rowid AS id FROM {fts_table} WHERE {fts_table} MATCH ? "
                f"ORDER BY bm25({fts_table}) LIMIT ?", (q, limit))
            return [r["id"] for r in cur.fetchall()]
        except sqlite3.Error:
            return None

    def _like_ids(self, table, cols, q, limit, namespace=None):
        like = f"%{q}%"
        cond = " OR ".join(f"{c} LIKE ?" for c in cols)
        if namespace:
            cur = self.con.execute(
                f"SELECT id FROM {table} WHERE ({cond}) AND namespace=? ORDER BY id DESC LIMIT ?",
                tuple([like] * len(cols)) + (namespace, limit))
        else:
            cur = self.con.execute(
                f"SELECT id FROM {table} WHERE {cond} ORDER BY id DESC LIMIT ?",
                tuple([like] * len(cols)) + (limit,))
        return [r["id"] for r in cur.fetchall()]

    def search_content(self, q, ctype=None, limit=30, namespace=None):
        q = (q or "").strip()
        ids = set(self._fts_ids("content_fts", ["title", "body"], q, limit * 3) or [])
        ids |= set(self._like_ids("content_item", ["title", "body"], q, limit * 3, namespace=namespace))
        rows = []
        for i in list(ids)[:limit * 4]:
            r = self.get_content(i)
            if r and (not namespace or r["namespace"] == namespace):
                rows.append(r)
        if ctype:
            rows = [r for r in rows if r["content_type"] == ctype]
        rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
        return rows[:limit]

    # ------------------------------------------------- 知识库（RAG 底座）
    def add_document(self, title, text, source=None, source_tag="manual",
                     authorization_ref="manual", chunk_size=500, overlap=50):
        cur = self.con.execute(
            "INSERT INTO kb_document(title,source,source_tag,authorization_ref) VALUES(?,?,?,?)",
            (title, source, source_tag, authorization_ref))
        doc_id = cur.lastrowid
        text = text or ""
        step = max(chunk_size - overlap, 50)
        start = 0
        seq = 0
        while start < len(text):
            chunk = text[start:start + chunk_size]
            self.con.execute(
                "INSERT INTO kb_chunk(doc_id,seq,content) VALUES(?,?,?)", (doc_id, seq, chunk))
            start += step
            seq += 1
        self.con.commit()
        return doc_id

    def list_documents(self, limit=50):
        return self.con.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM kb_chunk c WHERE c.doc_id=d.id) AS chunks "
            "FROM kb_document d ORDER BY d.created_at DESC LIMIT ?", (limit,)).fetchall()

    def get_document_chunks(self, doc_id):
        return self.con.execute("SELECT * FROM kb_chunk WHERE doc_id=? ORDER BY seq", (doc_id,)).fetchall()

    def search_kb(self, q, limit=20):
        like = f"%{q}%"
        return self.con.execute(
            "SELECT c.id, c.doc_id, d.title, c.content, c.seq FROM kb_chunk c "
            "JOIN kb_document d ON d.id=c.doc_id WHERE c.content LIKE ? ORDER BY c.id DESC LIMIT ?",
            (like, limit)).fetchall()

    # ------------------------------------------------- 会话
    def add_conversation(self, title, session_key=None, messages=None):
        cur = self.con.execute(
            "INSERT INTO ai_conversation(title,session_key,messages_json) VALUES(?,?,?)",
            (title, session_key, _jl(messages or [])))
        self.con.commit()
        return cur.lastrowid

    def get_conversation(self, cid=None, session_key=None):
        if cid:
            return self.con.execute("SELECT * FROM ai_conversation WHERE id=?", (cid,)).fetchone()
        if session_key:
            return self.con.execute("SELECT * FROM ai_conversation WHERE session_key=?",
                                    (session_key,)).fetchone()
        return None

    def append_message(self, cid, role, content):
        row = self.con.execute("SELECT messages_json FROM ai_conversation WHERE id=?", (cid,)).fetchone()
        msgs = _parse(row["messages_json"], []) if row else []
        msgs.append({"role": role, "content": content, "at": _now()})
        self.con.execute(
            "UPDATE ai_conversation SET messages_json=?, updated_at=datetime('now','localtime') WHERE id=?",
            (_jl(msgs), cid))
        self.con.commit()

    # ------------------------------------------------- 字典 / 关键词
    def add_master(self, category, code, label, sort=0):
        self.con.execute("INSERT OR IGNORE INTO master_data(category,code,label,sort) VALUES(?,?,?,?)",
                         (category, code, label, sort))
        self.con.commit()

    def list_master(self, category=None):
        if category:
            return self.con.execute(
                "SELECT * FROM master_data WHERE category=? ORDER BY sort,id", (category,)).fetchall()
        return self.con.execute("SELECT * FROM master_data ORDER BY category,sort,id").fetchall()

    def add_keyword_pack(self, name, words, grp=None):
        cur = self.con.execute("INSERT INTO keyword_pack(name,grp,words_json) VALUES(?,?,?)",
                               (name, grp, _jl(words or [])))
        self.con.commit()
        return cur.lastrowid

    def list_keyword_packs(self, enabled_only=True):
        sql = "SELECT * FROM keyword_pack"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id DESC"
        return self.con.execute(sql).fetchall()

    # ------------------------------------------------- 数据接入（合规）
    def add_ingest_source(self, source_type, name, authorization_ref, auth_scope=None):
        cur = self.con.execute(
            "INSERT INTO ingest_source(source_type,name,authorization_ref,auth_scope) VALUES(?,?,?,?)",
            (source_type, name, authorization_ref, auth_scope))
        self.con.commit()
        return cur.lastrowid

    def add_ingest_record(self, source_id, target_type, target_id, source_tag, meta=None):
        cur = self.con.execute(
            "INSERT INTO ingest_record(source_id,target_type,target_id,source_tag,raw_meta_json) "
            "VALUES(?,?,?,?,?)",
            (source_id, target_type, target_id, source_tag, _jl(meta)))
        self.con.commit()
        return cur.lastrowid

    # ------------------------------------------------- 记忆层（邻舍）
    def add_fragment(self, ftype, content, subject="work", tags=None, entities=None, source_ref=None):
        if ftype not in FRAGMENT_TYPES:
            raise ValueError(f"fragment_type 必须是 {FRAGMENT_TYPES}")
        cur = self.con.execute(
            "INSERT INTO memory_fragments(fragment_type,subject,content,entities,tags,source_ref) "
            "VALUES(?,?,?,?,?,?)",
            (ftype, subject, content, _jl(entities), _jl(tags), source_ref))
        self.con.commit()
        return cur.lastrowid

    def list_fragments(self, ftype=None, status="active", limit=50):
        sql = "SELECT * FROM memory_fragments WHERE 1=1"
        p = []
        if ftype:
            sql += " AND fragment_type=?"
            p.append(ftype)
        if status:
            sql += " AND status=?"
            p.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        p.append(limit)
        return self.con.execute(sql, p).fetchall()

    def search_memory(self, q, limit=20, audit=True, mode="fts+like", namespace=None):
        q = (q or "").strip()
        ids = set(self._fts_ids("fragment_fts", ["content"], q, limit * 3) or [])
        ids |= set(self._like_ids("memory_fragments", ["content", "tags"], q, limit * 3, namespace=namespace))
        rows = []
        for i in list(ids)[:limit * 4]:
            r = self.con.execute("SELECT * FROM memory_fragments WHERE id=?", (i,)).fetchone()
            if r and (not namespace or r["namespace"] == namespace):
                rows.append(r)
        # P1 decay：importance=high 加权；普通碎片按创建时间衰减（只降权不删除）
        rows.sort(key=lambda r: self._decay_key(r), reverse=True)
        rows = rows[:limit]
        if audit:
            self._audit(q, mode, {"memory_fragments": len(ids)}, [r["id"] for r in rows])
        return rows

    def _decay_key(self, r):
        """返回排序键：值越大越靠前。
        importance=high 永不衰减；normal 按 (创建时间距今天数)^0.5 指数衰减。
        """
        import datetime as _dt
        imp = r["importance"] if "importance" in r.keys() else "normal"
        created = (r["created_at"] or "")[:10]
        try:
            d0 = _dt.date.fromisoformat(created)
            age_days = max((_dt.date.today() - d0).days, 0)
        except Exception:
            age_days = 0
        if imp == "high":
            return 1e9 - age_days
        return 1000.0 / (1.0 + age_days ** 0.5)

    # ------------------------------------------------- P0 冲突消解（记忆打架检测）
    _CONFLICT_SENSITIVE = ("行业", "status", "状态", "配置", "版本", "定位", "地址", "电话", "账号",
                           "价格", "单价", "负责人", "角色", "显卡", "GPU", "内存", "模型", "硬件",
                           "主营业务", "城市", "规模", "人数", "目标", "策略")

    def detect_conflicts(self, limit=150):
        """扫描记忆碎片，找出互相矛盾的信息（记忆打架）。

        两类结果：
          strong=True  真矛盾：同一敏感属性（如"定位"）在不同碎片中被记录为不同值 → 必须人工裁决
          strong=False 疑似重复：同一事实被重复记录（内容高重叠）→ 可选合并
        只读，不删除、不修改，供人工确认（Mem0 式冲突消解的轻量版）。
        """
        import re as _re
        frags = [dict(r) for r in self.con.execute(
            "SELECT id, fragment_type, content, created_at FROM memory_fragments "
            "WHERE status='active' AND content IS NOT NULL AND length(content)>=12 "
            "ORDER BY id DESC LIMIT ?", (limit,))]
        # 每条提取「敏感属性 → 值集合」
        ann = []
        for f in frags:
            content = f["content"]
            hits = [k for k in self._CONFLICT_SENSITIVE if k in content]
            attr_vals = {}   # key -> set(values)
            for m in _re.finditer(
                    r"([\u4e00-\u9fa5A-Za-z0-9]{2,12})(?:是|为|：|=|，改为|调整为)([\u4e00-\u9fa5A-Za-z0-9]{2,24})",
                    content):
                k, v = m.group(1), m.group(2)
                if any(s in k for s in self._CONFLICT_SENSITIVE):
                    attr_vals.setdefault(k, set()).add(v)
            ann.append({"f": f, "hits": hits, "attr_vals": attr_vals})
        cand = []
        for i in range(len(ann)):
            for j in range(i + 1, len(ann)):
                a, b = ann[i], ann[j]
                if not (a["hits"] and b["hits"]):
                    continue
                # ---- 强冲突：同一属性，值集合不同（真矛盾）----
                shared_keys = set(a["attr_vals"]) & set(b["attr_vals"])
                conflicts = {}
                for k in shared_keys:
                    if a["attr_vals"][k] != b["attr_vals"][k]:
                        conflicts[k] = sorted(a["attr_vals"][k]) + ["≠"] + sorted(b["attr_vals"][k])
                if conflicts:
                    cand.append({
                        "a_id": a["f"]["id"], "b_id": b["f"]["id"],
                        "a": a["f"]["content"][:140], "b": b["f"]["content"][:140],
                        "shared_hits": sorted(set(a["hits"]) & set(b["hits"])),
                        "sim": round(self._jaccard(a["f"]["content"], b["f"]["content"]), 2),
                        "strong": True,
                        "conflict_attrs": [{"attr": k, "values": v} for k, v in conflicts.items()],
                    })
                    continue
                # ---- 弱候选：内容高重叠 + 命中同一敏感字段（疑似重复记录）----
                if set(a["hits"]) & set(b["hits"]):
                    sim = self._jaccard(a["f"]["content"], b["f"]["content"])
                    # 完全相等或高重叠都算疑似重复
                    is_dup = a["f"]["content"] == b["f"]["content"] or sim >= 0.62
                    if is_dup:
                        cand.append({
                            "a_id": a["f"]["id"], "b_id": b["f"]["id"],
                            "a": a["f"]["content"][:140], "b": b["f"]["content"][:140],
                            "shared_hits": sorted(set(a["hits"]) & set(b["hits"])),
                            "sim": round(1.0 if a["f"]["content"] == b["f"]["content"] else sim, 2),
                            "strong": False,
                            "conflict_attrs": [],
                        })
        cand.sort(key=lambda x: (not x["strong"], -x["sim"]))
        return cand

    @staticmethod
    def _jaccard(s1, s2):
        """字符级 Jaccard 相似度（交集/并集），0~1。对重复记录敏感、对长文本不虚高。"""
        sa, sb = set(s1), set(s2)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def add_rolling_summary(self, scope_key, summary, start_ref=None, end_ref=None, version=None):
        if version is None:
            last = self.con.execute(
                "SELECT checkpoint_version FROM rolling_summaries WHERE scope_key=? "
                "ORDER BY id DESC LIMIT 1", (scope_key,)).fetchone()
            version = (last["checkpoint_version"] if last else 0) + 1
        cur = self.con.execute(
            "INSERT INTO rolling_summaries(scope_key,start_ref,end_ref,summary,checkpoint_version) "
            "VALUES(?,?,?,?,?)",
            (scope_key, start_ref, end_ref, summary, version))
        self.con.commit()
        return cur.lastrowid

    def get_latest_summary(self, scope_key):
        return self.con.execute(
            "SELECT * FROM rolling_summaries WHERE scope_key=? ORDER BY id DESC LIMIT 1",
            (scope_key,)).fetchone()

    def list_summaries(self, scope_key=None, limit=20):
        sql = "SELECT * FROM rolling_summaries"
        p = []
        if scope_key:
            sql += " WHERE scope_key=?"
            p.append(scope_key)
        sql += " ORDER BY id DESC LIMIT ?"
        p.append(limit)
        return self.con.execute(sql, p).fetchall()

    def link_fragments(self, a, b, action="link"):
        self.con.execute(
            "INSERT INTO memory_relations(from_frag_id,to_frag_id,action) VALUES(?,?,?)", (a, b, action))
        self.con.commit()

    def _audit(self, query, mode, candidate_sources, hits_ids, fallback=None):
        try:
            self.con.execute(
                "INSERT INTO memory_retrieval_audits(query,mode,candidate_sources,hits_ids,fallback_reason) "
                "VALUES(?,?,?,?,?)",
                (query, mode, _jl(candidate_sources), _jl(hits_ids), fallback))
            self.con.commit()
        except Exception:
            pass

    def recall(self, query=None, top_summaries=2, limit=8):
        """防遗忘：按请求命中记忆碎片 + 滚动摘要，输出紧凑上下文。"""
        lines = []
        for s in self.con.execute(
                "SELECT * FROM rolling_summaries ORDER BY id DESC LIMIT ?", (top_summaries,)).fetchall():
            lines.append(f"[滚动摘要 v{s['checkpoint_version']} · {s['scope_key']}] {s['summary']}")
        frags = self.search_memory(query, limit=limit, audit=False) if query else self.list_fragments(limit=limit)
        if query:
            seen = {f["id"] for f in frags}
            try:
                for h in self.search_semantic(query, limit=limit, target_types=["memory_fragment"]):
                    if h["id"] in seen:
                        continue
                    row = self.con.execute(
                        "SELECT content FROM memory_fragments WHERE id=?", (h["id"],)).fetchone()
                    if row:
                        frags.append({"fragment_type": "semantic", "id": h["id"], "content": row["content"]})
            except Exception:
                pass
        for f in frags:
            lines.append(f"[{f['fragment_type']}] {f['content']}")
        if query:
            self._audit(query, "recall",
                        {"rolling_summaries": min(top_summaries, 99), "memory_fragments": len(frags)},
                        [f["id"] for f in frags])
        return lines

    # ------------------------------------------------- 统一检索（写审计）
    def search(self, q, limit=10, namespace=None):
        q = (q or "").strip()
        ns_where = " AND namespace=?" if namespace else ""
        ns_p = [namespace] if namespace else []
        res = {"entities": [], "content": [], "memory": [], "kb": [], "keyword_packs": [], "semantic": []}
        res["entities"] = [dict(r) for r in self.search_entities(q, limit=limit, namespace=namespace)]
        res["content"] = [dict(r) for r in self.search_content(q, limit=limit, namespace=namespace)]
        res["memory"] = [dict(r) for r in self.search_memory(q, limit=limit, audit=False, namespace=namespace)]
        like = f"%{q}%"
        res["kb"] = [dict(r) for r in self.con.execute(
            "SELECT c.id, c.doc_id, d.title, c.content, c.seq FROM kb_chunk c "
            "JOIN kb_document d ON d.id=c.doc_id WHERE c.content LIKE ?" + ns_where +
            " ORDER BY c.id DESC LIMIT ?", (like, *ns_p, limit)).fetchall()]
        try:
            res["semantic"] = self.search_semantic(q, limit=limit, namespace=namespace)
        except Exception:
            res["semantic"] = []
        # P2 混合检索调优 + 轻量 rerank：关键词命中(FTS/LIKE)与语义命中融合排序。
        # 归一化分数：FTS 前几位给 0.9~0.6 递减，语义给 score 系数 0.6，融合后重排。
        try:
            res["semantic"] = self._hybrid_rerank(q, res["semantic"], limit=limit)
        except Exception:
            pass
        for kp in self.list_keyword_packs():
            words = _parse(kp["words_json"], [])
            if any(q in (w or "") for w in words) or q in (kp["name"] or ""):
                res["keyword_packs"].append(dict(kp))
        src = {k: len(v) for k, v in res.items()}
        hits = [i["id"] for v in res.values() if isinstance(v, list) for i in v]
        self._audit(q, "unified", src, hits)
        return res

    def _hybrid_rerank(self, q, semantic, limit=10):
        """把关键词命中（content/memory/kb）与语义命中融合成统一排序列表。
        返回带 score 的语义条目（已融入关键词信号），保留原字段结构。
        """
        try:
            mem_ids = {r["id"] for r in self._like_ids("memory_fragments", ["content", "tags"], q, 30)}
            kb_ids = set(self._fts_ids("kb_chunk_fts", ["content"], q, 30) or [])
            kb_ids |= set(self._like_ids("kb_chunk", ["content"], q, 30))
            kw_ids = set(self._fts_ids("content_fts", ["title", "body"], q, 30) or [])
            kw_ids |= set(self._like_ids("content_item", ["title", "body"], q, 30))
        except Exception:
            mem_ids, kb_ids, kw_ids = set(), set(), set()
        if not semantic:
            return []
        boost = {}
        for i, s in enumerate(semantic[:limit]):
            key = (s["type"], s["id"])
            if (s["type"] == "memory_fragment" and s["id"] in mem_ids):
                boost[key] = 0.25
            elif (s["type"] == "kb_chunk" and s["id"] in kb_ids):
                boost[key] = 0.2
            elif (s["type"] == "content" and s["id"] in kw_ids):
                boost[key] = 0.2
            else:
                boost[key] = 0.0
        for s in semantic:
            key = (s["type"], s["id"])
            s["score"] = round(min(s["score"] + boost.get(key, 0.0), 1.0), 4)
        semantic.sort(key=lambda x: x["score"], reverse=True)
        return semantic[:limit]

    # ------------------------------------------------- 统计
    def stats(self):
        def c(t):
            return self.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {
            "entity": c("entity"), "entity_link": c("entity_link"),
            "content_item": c("content_item"), "kb_document": c("kb_document"),
            "kb_chunk": c("kb_chunk"), "ai_conversation": c("ai_conversation"),
            "master_data": c("master_data"), "keyword_pack": c("keyword_pack"),
            "ingest_source": c("ingest_source"), "ingest_record": c("ingest_record"),
            "memory_fragments": c("memory_fragments"), "rolling_summaries": c("rolling_summaries"),
            "memory_relations": c("memory_relations"), "retrieval_audits": c("memory_retrieval_audits"),
            "embeddings": c("embeddings"), "sys_profile": c("sys_profile"),
        }

    # ------------------------------------------------- 系统台账（AI 电脑中枢）
    def set_profile(self, key, value, kind="model", note=None):
        """写入/更新一条系统台账（模型/硬件/设置）。value 可为任意 JSON 可序列化对象。"""
        import json as _j
        v = _j.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        self.con.execute(
            "INSERT INTO sys_profile(key, value, kind, note, updated_at) VALUES(?,?,?,?,datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, kind=excluded.kind, "
            "note=excluded.note, updated_at=datetime('now','localtime')",
            (key, v, kind, note))
        self.con.commit()
        return True

    def get_profile(self, key=None):
        """读取系统台账。key 为空返回全部。value 为 JSON 时解析为对象，否则返回原文。"""
        def _v(s):
            try:
                return json.loads(s) if s else None
            except Exception:
                return s  # 非 JSON 原文返回
        if key:
            r = self.con.execute("SELECT key,value,kind,note,updated_at FROM sys_profile WHERE key=?",
                                 (key,)).fetchone()
            if not r:
                return None
            return {"key": r[0], "value": _v(r[1]), "kind": r[2],
                    "note": r[3], "updated_at": r[4]}
        rows = self.con.execute("SELECT key,value,kind,note,updated_at FROM sys_profile").fetchall()
        out = []
        for r in rows:
            out.append({"key": r[0], "value": _v(r[1]), "kind": r[2],
                        "note": r[3], "updated_at": r[4]})
        return out

    # ------------------------------------------------- 从 content_brain 导入
    def import_content_brain(self, src_path, if_exists="skip"):
        stats = {}
        src = sqlite3.connect(src_path)
        src.row_factory = sqlite3.Row
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        has = lambda t: t in tables

        if has("companies"):
            for r in src.execute("SELECT * FROM companies"):
                k = r.keys()
                name = r["company_name"] if "company_name" in k else r["brand_name"]
                if not name:
                    continue
                eid = self.add_entity("org", name, org=name,
                                      meta={"key": r["company_key"] if "company_key" in k else None,
                                            "website": r["website"] if "website" in k else None,
                                            "slogan": r["slogan"] if "slogan" in k else None,
                                            "desc": r["description"] if "description" in k else None},
                                      if_exists=if_exists)
                stats["companies"] = stats.get("companies", 0) + 1
                if has("team_members"):
                    for m in src.execute("SELECT * FROM team_members WHERE company_id=?", (r["id"],)):
                        mk = m.keys()
                        peid = self.add_entity("person", m["name"], org=name,
                                               role=m["role"] if "role" in mk else None,
                                               contact=_parse(m["contact"], {}) if "contact" in mk else None,
                                               meta={"profile": m["profile"] if "profile" in mk else None},
                                               if_exists=if_exists)
                        self.link(peid, eid, "belongs_to", "团队成员")
                        stats["people"] = stats.get("people", 0) + 1
                if has("accounts"):
                    for a in src.execute("SELECT * FROM accounts WHERE company_id=?", (r["id"],)):
                        ak = a.keys()
                        aeid = self.add_entity("account", a["account_name"], org=name,
                                               meta={"key": a["account_key"] if "account_key" in ak else None,
                                                     "industry": a["industry"] if "industry" in ak else None,
                                                     "status": a["status"] if "status" in ak else None},
                                               if_exists=if_exists)
                        self.link(aeid, eid, "belongs_to", "运营账号")
                        stats["accounts"] = stats.get("accounts", 0) + 1
                        if has("account_platforms"):
                            for ap in src.execute("SELECT * FROM account_platforms WHERE account_id=?",
                                                  (a["id"],)):
                                apk = ap.keys()
                                pe2 = self.add_entity("platform", ap["platform"], org=name,
                                                      meta={"url": ap["platform_account_url"]
                                                            if "platform_account_url" in apk else None,
                                                            "ai_disclosure": ap["ai_disclosure_required"]
                                                            if "ai_disclosure_required" in apk else None},
                                                      if_exists=if_exists)
                                self.link(pe2, aeid, "platform_of", ap["platform"])
                                stats["platforms"] = stats.get("platforms", 0) + 1
        if has("products"):
            for p in src.execute("SELECT * FROM products"):
                pk = p.keys()
                self.add_entity("product", p["product_name"], org=None,
                                meta={"category": p["product_category"] if "product_category" in pk else None,
                                      "desc": p["short_description"] if "short_description" in pk else None,
                                      "pricing": p["pricing_summary"] if "pricing_summary" in pk else None,
                                      "pain": p["customer_pain_points"] if "customer_pain_points" in pk else None,
                                      "caps": p["core_capabilities"] if "core_capabilities" in pk else None},
                                if_exists=if_exists)
                stats["products"] = stats.get("products", 0) + 1
        if has("capabilities"):
            for cap in src.execute("SELECT * FROM capabilities"):
                ck = cap.keys()
                self.add_master("capability", cap["capability_name"],
                                cap["capability_group"] if "capability_group" in ck else "")
                stats["capabilities"] = stats.get("capabilities", 0) + 1
        if has("topics"):
            for t in src.execute("SELECT * FROM topics"):
                dup = self.con.execute(
                    "SELECT id FROM content_item WHERE title=? AND category='topic'",
                    (t["topic_name"],)).fetchone()
                if dup:
                    continue
                tk = t.keys()
                body = ""
                if "audience_problem" in tk and t["audience_problem"]:
                    body += str(t["audience_problem"]) + "\n\n"
                if "business_relevance" in tk and t["business_relevance"]:
                    body += str(t["business_relevance"])
                self.add_content(t["topic_name"], body, ctype="note", category="topic",
                                 source_type="import", source_tag="content_brain")
                stats["topics"] = stats.get("topics", 0) + 1
        src.close()
        return stats

    # ------------------------------------------------- 向量语义检索（本地 bge-small-zh）
    def _vec(self):
        if self._vec_engine is None:
            import os
            from fastembed import TextEmbedding
            cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".model_cache")
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            self._vec_engine = TextEmbedding("BAAI/bge-small-zh-v1.5", cache_dir=cache)
        return self._vec_engine

    def embed_texts(self, texts):
        import numpy as np
        return [np.asarray(v, dtype=np.float32) for v in self._vec().embed(list(texts))]

    def index_vectors(self, reset=False):
        """为 content / kb_chunk / memory_fragment 生成向量写入 embeddings 表。返回新增条数。"""
        if reset:
            self.con.execute("DELETE FROM embeddings")
            self.con.commit()
        rows = []
        for r in self.con.execute("SELECT id, title, body FROM content_item"):
            rows.append(("content", r["id"], (r["title"] or "") + "\n" + (r["body"] or "")))
        for r in self.con.execute("SELECT id, content FROM kb_chunk"):
            rows.append(("kb_chunk", r["id"], r["content"] or ""))
        for r in self.con.execute("SELECT id, content FROM memory_fragments WHERE status='active'"):
            rows.append(("memory_fragment", r["id"], r["content"] or ""))
        # 实体（客户/账号/平台等）：name + org + meta 描述拼成检索文本
        for r in self.con.execute("SELECT id, name, org, meta_json FROM entity"):
            meta = _parse(r["meta_json"] or "{}", {})
            parts = [r["name"] or ""]
            if r["org"]:
                parts.append(r["org"])
            if isinstance(meta, dict):
                for k in ("industry", "desc", "profile", "slogan"):
                    if meta.get(k):
                        parts.append(str(meta[k]))
            rows.append(("entity", r["id"], "\n".join(parts)))
        todo = []
        for t, i, text in rows:
            has = self.con.execute("SELECT 1 FROM embeddings WHERE target_type=? AND target_id=?",
                                   (t, i)).fetchone()
            if not has:
                todo.append((t, i, text))
        if not todo:
            return 0
        vecs = self.embed_texts([text for _, _, text in todo])
        for (t, i, _), v in zip(todo, vecs):
            self.con.execute(
                "INSERT OR REPLACE INTO embeddings(target_type,target_id,vector,model) VALUES(?,?,?,?)",
                (t, i, v.tobytes(), "bge-small-zh-v1.5"))
        self.con.commit()
        return len(todo)

    def search_semantic(self, q, limit=10, target_types=None, namespace=None):
        """语义检索：本地向量余弦。embeddings 空时自动先建索引。"""
        import numpy as np
        cnt = self.con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        if cnt == 0:
            self.index_vectors()
        qv = self.embed_texts([q])[0]
        qn = qv / (np.linalg.norm(qv) + 1e-9)
        scores = []
        for r in self.con.execute("SELECT target_type, target_id, vector FROM embeddings"):
            if target_types and r["target_type"] not in target_types:
                continue
            if namespace:
                # 向量表没有 namespace，回源检查目标行
                t, i = r["target_type"], r["target_id"]
                try:
                    if t == "content":
                        row = self.con.execute("SELECT namespace FROM content_item WHERE id=?", (i,)).fetchone()
                    elif t == "kb_chunk":
                        row = self.con.execute(
                            "SELECT d.namespace FROM kb_chunk c JOIN kb_document d ON d.id=c.doc_id "
                            "WHERE c.id=?", (i,)).fetchone()
                    elif t == "memory_fragment":
                        row = self.con.execute("SELECT namespace FROM memory_fragments WHERE id=?", (i,)).fetchone()
                    elif t == "entity":
                        row = self.con.execute("SELECT namespace FROM entity WHERE id=?", (i,)).fetchone()
                    else:
                        row = None
                    if row and row["namespace"] != namespace:
                        continue
                except Exception:
                    continue
            v = np.frombuffer(r["vector"], dtype=np.float32)
            vn = v / (np.linalg.norm(v) + 1e-9)
            scores.append((float(qn @ vn), r["target_type"], r["target_id"]))
        scores.sort(reverse=True)
        out = []
        for score, t, i in scores[:limit]:
            text = ""
            if t == "content":
                row = self.con.execute("SELECT title, body FROM content_item WHERE id=?", (i,)).fetchone()
                if row:
                    text = (row["title"] or "") + ("\n" + row["body"] if row["body"] else "")
            elif t == "kb_chunk":
                row = self.con.execute("SELECT content FROM kb_chunk WHERE id=?", (i,)).fetchone()
                text = row["content"] if row else ""
            elif t == "memory_fragment":
                row = self.con.execute("SELECT content FROM memory_fragments WHERE id=?", (i,)).fetchone()
                text = row["content"] if row else ""
            elif t == "entity":
                row = self.con.execute("SELECT name, org, meta_json FROM entity WHERE id=?", (i,)).fetchone()
                if row:
                    meta = _parse(row["meta_json"] or "{}", {})
                    text = (row["name"] or "")
                    if row["org"]:
                        text += "\n" + row["org"]
                    if isinstance(meta, dict) and meta.get("desc"):
                        text += "\n" + meta["desc"]
            out.append({"type": t, "id": i, "score": round(score, 4), "text": text[:200]})
        self._audit(q, "vector", {"embeddings": len(scores)}, [o["id"] for o in out])
        return out

    def daily_context(self, days=5):
        """每日开工上下文：滚动摘要 + 铁律 + 最近工作日志 + 未完成发布。返回文本行。"""
        lines = []
        for s in self.con.execute("SELECT * FROM rolling_summaries ORDER BY id DESC LIMIT 1"):
            lines.append(f"[滚动摘要] {s['summary']}")
        for r in self.con.execute(
                "SELECT content FROM memory_fragments WHERE source_ref LIKE 'iron_rules%' "
                "ORDER BY id"):
            lines.append(f"[铁律] {r['content']}")
        logs = self.con.execute(
            "SELECT title, body FROM content_item WHERE category='工作日志' "
            "ORDER BY updated_at DESC LIMIT ?", (days,)).fetchall()
        for r in reversed(logs):
            lines.append(f"[日志] {r['title']}: {(r['body'] or '')[:80]}")
        pend = self.con.execute(
            "SELECT title FROM content_item WHERE category='发布记录' AND status!='done' "
            "ORDER BY updated_at DESC LIMIT 10").fetchall()
        for r in pend:
            lines.append(f"[待办·发布] {r['title']}")
        # 客户台账（2026-09-04 起：entity 表维护，汉全出海=root 服务方）
        try:
            root = self.con.execute("SELECT id FROM entity WHERE name='汉全出海' AND type='account'").fetchone()
            if root:
                custs = self.con.execute(
                    "SELECT e.name, e.meta_json FROM entity_link l "
                    "JOIN entity e ON e.id=l.to_id WHERE l.from_id=? AND l.relation='serves' "
                    "ORDER BY e.id", (root["id"],)).fetchall()
                if custs:
                    lines.append("[客户台账] 汉全出海服务客户：")
                    for c in custs:
                        m = _parse(c["meta_json"], {})
                        st = m.get("status", "")
                        flag = "🟢" if st == "active" else ("⚪" if st == "previous" else "?")
                        lines.append(f"  {flag} {c['name']}（{m.get('industry','')}）"
                                     f"{'· 包:' + m.get('upload_pack','') if m.get('upload_pack') else ''}")
        except Exception:
            pass
        # 用户自定义每日指引（可在此按需追加，如产出目录/状态机/SOP 路径）
        # 示例：lines.append("[流水线] 产出目录: /path/to/output/")

        # ── P1 主动提醒（2026-09-09 v2.1，学邻舍"主动行为"）──
        # ① 未完成的工作项（status != done）
        todo = self.con.execute(
            "SELECT title, status FROM content_item "
            "WHERE category IN ('工作日志','任务','决策') AND status NOT IN ('done','已发布','已完成') "
            "ORDER BY updated_at DESC LIMIT 8").fetchall()
        if todo:
            lines.append("[提醒·未完成] 上次还没做完的事：")
            for r in todo:
                lines.append(f"  · {r['title']}（{r['status']}）")
        # ② 最近决策（最近 5 条 decision）
        dec = self.con.execute(
            "SELECT content FROM memory_fragments WHERE fragment_type='decision' "
            "ORDER BY created_at DESC LIMIT 5").fetchall()
        if dec:
            lines.append("[提醒·最近决策]")
            for r in dec:
                lines.append(f"  · {(r['content'] or '')[:70]}")
        # ③ 高价值知识（importance=high，若已启用）
        hi = self.con.execute(
            "SELECT content FROM memory_fragments WHERE importance='high' "
            "ORDER BY created_at DESC LIMIT 5").fetchall()
        if hi:
            lines.append("[提醒·高价值知识]")
            for r in hi:
                lines.append(f"  · {(r['content'] or '')[:70]}")

        # ── P1 滚动摘要自动压缩（2026-09-09 v2.1：旧日志自动蒸馏进长期记忆）──
        try:
            self._auto_compress_logs()
        except Exception:
            pass

        return lines

    def _auto_compress_logs(self, older_days=7, max_titles=12):
        """把超过 older_days 天的「工作日志」自动压缩进滚动摘要（append 新 checkpoint）。
        幂等：按日期范围去重，不会重复蒸馏同一批日志。只摘要不删除原始日志。
        """
        import datetime as _dt
        today = _dt.date.today()
        cutoff = (today - _dt.timedelta(days=older_days)).isoformat()
        logs = self.con.execute(
            "SELECT title, body, updated_at FROM content_item "
            "WHERE category='工作日志' AND updated_at < ? "
            "ORDER BY updated_at DESC", (cutoff + " 00:00:00",)).fetchall()
        if not logs:
            return 0
        # 取最近一批（按日期分桶，避免每次全量）
        dates = {}
        for r in logs:
            d = (r["updated_at"] or "")[:10]
            dates.setdefault(d, []).append(r)
        # 只处理最新一个日期桶，避免一次性把所有旧日志全塞进来
        bucket_date = sorted(dates.keys())[-1]
        bucket = dates[bucket_date]
        # 幂等：该日期桶是否已被压缩过（查 rolling_summaries 的 end_ref）
        done = self.con.execute(
            "SELECT 1 FROM rolling_summaries WHERE scope_key='auto' AND end_ref=?",
            (bucket_date,)).fetchone()
        if done:
            return 0
        titles = [r["title"] for r in bucket[:max_titles]]
        summary = ("[自动压缩 {bd}] 工作日志要点：{ts}".format(
            bd=bucket_date, ts="；".join(titles)))
        self.add_rolling_summary("auto", summary, start_ref=None, end_ref=bucket_date)
        return len(bucket)


# ========================================================= CLI
def _main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="cyber_brain", description="塞博大脑 · 个人工作知识库（三源融合）")
    p.add_argument("--db", default="cyber_brain.db")
    sub = p.add_subparsers(dest="cmd")

    pe = sub.add_parser("entity", help="实体")
    pe.add_argument("--add", action="store_true")
    pe.add_argument("--type", choices=ENTITY_TYPES)
    pe.add_argument("--name")
    pe.add_argument("--org")
    pe.add_argument("--role")
    pe.add_argument("--if-exists", default="skip")
    pe.add_argument("--list", action="store_true")
    pe.add_argument("--search")

    pl = sub.add_parser("link", help="实体关联")
    pl.add_argument("--from", dest="from_id", type=int, required=True)
    pl.add_argument("--to", dest="to_id", type=int, required=True)
    pl.add_argument("--relation", required=True)
    pl.add_argument("--note")

    pc = sub.add_parser("content", help="内容")
    pc.add_argument("--add", action="store_true")
    pc.add_argument("--title")
    pc.add_argument("--body", default="")
    pc.add_argument("--type", choices=CONTENT_TYPES, default="note")
    pc.add_argument("--status", default="draft")
    pc.add_argument("--cat")
    pc.add_argument("--entity-ids")
    pc.add_argument("--source-tag", default="manual")
    pc.add_argument("--list", action="store_true")
    pc.add_argument("--search")
    pc.add_argument("--get", type=int)

    pd = sub.add_parser("doc", help="知识库文档")
    pd.add_argument("--add", action="store_true")
    pd.add_argument("--title")
    pd.add_argument("--text", default="")
    pd.add_argument("--source")
    pd.add_argument("--list", action="store_true")
    pd.add_argument("--search")
    pd.add_argument("--get", type=int)

    pcv = sub.add_parser("conv", help="AI 会话")
    pcv.add_argument("--add", action="store_true")
    pcv.add_argument("--title")
    pcv.add_argument("--session")
    pcv.add_argument("--get", type=int)
    pcv.add_argument("--append", type=int)
    pcv.add_argument("--role")
    pcv.add_argument("--text")

    pf = sub.add_parser("frag", help="记忆碎片")
    pf.add_argument("--add", action="store_true")
    pf.add_argument("--type", choices=FRAGMENT_TYPES, default="fact")
    pf.add_argument("--content")
    pf.add_argument("--subject", default="work")
    pf.add_argument("--list", action="store_true")
    pf.add_argument("--search")

    pev = sub.add_parser("event", help="工作事件（收工打卡/开工检查）")
    pev.add_argument("--add", help="收工打卡：一句话记录今天干了什么")
    pev.add_argument("--check", action="store_true", help="开工检查：昨天是否漏记")
    pev.add_argument("--list", action="store_true", help="最近事件")
    pev.add_argument("--n", type=int, default=10)

    ps = sub.add_parser("summary", help="滚动摘要")
    ps.add_argument("--add", action="store_true")
    ps.add_argument("--scope", default="work")
    ps.add_argument("--summary")
    ps.add_argument("--get", action="store_true")

    pr = sub.add_parser("recall", help="防遗忘：命中记忆碎片+摘要")
    pr.add_argument("query", nargs="?", default=None)

    psr = sub.add_parser("search", help="统一搜索")
    psr.add_argument("query")

    pm = sub.add_parser("master", help="字典")
    pm.add_argument("--add", action="store_true")
    pm.add_argument("--category")
    pm.add_argument("--code")
    pm.add_argument("--label")
    pm.add_argument("--list", action="store_true")
    pm.add_argument("--cat")

    pk = sub.add_parser("kw", help="关键词组")
    pk.add_argument("--add", action="store_true")
    pk.add_argument("--name")
    pk.add_argument("--words")
    pk.add_argument("--list", action="store_true")

    pi = sub.add_parser("ingest", help="数据接入（合规）")
    pi.add_argument("--source", action="store_true")
    pi.add_argument("--type")
    pi.add_argument("--name")
    pi.add_argument("--auth")
    pi.add_argument("--record", action="store_true")
    pi.add_argument("--source-id", type=int)
    pi.add_argument("--target-type")
    pi.add_argument("--target-id", type=int)
    pi.add_argument("--tag")

    pimp = sub.add_parser("import", help="从 content_brain 导入")
    pimp.add_argument("--from", dest="src")

    pidx = sub.add_parser("index", help="重建向量索引")
    pidx.add_argument("--reset", action="store_true")

    pday = sub.add_parser("daily", help="每日开工上下文（防遗忘）")
    pday.add_argument("--days", type=int, default=5)

    pv = sub.add_parser("vecsearch", help="语义搜索（向量）")
    pv.add_argument("query")

    pst = sub.add_parser("stats", help="统计")

    args = p.parse_args(argv)
    db = CyberBrain(args.db)

    if args.cmd == "entity":
        if args.add:
            eid = db.add_entity(args.type, args.name, org=args.org, role=args.role,
                                if_exists=args.if_exists)
            print("entity id =", eid)
        elif args.list:
            for r in db.list_entities(args.type):
                print(r["id"], r["type"], r["name"], r["org"] or "")
        elif args.search:
            for r in db.search_entities(args.search):
                print(r["id"], r["type"], r["name"], r["org"] or "")
        else:
            print("entity: 需要 --add / --list / --search")

    elif args.cmd == "link":
        db.link(args.from_id, args.to_id, args.relation, args.note)
        print("linked")

    elif args.cmd == "content":
        if args.add:
            eids = [int(x) for x in args.entity_ids.split(",")] if args.entity_ids else None
            cid = db.add_content(args.title, args.body, ctype=args.type, status=args.status,
                                 category=args.cat, entity_ids=eids, source_tag=args.source_tag)
            print("content id =", cid)
        elif args.get:
            r = db.get_content(args.get)
            print(dict(r) if r else "not found")
        elif args.list:
            for r in db.list_content(args.type, limit=50):
                print(r["id"], f"[{r['content_type']}]", r["title"], f"({r['status']})")
        elif args.search:
            for r in db.search_content(args.search):
                print(r["id"], f"[{r['content_type']}]", r["title"], f"({r['status']})")
        else:
            print("content: 需要 --add / --get / --list / --search")

    elif args.cmd == "doc":
        if args.add:
            did = db.add_document(args.title, args.text, source=args.source)
            print("doc id =", did)
        elif args.get:
            chunks = db.get_document_chunks(args.get)
            print("chunks:", len(chunks))
            for c in chunks[:5]:
                print(" ", c["seq"], c["content"][:80])
        elif args.list:
            for r in db.list_documents():
                print(r["id"], r["title"], f"{r['chunks']} chunks")
        elif args.search:
            for c in db.search_kb(args.search):
                print(c["doc_id"], c["id"], c["content"][:80])
        else:
            print("doc: 需要 --add / --get / --list / --search")

    elif args.cmd == "conv":
        if args.add:
            cid = db.add_conversation(args.title, session_key=args.session)
            print("conv id =", cid)
        elif args.append:
            db.append_message(args.append, args.role, args.text)
            print("appended")
        elif args.get:
            r = db.get_conversation(args.get)
            print(r["title"], "|", r["messages_json"][:200]) if r else print("not found")
        else:
            print("conv: 需要 --add / --append / --get")

    elif args.cmd == "frag":
        if args.add:
            fid = db.add_fragment(args.type, args.content, subject=args.subject)
            print("fragment id =", fid)
        elif args.list:
            for r in db.list_fragments(args.type):
                print(r["id"], f"[{r['fragment_type']}]", r["content"][:80])
        elif args.search:
            for r in db.search_memory(args.search, audit=False):
                print(r["id"], f"[{r['fragment_type']}]", r["content"][:80])
        else:
            print("frag: 需要 --add / --list / --search")

    elif args.cmd == "event":
        import datetime as _dt
        if args.add:
            fid = db.add_fragment("event", args.add, subject="work_event",
                                  tags=["event"], source_ref="work_log/manual")
            print("event id =", fid, "已记录 ✅")
        elif args.check:
            # 开工检查：昨天有没有记事件
            yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
            cnt = db.con.execute(
                "SELECT COUNT(*) FROM memory_fragments WHERE fragment_type='event' "
                "AND created_at LIKE ?", (yesterday + "%",)).fetchone()[0]
            if cnt > 0:
                print(f"✅ 昨天（{yesterday}）已记录 {cnt} 条事件")
            else:
                print(f"⚠️ 昨天（{yesterday}）没有记录事件！")
                print("   记得收工时跑：cyber_brain.py event --add \"今天干了……\"")
        elif args.list:
            rows = db.list_fragments("event", limit=args.n)
            if not rows:
                print("暂无事件记录")
            for r in rows:
                print(r["id"], r["created_at"], r["content"][:90])
        else:
            print("event: 需要 --add / --check / --list")

    elif args.cmd == "summary":
        if args.add:
            db.add_rolling_summary(args.scope, args.summary)
            s = db.get_latest_summary(args.scope)
            print("summary v", s["checkpoint_version"], "id", s["id"])
        elif args.get:
            s = db.get_latest_summary(args.scope)
            print("v%s %s: %s" % (s["checkpoint_version"], s["scope_key"], s["summary"])) if s else print("无")
        else:
            print("summary: 需要 --add / --get")

    elif args.cmd == "recall":
        for line in db.recall(args.query):
            print(line)

    elif args.cmd == "search":
        res = db.search(args.query)
        for k, v in res.items():
            if not v:
                continue
            print(f"── {k} ({len(v)}) ──")
            for i in v[:5]:
                if k == "content":
                    print("  ", i["id"], i["title"])
                elif k == "entities":
                    print("  ", i["id"], i["type"], i["name"])
                elif k == "memory":
                    print("  ", i["id"], f"[{i['fragment_type']}]", i["content"][:60])
                elif k == "kb":
                    print("  ", i["doc_id"], i["content"][:60])
                elif k == "keyword_packs":
                    print("  ", i["name"], _parse(i["words_json"], [])[:5])
                elif k == "semantic":
                    print("  ", f"{i['score']:.3f}", i["type"], "#", i["id"], i["text"][:50])

    elif args.cmd == "master":
        if args.add:
            db.add_master(args.category, args.code, args.label)
            print("added")
        elif args.list:
            for r in db.list_master(getattr(args, "cat", None)):
                print(r["category"], r["code"], r["label"])
        else:
            print("master: 需要 --add / --list")

    elif args.cmd == "kw":
        if args.add:
            db.add_keyword_pack(args.name, args.words.split(",") if args.words else [])
            print("added")
        elif args.list:
            for r in db.list_keyword_packs():
                print(r["name"], _parse(r["words_json"], []))
        else:
            print("kw: 需要 --add / --list")

    elif args.cmd == "ingest":
        if args.source:
            sid = db.add_ingest_source(args.type, args.name, args.auth)
            print("ingest source id =", sid)
        elif args.record:
            rid = db.add_ingest_record(args.source_id, args.target_type, args.target_id, args.tag)
            print("ingest record id =", rid)
        else:
            print("ingest: 需要 --source / --record")

    elif args.cmd == "import":
        st = db.import_content_brain(args.src)
        print("imported:", st)

    elif args.cmd == "daily":
        for line in db.daily_context(days=args.days):
            print(line)

    elif args.cmd == "index":
        n = db.index_vectors(reset=args.reset)
        print(f"向量索引完成，新增 {n} 条（共 {db.stats()['embeddings']} 条）")

    elif args.cmd == "vecsearch":
        for r in db.search_semantic(args.query):
            print(f"  {r['score']:.4f} [{r['type']}#{r['id']}] {r['text'][:70]}")

    elif args.cmd == "stats":
        for k, v in db.stats().items():
            print(f"{k:22} {v}")

    else:
        p.print_help()


if __name__ == "__main__":
    sys.exit(_main())