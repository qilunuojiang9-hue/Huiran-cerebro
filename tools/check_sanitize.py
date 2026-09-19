#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前脱敏检验 —— 扫描仓库里有没有混进个人/公司/客户信息。

用途：把「初步脱敏」的赛博大脑放进本仓库后、git push 之前，先跑这个。
     任何 P0/P1 命中都应该先处理掉再发布。

用法：
    python tools/check_sanitize.py            # 只报 P0/P1（默认，扫工作树）
    python tools/check_sanitize.py --all      # 连 P2 提示一起报
    python tools/check_sanitize.py --history  # **同时扫 git 全历史**（发布前强烈建议）
    python tools/check_sanitize.py -v         # 连原文一起打印（谨慎，别贴到公开地方）

退出码：0 = 干净；1 = 有 P0/P1 命中（可用于 pre-commit / CI）

────────────────────────────────────────────────────────────────────────────
⚠️ 设计要点：**具体公司名 / 客户名 / 人名不写在本文件里**

本文件是公开的。如果把真实主体名称直接写进规则表，
等于把客户名单和内部信息一起公开了 —— 检验工具自己就成了泄漏源。

所以分两层：
  ① 通用规则（本文件的 RULES）—— 只含机器痕迹、凭据格式、联系方式这类
     与具体主体无关的模式，可以安全公开；
  ② 私有词表（仓库根目录 sanitize_terms.local.txt，**已被 .gitignore 排除**）
     —— 公司名、客户名、内部域名、真实人名全在这里，本地才有。

clone 本仓库的人没有第 ② 层，脚本会退化成只跑通用规则（仍然可用，
只是查不出特定主体的名字）。要补，自己建一个 sanitize_terms.local.txt 即可。
────────────────────────────────────────────────────────────────────────────
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMS_FILE = os.path.join(ROOT, "sanitize_terms.local.txt")

SKIP_DIRS = {".git", "__pycache__", ".model_cache", "node_modules", ".venv", "venv"}
SKIP_EXT = {".db", ".sqlite", ".sqlite3", ".onnx", ".bin", ".model", ".png", ".jpg",
            ".jpeg", ".gif", ".svg", ".ico", ".zip", ".mp4", ".mp3", ".wav", ".pdf"}

# 不做整文件白名单 —— 那会留下检查盲区。
# 若某个文件里出现了「作为反面示例的敏感串」，请用下面 ALLOW 的逐行豁免，
# 或者直接把那个串改写成占位符（更推荐）。
WHITELIST_FILES = set()

# 本地专属文件：它们**就是用来存放敏感词的**（且已被 .gitignore 排除），
# 扫描它们只会得到 100% 的自我命中噪音。
LOCAL_ONLY = {"sanitize_terms.local.txt"}
LOCAL_ONLY_SUFFIX = (".local.txt", ".local.json")

