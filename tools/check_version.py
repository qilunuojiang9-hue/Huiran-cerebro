#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""版本号一致性校验 / 递增工具

**单一事实源**：`cyber_brain.py` 里的 `__version__`。
其余所有地方（README 徽章、git tag）都必须与它一致 —— 本脚本负责盯着这件事，
避免再出现「发了 v1.4.0 但徽章写着 v1.3.0」这种情况。

用法：
    python tools/check_version.py              # 校验（不一致则退出码 1）
    python tools/check_version.py --fix        # 用 __version__ 覆盖 README 徽章
    python tools/check_version.py --bump minor # 递增版本号并同步徽章
    python tools/check_version.py --tag        # 额外校验最新 git tag

版本号规则（语义化）：
    major  破坏性变更（数据库结构不兼容 / CLI 参数改名 / 配置格式变化）
    minor  新功能（向后兼容）
    patch  修 bug / 文档 / 脱敏
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, "cyber_brain.py")
README = os.path.join(ROOT, "README.md")

VER_RE = re.compile(r'^__version__\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', re.M)
BADGE_RE = re.compile(r'(badge/版本-v)([0-9]+\.[0-9]+\.[0-9]+)(-)')


def read_version():
    t = open(CORE, encoding="utf-8").read()
    m = VER_RE.search(t)
    return m.group(1) if m else None


def read_badge():
    t = open(README, encoding="utf-8").read()
    m = BADGE_RE.search(t)
    return m.group(2) if m else None


def write_version(v):
    t = open(CORE, encoding="utf-8").read()
    t2 = VER_RE.sub('__version__ = "%s"' % v, t, count=1)
    open(CORE, "w", encoding="utf-8", newline="").write(t2)


def write_badge(v):
    t = open(README, encoding="utf-8").read()
    t2 = BADGE_RE.sub(lambda m: m.group(1) + v + m.group(3), t, count=1)
    open(README, "w", encoding="utf-8", newline="").write(t2)


def bump(v, part):
    a, b, c = (int(x) for x in v.split("."))
    if part == "major":
        return "%d.0.0" % (a + 1)
    if part == "minor":
        return "%d.%d.0" % (a, b + 1)
    return "%d.%d.%d" % (a, b, c + 1)


def git_tags():
    r = subprocess.run(["git", "tag", "-l", "v*"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    tags = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]

    def key(t):
        try:
            return tuple(int(x) for x in t.lstrip("v").split("."))
        except ValueError:
            return (0, 0, 0)

    return sorted(tags, key=key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="用 __version__ 覆盖 README 徽章")
    ap.add_argument("--bump", choices=["major", "minor", "patch"])
    ap.add_argument("--tag", action="store_true", help="额外校验最新 git tag")
    a = ap.parse_args()

    if a.bump:
        cur = read_version()
        if not cur:
            print("❌ 读不到 __version__")
            return 2
        new = bump(cur, a.bump)
        write_version(new)
        write_badge(new)
        print("✅ 版本 %s → %s（已同步 README 徽章）" % (cur, new))
        print("   下一步：提交 → git tag v%s → 推送（pre-push 会跑脱敏扫描）" % new)
        return 0

    core, badge = read_version(), read_badge()
    print("=" * 58)
    print("版本号一致性校验")
    print("=" * 58)
    print("  事实源 cyber_brain.py : %s" % (core or "❌ 未找到 __version__"))
    print("  README 徽章           : %s" % (badge or "❌ 未找到徽章"))
    ok = True

    if core and badge and core != badge:
        ok = False
        print("  ❌ 不一致！")
        if a.fix:
            write_badge(core)
            print("  ✅ 已用 %s 覆盖徽章" % core)
            ok = True
    elif core and badge:
        print("  ✅ 一致")

    if a.tag:
        tags = git_tags()
        latest = tags[-1].lstrip("v") if tags else None
        print("  最新 git tag          : %s" % (("v" + latest) if latest else "(无)"))
        if latest and core and latest != core:
            print("  ⚠️  tag 与 __version__ 不一致（发版前正常，发版后需对齐）")
        elif latest:
            print("  ✅ tag 一致")

    print()
    if not ok:
        print("提示：跑 `python tools/check_version.py --fix` 同步徽章")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
