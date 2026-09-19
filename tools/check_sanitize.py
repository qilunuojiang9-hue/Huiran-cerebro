#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前脱敏检验 —— 扫描仓库里有没有混进个人/公司/客户信息。

用途：把「初步脱敏」的赛博大脑放进本仓库后、git push 之前，先跑这个。
     任何 P0/P1 命中都应该先处理掉再发布。

用法：
    python tools/check_sanitize.py            # 只报 P0/P1（默认）
    python tools/check_sanitize.py --all      # 连 P2 提示一起报
    python tools/check_sanitize.py -v         # 连原文一起打印（谨慎，别贴到公开地方）

退出码：0 = 干净；1 = 有 P0/P1 命中（可用于 pre-commit / CI）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {".git", "__pycache__", ".model_cache", "node_modules", ".venv", "venv"}
SKIP_EXT = {".db", ".sqlite", ".sqlite3", ".onnx", ".bin", ".model", ".png", ".jpg",
            ".jpeg", ".gif", ".svg", ".ico", ".zip", ".mp4", ".mp3", ".wav", ".pdf"}
# 这些文件本身就要讲"怎么脱敏"，会包含示例关键词 → 白名单
WHITELIST_FILES = {"tools/check_sanitize.py", "README.md", "CHANGELOG.md", "llms.txt"}

# ── 规则表 ────────────────────────────────────────────────
# level: P0 = 绝对不能发；P1 = 大概率不该发；P2 = 提示人工确认
RULES = [
    # —— 本地机器痕迹 ——
    ("P0", "本机 Windows 用户名路径", re.compile(r"[Cc]:[\\/]+Users[\\/]+[A-Za-z0-9_.\-]+")),
    ("P0", "macOS 用户路径", re.compile(r"/Users/[A-Za-z0-9_.\-]+/")),
    ("P0", "本机赛博大脑路径", re.compile(r"[Cc]:[\\/]+cyber-brain", re.I)),
    ("P0", "WorkBuddy 工作区路径", re.compile(r"WorkBuddy[\\/]+20\d\d-\d\d-\d\d")),
    ("P0", "WorkBuddy 技能目录", re.compile(r"\.workbuddy[\\/]+skills", re.I)),

    # —— 公司 / 品牌 ——
    ("P0", "公司名（YourCompany）", re.compile(r"YourCompany")),
    ("P0", "公司名（英文）", re.compile(r"yourcompany|yourcompany|internal-server", re.I)),
    ("P0", "内部域名", re.compile(r"(?:ai\.)?yourcompany\.com|git\.internal-server\.net|d1ss", re.I)),
    ("P0", "内部系统名", re.compile(r"internal-system|内部系统|GEO\s*Hub|internal-project", re.I)),

    # —— 客户 / 人名 ——
    ("P0", "客户名", re.compile(r"CustomerA|CustomerB|CustomerC|CustomerD|CustomerE|CustomerF|CustomerG|CustomerH|CustomerI|CustomerJ|CustomerK")),
    ("P0", "真实人名", re.compile(r"YourName|YourName")),
    ("P0", "学校/个人身份", re.compile(r"YourUniversity")),

    # —— 凭据 ——
    ("P0", "API Key / Token", re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key|bearer)\s*[=:]\s*[\"']([A-Za-z0-9\-_.]{16,})")),
    ("P0", "密钥前缀", re.compile(r"[\"'](?:sk|ghp|gho|xoxb)-[A-Za-z0-9\-_]{10,}")),
    ("P0", "长十六进制串（疑密钥）", re.compile(r"[\"']([0-9a-fA-F]{32,})[\"']")),
    ("P0", "密码赋值", re.compile(r"(?i)(password|passwd|pwd)\s*=\s*[\"'][^\"']{6,}[\"']")),

    # —— 联系方式 ——
    ("P1", "手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("P1", "邮箱（非占位）", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("P1", "座机/热线", re.compile(r"(?:400|800)[\-\s]?\d{3}[\-\s]?\d{4}")),

    # —— 业务细节 ——
    ("P1", "业务流水线细节", re.compile(r"8\s*篇推文|平台草稿箱|批量草稿|sync-tool|publish-tool")),

    # —— 提示级 ——
    # 「客户台账」是通用功能名（以服务方实体为 root 列客户），不是客户名 → 只提示
    ("P2", "业务用语（通用，人工确认）", re.compile(r"客户台账|诊断报告")),
    ("P2", "内网 IP", re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\b")),
    ("P2", "本地端口", re.compile(r"127\.0\.0\.1:(\d+)")),
    ("P2", "TODO/待清理标记", re.compile(r"(?i)(FIXME|XXX|待脱敏|删掉这句)")),
]

# 允许出现的例外（误报豁免）
ALLOW = [
    re.compile(r"#\s*示例"),                # 注释里的示例
    re.compile(r"lines\.append\(\"\[流水线\]\s*产出目录:\s*/path/to"),
    re.compile(r"your[_-]?name|example\.com|占位|PLACEHOLDER", re.I),
]


def scan_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    hits = []
    for i, line in enumerate(lines, 1):
        if any(a.search(line) for a in ALLOW):
            continue
        for level, name, rx in RULES:
            for m in rx.finditer(line):
                hits.append((level, name, i, m.group(0)[:80]))
    return hits


def main():
    show_all = "--all" in sys.argv
    verbose = "-v" in sys.argv

    results = {}
    scanned = 0
    for r, ds, fs in os.walk(ROOT):
        ds[:] = [d for d in ds if d not in SKIP_DIRS]
        for f in fs:
            p = os.path.join(r, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            if rel in WHITELIST_FILES:
                continue
            scanned += 1
            h = scan_file(p)
            if h:
                results[rel] = h

    print("=" * 78)
    print("发布前脱敏检验　｜　扫描 %d 个文件（跳过 .git/数据库/二进制/白名单）" % scanned)
    print("=" * 78)

    if not results:
        print()
        print("  ✅ 未发现任何 P0/P1/P2 命中 —— 可以发布")
        return 0

    order = {"P0": 0, "P1": 1, "P2": 2}
    p0 = p1 = p2 = 0
    for rel in sorted(results, key=lambda x: (min(order[l] for l, _, _, _ in results[x]), x)):
        hits = results[rel]
        levels = {l for l, _, _, _ in hits}
        if not show_all and levels == {"P2"}:
            continue
        print()
        print("  📄 %s" % rel)
        seen = set()
        for level, name, ln, txt in sorted(hits, key=lambda x: (order[x[0]], x[2])):
            key = (level, name, ln)
            if key in seen:
                continue
            seen.add(key)
            if level == "P0":
                p0 += 1
            elif level == "P1":
                p1 += 1
            else:
                p2 += 1
            mark = {"P0": "🔴", "P1": "🟠", "P2": "🟡"}[level]
            print("     %s [%s] %-22s 第%d行  %s" % (mark, level, name, ln,
                  txt if verbose else txt[:52]))

    print()
    print("-" * 78)
    print("  🔴 P0（绝对不能发）: %d 处　｜　🟠 P1（大概率不该发）: %d 处　｜　🟡 P2（提示）: %d 处"
          % (p0, p1, p2))
    if p0 or p1:
        print()
        print("  ⛔ 有 P0/P1 命中 —— 先脱敏再发布。")
        print("     处理方式：把真实路径/公司名/客户名换成占位符（如 /path/to/output/、YourCompany）")
        return 1
    print()
    print("  ✅ 只有 P2 提示，人工扫一眼即可")
    return 0


if __name__ == "__main__":
    sys.exit(main())