# ── ① 通用规则（与具体主体无关，可安全公开）─────────────────────────────
RULES = [
    # —— 本地机器痕迹 ——
    ("P0", "本机 Windows 用户名路径", re.compile(r"[Cc]:[\\/]+Users[\\/]+[A-Za-z0-9_.\-]+")),
    ("P0", "macOS 用户路径", re.compile(r"/Users/[A-Za-z0-9_.\-]+/")),
    ("P0", "WorkBuddy 工作区路径", re.compile(r"WorkBuddy[\\/]+20\d\d-\d\d-\d\d")),
    ("P0", "WorkBuddy 技能目录", re.compile(r"\.workbuddy[\\/]+skills", re.I)),
    ("P0", "本机家目录通配", re.compile(r"[Cc]:[\\/]+Users[\\/]+[^\\/\s\"']*[\\/]+(?:Desktop|Downloads|Documents)")),

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

    # —— 提示级 ——
    ("P2", "内网 IP", re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\b")),
    ("P2", "本地端口", re.compile(r"127\.0\.0\.1:(\d+)")),
    ("P2", "TODO/待清理标记", re.compile(r"(?i)(FIXME|XXX|待脱敏|删掉这句)")),
]

# 允许出现的例外（误报豁免）
ALLOW = [
    re.compile(r"#\s*示例"),                # 注释里的示例
    re.compile(r"lines\.append\(\"\[流水线\]\s*产出目录:\s*/path/to"),
    re.compile(r"your[_-]?name|example\.com|占位|PLACEHOLDER", re.I),
    re.compile(r"users\.noreply\.github\.com"),
]


def load_private_terms():
    """加载本地私有词表（不入库）。返回 (rules, count)；文件不存在则返回 ([], 0)。"""
    if not os.path.exists(TERMS_FILE):
        return [], 0
    rules = []
    n = 0
    with open(TERMS_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) != 3:
                continue
            level, kind, word = (p.strip() for p in parts)
            if level not in ("P0", "P1", "P2") or not word:
                continue
            try:
                rules.append((level, kind, re.compile(re.escape(word))))
                n += 1
            except re.error:
                continue
    return rules, n


def scan_file(path, rules):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    hits = []
    for i, line in enumerate(lines, 1):
        if any(a.search(line) for a in ALLOW):
            continue
        for level, name, rx in rules:
            for m in rx.finditer(line):
                hits.append((level, name, i, m.group(0)[:80]))
    return hits


def scan_history(rules):
    """扫描 git **全历史**里的每一个 blob（含已被删除文件的旧版本）。

    为什么必须单独做这一步：
        改了当前文件 ≠ 历史里干净了。旧版本仍以 blob 形式留在 .git 里，
        push 之后任何人都能用 `git log -p` / `git show <sha>` 翻出来。
        只扫工作树的检验会给出「全绿」的假象。
    """
    try:
        out = subprocess.run(["git", "rev-list", "--objects", "--all"],
                             cwd=ROOT, capture_output=True, timeout=300).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None

    entries = []
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.strip().split(" ", 1)
        if parts and parts[0]:
            entries.append((parts[0], parts[1] if len(parts) > 1 else ""))

    results = {}
    nblob = 0
    for sha, path in entries:
        t = subprocess.run(["git", "cat-file", "-t", sha], cwd=ROOT,
                           capture_output=True).stdout.strip()
        if t != b"blob":
            continue
        nblob += 1
        raw = subprocess.run(["git", "cat-file", "-p", sha], cwd=ROOT,
                             capture_output=True, timeout=120).stdout
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            txt = "\n".join(m.group(0).decode("latin-1")
                            for m in re.finditer(rb"[\x20-\x7e]{6,}", raw))
        if not txt:
            continue
        hits = []
        for i, line in enumerate(txt.splitlines(), 1):
            if any(a.search(line) for a in ALLOW):
                continue
            for level, name, rx in rules:
                for m in rx.finditer(line):
                    hits.append((level, name, i, m.group(0)[:80]))
        if hits:
            results["历史blob %s（%s）" % (sha[:8], path or "路径未知")] = hits
    results["__nblob__"] = nblob      # 元信息，输出时剔除
    return results


def main():
    show_all = "--all" in sys.argv
    verbose = "-v" in sys.argv
    with_history = "--history" in sys.argv

    private, pcount = load_private_terms()
    rules = RULES + private

    results = {}
    scanned = 0
    for r, ds, fs in os.walk(ROOT):
        ds[:] = [d for d in ds if d not in SKIP_DIRS]
        for f in fs:
            p = os.path.join(r, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            if rel in WHITELIST_FILES or rel in LOCAL_ONLY \
                    or rel.endswith(LOCAL_ONLY_SUFFIX):
                continue
            scanned += 1
            h = scan_file(p, rules)
            if h:
                results[rel] = h

    nblob = 0
    nhist = 0
    if with_history:
        hist = scan_history(rules)
        if hist is None:
            print("⚠️ --history：无法读取 git 历史（不是仓库 / 没有 commit）")
        else:
            nblob = hist.pop("__nblob__", 0)
            nhist = len(hist)
            results.update(hist)

    print("=" * 78)
    print("发布前脱敏检验　｜　工作树 %d 个文件%s" % (
        scanned, "　＋　git 历史 %d 个 blob" % nblob if with_history else ""))
    if pcount:
        print("私有词表：已加载 %d 条（sanitize_terms.local.txt）" % pcount)
    else:
        print("私有词表：⚠️ 未找到 sanitize_terms.local.txt —— 只跑通用规则，"
              "查不出特定公司/客户名")
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
        shown = 0
        limit = 6 if rel.startswith("历史blob") else 10 ** 9
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
            if shown >= limit:
                continue
            shown += 1
            mark = {"P0": "🔴", "P1": "🟠", "P2": "🟡"}[level]
            print("     %s [%s] %-22s 第%d行  %s" % (mark, level, name, ln,
                  txt if verbose else txt[:52]))
        if shown < len(seen):
            print("     ……（该版本另有 %d 处命中未逐条列出）" % (len(seen) - shown))

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
