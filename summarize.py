#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主动提取脚本（summarize.py）—— 会话/一天工作结束后自动沉淀记忆（P2-1）。

把零散的 session_log 打卡碎片，自动汇总成：
  ① 一条滚动摘要（rolling_summaries）—— 供 recall/daily 带回
  ② 高价值事件自动升级为 decision/pitfall 碎片（按关键词识别）
  ③ 输出「今日小结」文本，可直接贴给 AI 或存档

用法：
  python summarize.py                → 汇总今天所有 event 碎片 → 生成滚动摘要 + 升级碎片
  python summarize.py --days 3       → 汇总最近 3 天
  python summarize.py --dry-run      → 只预览不落库

触发方式：
  - 手动：每天收工跑一次
  - 自动化：WorkBuddy 每日自动化（收工时间）调用本脚本
  - MCP：recall(mode=daily) 或 session_log_tool 之外，也可直接跑本脚本

原理（对标 memU 的主动提取 + 滚动摘要）：
  ① 拉取时间窗内全部 event 碎片
  ② 关键词规则把「决策/踩坑/完成」分类
  ③ 生成一条汇总摘要写入 rolling_summaries
  ④ 高价值内容（踩坑/决策）单独升级为对应类型碎片，供 recall 高优先召回
"""
import argparse
import datetime
import os
import re
import sys

from cyber_brain import CyberBrain

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "cyber_brain.db")

# 决策类关键词 → decision
DECISION_KW = ("决定", "确定", "拍板", "方案", "选择", "采用", "弃用", "改为", "方向")
# 踩坑类关键词 → pitfall
PITFALL_KW = ("踩坑", "报错", "失败", "bug", "问题", "坑", "教训", "错误", "修复")
# 完成类关键词（计入摘要但不升级）
DONE_KW = ("完成", "上线", "交付", "落地", "升级", "发布", "搭建", "实现")


def _parse_date(s):
    try:
        return datetime.date.fromisoformat((s or "")[:10])
    except Exception:
        return datetime.date.today()


def collect_events(b, days):
    """拉取时间窗内 event 碎片，返回 list[dict]（含解析出的日期）"""
    since = datetime.date.today() - datetime.timedelta(days=days - 1)
    since_s = since.isoformat()
    rows = b.con.execute(
        "SELECT id, content, created_at FROM memory_fragments "
        "WHERE fragment_type='event' AND status='active' ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = _parse_date(r["created_at"])
        if d >= since:
            out.append({"id": r["id"], "content": r["content"], "date": d.isoformat()})
    return out


def upgrade_fragments(b, events, dry_run=False):
    """把高价值 event 升级为 decision / pitfall 碎片（避免重复，查重后再写）。"""
    upgraded = {"decision": 0, "pitfall": 0}
    for e in events:
        text = e["content"]
        for ftype, kws in (("decision", DECISION_KW), ("pitfall", PITFALL_KW)):
            if any(k in text for k in kws):
                # 判重：同类型同内容已存在则跳过
                dup = b.con.execute(
                    "SELECT 1 FROM memory_fragments WHERE fragment_type=? AND content=? LIMIT 1",
                    (ftype, text)).fetchone()
                if dup:
                    continue
                if not dry_run:
                    b.add_fragment(
                        ftype=ftype, content=text,
                        subject=text[:40], tags=[ftype, "auto-extract"],
                        source_ref="summarize/auto",
                    )
                upgraded[ftype] += 1
    return upgraded


def build_summary(events):
    """从事件列表生成一条滚动摘要（按日期分组 + 计数 + 要点）"""
    if not events:
        return None
    by_date = {}
    for e in events:
        by_date.setdefault(e["date"], []).append(e["content"])
    parts = []
    for d in sorted(by_date):
        items = by_date[d]
        parts.append(f"{d}（{len(items)}条）：{'；'.join(i.replace('[', '').replace(']', '') for i in items[:6])}")
        if len(items) > 6:
            parts.append(f"  …等共{len(items)}条")
    summary = "；".join(parts)
    # 截断到合理长度（滚动摘要不宜过长）
    if len(summary) > 600:
        summary = summary[:600] + "…"
    return summary


def main():
    ap = argparse.ArgumentParser(description="赛博大脑主动提取：会话结束自动沉淀记忆")
    ap.add_argument("--days", type=int, default=1, help="汇总最近 N 天（默认 1=今天）")
    ap.add_argument("--dry-run", action="store_true", help="只预览不落库")
    ap.add_argument("--db", default=DB, help="数据库路径（默认 cyber_brain.db）")
    args = ap.parse_args()

    b = CyberBrain(args.db)
    events = collect_events(b, args.days)
    if not events:
        print(f"最近 {args.days} 天没有 event 碎片，无需汇总。")
        print("  工作告一段落后先跑: python session_log.py \"干了什么……\"")
        return

    print(f"== 最近 {args.days} 天共 {len(events)} 条事件 ==")
    for e in events:
        print(f"  #{e['id']} [{e['date']}] {e['content'][:80]}")

    # ① 生成滚动摘要
    summary = build_summary(events)
    if summary:
        if args.dry_run:
            print(f"\n[预演] 滚动摘要（{len(summary)}字）:\n  {summary}")
        else:
            b.add_rolling_summary("work", summary, start_ref=events[0]["date"],
                                  end_ref=events[-1]["date"])
            print(f"\n[摘要] 已写入滚动摘要（v{len(summary)}字）✅")

    # ② 升级高价值碎片
    up = upgrade_fragments(b, events, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[预演] 将升级 {up['decision']} 条决策 + {up['pitfall']} 条踩坑碎片")
    else:
        print(f"[升级] 已升级 {up['decision']} 条决策 + {up['pitfall']} 条踩坑碎片 ✅")

    if not args.dry_run:
        print("\n✅ 主动提取完成。次日开工 `python daily_brief.py` 会自动带上今日小结。")


if __name__ == "__main__":
    main()
