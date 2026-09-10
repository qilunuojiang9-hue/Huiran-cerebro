#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话自动打卡脚本（session_log.py）——解决「上午做下午忘」的核心断点。

机制来源（同赛道优秀作品借鉴）：
  - kg-memory-mcp (liangquanzhou) 的 Hook 会话归档：工作告一段落自动收记忆，不用手动记
  - Mem0 的自动提取：把"干了啥"自动抽成结构化 event 碎片
  - GBrain 的 compiled truth：滚动摘要定期编译（赛博大脑已有 _auto_compress_logs）

用法：
  python session_log.py "上午完成了知识库上传包 v2.1 升级，向量索引重建到 5873 条"
      → 自动写入 1 条 event 碎片 + 1 条工作日志 content_item（含日期分类）
  python session_log.py --today          → 列出今天已记的全部工作（按时间）
  python session_log.py --list N         → 列出最近 N 条工作碎片（默认 10）

特性：
  - 判重：同一天同一标题/内容相近的碎片自动跳过（避免重复打卡）
  - 自动分类：含"发布/上传/草稿"→发布记录；含"修复/解决/踩坑"→踩坑；
              含"完成/落地/交付/升级"→完成事项；默认→工作日志
  - 幂等：重复运行不会产生重复记忆

作为模块被 MCP 服务器复用（mcp_server.session_log_tool）：
  - log(text)         → 打卡，返回 dict（写入详情 / 跳过）
  - today()           → 返回今日所有已记 event
  - recent(limit)     → 返回最近 N 条
"""
import argparse
import datetime
import os
import re
import sys

from cyber_brain import CyberBrain

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "cyber_brain.db")


def categorize(text):
    """根据文本内容自动分类（简单规则，够用）"""
    if re.search(r"发布|上传|草稿|分发|推文", text):
        return "发布记录"
    if re.search(r"修复|解决|踩坑|bug|报错|失败|问题", text):
        return "踩坑"
    if re.search(r"完成|落地|交付|升级|上线|重构|搭建|实现", text):
        return "完成事项"
    return "工作日志"


def is_dup(b, text, date):
    """判重：同一天内，正文高度相似的碎片视为重复
    规则：①subject 截断前缀相同 → 视为重复；②Jaccard 字符相似度 ≥ 0.85 → 视为重复
    """
    subject = (text[:40] if len(text) > 40 else text).strip()
    today_events = b.con.execute(
        "SELECT subject, content FROM memory_fragments "
        "WHERE fragment_type='event' AND created_at LIKE ?",
        (date + "%",)).fetchall()
    for (exist_subject, content) in today_events:
        if not content:
            continue
        # 规则 1：subject 截断前缀相同（含旧/新版本 [日期] 前缀）→ 直接重复
        if exist_subject and (exist_subject == subject or exist_subject.endswith(subject) or subject in exist_subject):
            return True
        # 规则 2：Jaccard 字符集相似度
        set_a, set_c = set(text), set(content)
        inter = len(set_a & set_c)
        union = len(set_a | set_c) or 1
        if inter / union >= 0.85:
            return True
    return False


def log(text, db_path=None):
    """会话打卡核心函数（CLI/MCP 复用）。

    Returns:
        dict: {"ok": bool, "skipped": bool, "category": str, "subject": str,
               "fragment_id": int|None, "content_id": int|None}
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "skipped": False, "error": "empty"}
    b = CyberBrain(db_path or DB)
    date = datetime.date.today().isoformat()
    subject = text[:40] if len(text) > 40 else text
    cat = categorize(text)

    if is_dup(b, text, date):
        return {"ok": True, "skipped": True, "category": cat, "subject": subject}

    fid = b.add_fragment(
        ftype="event",
        content=f"[{date}] {text}",
        subject=subject,
        tags=[cat],
        source_ref="session_log",
    )
    cid = b.add_content(
        title=f"{date} {subject}",
        body=text,
        ctype="note",
        status="done",
        category=cat,
        tags=[cat],
        source_tag="session_log",
    )
    return {
        "ok": True, "skipped": False, "category": cat, "subject": subject,
        "fragment_id": fid, "content_id": cid,
    }


def today(db_path=None):
    """返回今日所有已记 event 列表（dict 列表）"""
    b = CyberBrain(db_path or DB)
    date = datetime.date.today().isoformat()
    rows = b.con.execute(
        "SELECT id, content, created_at FROM memory_fragments "
        "WHERE fragment_type='event' AND created_at LIKE ? ORDER BY id",
        (date + "%",)).fetchall()
    return [dict(r) for r in rows]


def recent(limit=10, db_path=None):
    """返回最近 N 条 event（跨日期）"""
    b = CyberBrain(db_path or DB)
    rows = b.con.execute(
        "SELECT id, content, created_at FROM memory_fragments "
        "WHERE fragment_type='event' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── CLI 入口（MCP 工具不走这里）──
def main():
    ap = argparse.ArgumentParser(description="赛博大脑会话自动打卡")
    ap.add_argument("text", nargs="?", help="本次工作内容描述（一句话）")
    ap.add_argument("--today", action="store_true", help="列出今天已记工作")
    ap.add_argument("--list", type=int, nargs="?", const=10, help="列出最近 N 条工作碎片")
    args = ap.parse_args()

    if args.today:
        items = today()
        if not items:
            print(f"今天还没有打卡记录。")
            print('  工作告一段落后跑: python session_log.py "干了什么……"')
            return
        print(f"== 今天已记 {len(items)} 条 ==")
        for e in items:
            print(f"  #{e['id']} {e['content'][:90]}")
        return
    if args.list is not None:
        items = recent(args.list)
        if not items:
            print("暂无记录。")
            return
        print(f"== 最近 {len(items)} 条工作碎片 ==")
        for e in items:
            print(f"  #{e['id']} [{e['created_at'][:16]}] {e['content'][:80]}")
        return
    if not args.text:
        ap.print_help()
        return

    result = log(args.text.strip())
    if result.get("skipped"):
        print(f"[跳过] 今天已有相似记录：{result['subject']}...")
    elif result.get("ok"):
        print(f"[碎片] + {result['category']}：{result['subject']}")
        print(f"[日志] + {result['category']}：{result['subject']}")
    else:
        print(f"[错误] {result.get('error', 'unknown')}")


if __name__ == "__main__":
    main()
