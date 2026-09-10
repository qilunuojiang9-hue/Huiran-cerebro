"""赛博大脑 · 记忆碎片去重只读扫描（P0 治理第一步）。
只报告重复候选，不修改数据库。
输出：精确重复组 + 近似重复候选(SequenceMatcher>=0.6)。
"""
import sqlite3, difflib
from collections import defaultdict

DB = "C:/cyber-brain/cyber_brain.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
rows = [dict(r) for r in db.execute(
    "SELECT id,fragment_type,subject,content,created_at FROM memory_fragments ORDER BY id")]
n = len(rows)
print("记忆碎片总数:", n)

norm = lambda s: "".join((s or "").split())
groups = defaultdict(list)
for r in rows:
    groups[norm(r["content"])].append(r["id"])
exact = [(k, v) for k, v in groups.items() if len(v) > 1 and k]
print("\n=== 精确重复组:", len(exact), "===")
for k, v in exact:
    print("  ids", v, "| 样例:", (k[:40] + ("…" if len(k) > 40 else "")))

pairs = []
for i in range(n):
    for j in range(i + 1, n):
        a, b = rows[i]["content"] or "", rows[j]["content"] or ""
        if len(a) < 20 or len(b) < 20:
            continue
        r = difflib.SequenceMatcher(None, a, b).ratio()
        if r >= 0.6:
            pairs.append((r, rows[i]["id"], rows[j]["id"],
                          rows[i]["subject"], rows[j]["subject"]))
pairs.sort(reverse=True)
print("\n=== 近似重复候选 (>=0.6):", len(pairs), "===")
for r, i, j, si, sj in pairs[:40]:
    print(f"  {r:.2f}  #{i}[{si}] <-> #{j}[{sj}]")

print("\n（只读扫描完成，未做任何修改）")
