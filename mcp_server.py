# -*- coding: utf-8 -*-
"""
赛博大脑 MCP 服务器（Cyber Brain MCP Server）
================================================
把赛博大脑（C:/cyber-brain/cyber_brain.db）的能力暴露为标准 MCP 工具，
供豆包（Doubao）等支持 MCP 的客户端连接使用。

传输方式：HTTP（streamable HTTP，fastmcp 默认），豆包「自定义连接器」选 HTTP 即可。
默认地址：http://127.0.0.1:8765/mcp

【重要】豆包工作对自定义 MCP 连接器有工具数量上限（约 7 个），超出部分不加载。
本服务器刻意精简为 7 个核心工具，把低频能力合并进综合查询/综合写入工具：

  1. recall            查询记忆/知识库/实体（综合查询，mode 参数切换）
  2. search            全库搜索（内容/知识库/碎片/实体/词库）
  3. add_memory        写入记忆碎片（fact/preference/decision/iron_rule 等 8 类）
  4. add_content       写入知识库文档（长文/报告/资料）
  5. daily_context     今日开工上下文（滚动摘要+铁律+最近日志）
  6. stats             知识库统计 + 冲突检测 + 系统台账（mode 参数切换）
  7. entity            实体查询（搜索实体 / 1 跳邻居 / 台账，mode 参数切换）

启动：python mcp_server.py            （默认 8765）
      python mcp_server.py --port 9000
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastmcp import FastMCP  # fastmcp 4.x 独立包

from cyber_brain import CyberBrain

# ---------------------------------------------------------------- 基础
DB_PATH = os.environ.get("CYBER_BRAIN_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cyber_brain.db"))
HOST = os.environ.get("CYBER_BRAIN_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("CYBER_BRAIN_MCP_PORT", "8765"))

mcp = FastMCP(
    "cyber-brain",
    instructions=(
        "赛博大脑（Cyber Brain）——个人/团队记忆中枢知识库。"
        "核心能力：①查询记忆与知识库（用 recall 或 search）；"
        "②写入记忆碎片（用 add_memory，类型 fact/preference/emotion/knowledge/decision/iron_rule/event/pitfall）；"
        "③写入知识库文档（用 add_content）；"
        "④今日开工上下文（用 daily_context）；"
        "⑤知识库统计/冲突检测/系统台账（用 stats）；"
        "⑥实体与关系查询（用 entity）。"
    ),
)

_brain = None


def brain():
    global _brain
    if _brain is None:
        _brain = CyberBrain(DB_PATH)
    return _brain


def _rows_to_dicts(rows):
    out = []
    for r in rows or []:
        out.append(dict(r))
    return out


# ---------------------------------------------------------------- 工具 1：综合查询
@mcp.tool()
def recall(query: str = "", mode: str = "memory", limit: int = 8, top_summaries: int = 2, days: int = 5) -> list:
    """查询赛博大脑记忆/知识库/实体/今日上下文（综合查询）。

    Args:
        query: 查询关键词（留空返回最新）。
        mode: 查询模式：memory 记忆（默认）/ kb 知识库文档 / all 全部 / daily 今日开工上下文。
        limit: 返回条数（默认 8）。
        top_summaries: 滚动摘要条数（memory 模式，默认 2）。
        days: daily 模式回溯天数（默认 5）。
    """
    b = brain()
    if mode == "daily":
        return b.daily_context(days=days)
    if mode == "kb":
        return _rows_to_dicts(b.search_kb(query, limit=limit))
    if mode == "all":
        r = b.search(query, limit=limit)
        return _rows_to_dicts(r.get("content", [])) + _rows_to_dicts(r.get("memory", [])) + _rows_to_dicts(r.get("kb", []))
    return b.recall(query=query or None, top_summaries=top_summaries, limit=limit)


# ---------------------------------------------------------------- 工具 2：全库搜索
@mcp.tool()
def search(q: str, limit: int = 10, namespace: str = "") -> dict:
    """全库搜索：内容文档 / 知识库 / 记忆碎片 / 实体 / 关键词词库。

    Args:
        q: 搜索关键词（必填）。
        limit: 每类返回条数（默认 10）。
        namespace: 命名空间过滤（可选，如 hanquan）。
    """
    return brain().search(q, limit=limit, namespace=namespace or None)


# ---------------------------------------------------------------- 工具 3：写入记忆
@mcp.tool()
def add_memory(
    ftype: str,
    content: str,
    subject: str = "work",
    tags: str = "",
    entities: str = "",
    source_ref: str = "mcp-doubao",
) -> int:
    """写入一条记忆碎片。ftype 必须是：fact/preference/emotion/knowledge/decision/iron_rule/event/pitfall。

    Args:
        ftype: 碎片类型（fact 事实 / preference 偏好 / emotion 情绪 / knowledge 知识 / decision 决策 / iron_rule 铁律 / event 事件 / pitfall 踩坑）。
        content: 碎片正文（一句话或短段）。
        subject: 主题（默认 work）。
        tags: 逗号分隔标签，如 "汉全,获客"。
        entities: 逗号分隔关联实体名，如 "汉全科技,刘力"。
        source_ref: 来源（默认 mcp-doubao，可写 doubao-export 等）。
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    ent_list = [e.strip() for e in entities.split(",") if e.strip()] if entities else None
    return brain().add_fragment(ftype, content, subject=subject, tags=tag_list, entities=ent_list, source_ref=source_ref)


