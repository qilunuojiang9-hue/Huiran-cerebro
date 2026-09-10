#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「今日开工上下文」到 daily_brief/ 目录（每天自动化调用）
输出：文件路径 + 内容（stdout）
增强（2026-09-04）：
  1. 铁律（iron_rule）由 daily_context 带出
  2. 昨天是否漏记 event 事件的提醒（防遗忘）
增强（2026-09-09 v2.1）：
  3. 运行前自动把 cyber_brain.db 备份到 archive/（P0 治理）
  4. 主动提醒：未完成工作项 + 最近决策 + 高价值知识（P1 学邻舍"主动行为"）
"""
import os
import shutil
import datetime
from cyber_brain import CyberBrain

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "cyber_brain.db")
OUT = os.path.join(HERE, "daily_brief")

os.makedirs(OUT, exist_ok=True)

# ── P0：运行前自动备份数据库（带日期，保留最近 30 份）──
def auto_backup():
    try:
        arch = os.path.join(HERE, "archive")
        os.makedirs(arch, exist_ok=True)
        date = datetime.date.today().strftime("%Y%m%d")
        # 同一天只留一份（幂等，避免自动化重复跑产生多份）
        for f in os.listdir(arch):
            if f.startswith("cyber_brain.db.bak.") and date in f:
                return None
        target = os.path.join(arch, f"cyber_brain.db.bak.{date}")
        shutil.copy2(DB, target)
        # 清理超过 30 天的备份
        olds = sorted(
            [os.path.join(arch, f) for f in os.listdir(arch)
             if f.startswith("cyber_brain.db.bak.")])
        for f in olds[:-30]:
            try:
                os.remove(f)
            except Exception:
                pass
        return target
    except Exception as e:
        return "ERR:" + str(e)

bak = auto_backup()

b = CyberBrain(DB)
lines = b.daily_context(days=5)
date = datetime.date.today().strftime("%Y-%m-%d")

if bak and not str(bak).startswith("ERR:"):
    lines.append(f"[备份] ✅ 数据库已备份: {os.path.basename(bak)}")
elif bak and str(bak).startswith("ERR:"):
    lines.append(f"[备份] ⚠️ 自动备份失败: {bak}")


# 开工检查：昨天有没有记 event（防遗忘）
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
cnt = b.con.execute(
    "SELECT COUNT(*) FROM memory_fragments WHERE fragment_type='event' AND created_at LIKE ?",
    (yesterday + "%",)).fetchone()[0]
if cnt == 0:
    lines.append("")
    lines.append("[收工提醒] ⚠️ 昨天没有记录工作事件！")
    lines.append("   → 跑: cyber_brain.py event --add \"昨天干了……\"（补记）")
    lines.append("   → 以后每天收工记得打卡一次，防遗忘")

path = os.path.join(OUT, f"daily_{date}.txt")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("FILE:", path)
print("LINES:", len(lines))
print("----")
print("\n".join(lines))