# ---------------------------------------------------------------- 工具 4：写入文档
@mcp.tool()
def add_content(
    title: str,
    body: str = "",
    ctype: str = "note",
    status: str = "draft",
    category: str = "",
    tags: str = "",
    entity_ids: str = "",
    source_tag: str = "mcp-doubao",
) -> int:
    """写入知识库文档（长文/报告/资料）。

    Args:
        title: 标题。
        body: 正文（Markdown 纯文本）。
        ctype: 内容类型（note/report/article/sop/template，默认 note）。
        status: 状态（draft/done，默认 draft）。
        category: 分类，如 "词库/GEO"。
        tags: 逗号分隔标签。
        entity_ids: 逗号分隔实体 ID（关联实体）。
        source_tag: 来源标记（默认 mcp-doubao）。
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    ent_ids = [int(x.strip()) for x in entity_ids.split(",") if x.strip().isdigit()] if entity_ids else None
    return brain().add_content(
        title=title, body=body, ctype=ctype, status=status,
        category=category or None, tags=tag_list, entity_ids=ent_ids,
        source_tag=source_tag,
    )


# ---------------------------------------------------------------- 工具 5：统计/冲突/台账
@mcp.tool()
def stats(mode: str = "stats", limit: int = 150, key: str = "") -> dict:
    """知识库统计 / 冲突检测 / 系统台账。

    Args:
        mode: stats 统计（默认）/ conflicts 冲突检测 / profile 系统台账读取。
        limit: conflicts 模式扫描条数上限（默认 150）。
        key: profile 模式的台账键名（空=全部）。
    """
    b = brain()
    if mode == "conflicts":
        return {"conflicts": b.detect_conflicts(limit=limit)}
    if mode == "profile":
        return {"profile": b.get_profile(key=key or None)}
    return b.stats()


# ---------------------------------------------------------------- 工具 7：实体查询
@mcp.tool()
def entity(q: str = "", mode: str = "search", eid: int = 0, limit: int = 20) -> dict:
    """实体查询：搜索实体 / 1 跳关系邻居 / 台账。

    Args:
        q: search 模式的搜索关键词。
        mode: search 搜索实体（默认）/ neighbors 1 跳邻居 / profile 系统台账。
        eid: neighbors 模式的实体 ID。
        limit: search 模式返回条数（默认 20）。
    """
    b = brain()
    if mode == "neighbors":
        if not eid:
            return {"error": "neighbors 模式需要传 eid 实体 ID"}
        return {"neighbors": _rows_to_dicts(b.neighbors(eid))}
    if mode == "profile":
        return {"profile": b.get_profile(key=q or None)}
    return {"entities": _rows_to_dicts(b.search_entities(q, limit=limit))}


# ---------------------------------------------------------------- 入口
def main():
    parser = argparse.ArgumentParser(description="赛博大脑 MCP 服务器")
    parser.add_argument("--host", default=HOST, help=f"监听地址（默认 {HOST}）")
    parser.add_argument("--port", type=int, default=PORT, help=f"监听端口（默认 {PORT}）")
    args = parser.parse_args()

    print("=" * 60)
    print("赛博大脑 MCP 服务器 启动（精简 6 工具版，适配豆包上限）")
    print(f"  数据库: {DB_PATH}")
    print(f"  地址:   http://{args.host}:{args.port}/mcp")
    print(f"  传输:   HTTP（streamable HTTP）")
    print("  工具:   recall / search / add_memory / add_content /")
    print("          stats / entity")
    print("  豆包连接: 自定义连接器 → 服务器名称 cyber-brain → 传输类型 HTTP")
    print(f"          → 服务器 URL http://{args.host}:{args.port}/mcp")
    print("=" * 60)

    mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
