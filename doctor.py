# -*- coding: utf-8 -*-
"""
赛博大脑 环境自检引导器 (doctor.py)
====================================
定位：赛博大脑 = 自带引导的智能体核心。
数据 + 模型 + 代码全部可拷贝（cyber-brain/ 整个文件夹），
但 Python 环境属于系统级依赖，迁移后运行本脚本自检并引导安装。

用法：
    python doctor.py             # 自检并输出报告（缺什么一目了然）
    python doctor.py --fix       # 自检 + 自动安装缺失的 pip 包
    python doctor.py --model     # 检查/提示向量模型缓存状态

输出：PASS / FAIL 报告，FAIL 项附带修复指引。
"""
import importlib.util
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "cyber_brain.db")
MODEL_CACHE = os.path.join(ROOT, ".model_cache")
REQ_FILE = os.path.join(ROOT, "requirements.txt")

PASS, FAIL, WARN = "✅", "❌", "⚠️"


def check_python():
    """检查 Python 版本"""
    v = sys.version_info
    ok = v >= (3, 10)
    msg = f"Python {v.major}.{v.minor}.{v.micro}（要求 ≥3.10）"
    return (PASS if ok else FAIL), msg


# pip 包名 → import 模块名 映射（两者不一致的包）
IMPORT_ALIASES = {
    "python-docx": "docx",
    "python-pptx": "pptx",
    "python-multipart": "multipart",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
}


def parse_requirements():
    """从 requirements.txt 解析 (pip包名, import模块名) 列表"""
    pkgs = []
    if not os.path.exists(REQ_FILE):
        return pkgs
    with open(REQ_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_\-\.\[\]]+)([<>=!~].*)?$", line)
            if m:
                pip_name = m.group(1).split("[")[0]
                import_name = IMPORT_ALIASES.get(pip_name, pip_name.replace("-", "_"))
                pkgs.append((pip_name, import_name))
    return pkgs


def check_packages():
    """逐个 import 检查依赖包"""
    results = []
    for pip_name, import_name in parse_requirements():
        spec = importlib.util.find_spec(import_name)
        if spec is None:
            results.append((FAIL, f"缺少包: {pip_name}（运行 pip install -r requirements.txt 或 python doctor.py --fix）"))
        else:
            results.append((PASS, f"包已装: {pip_name}"))
    return results


def check_model_cache():
    """检查 fastembed 向量模型缓存（bge-small-zh-v1.5）是否随目录迁移"""
    # fastembed 缓存目录结构：.model_cache/BAAI/bge-small-zh-v1.5/{model.onnx, tokenizer.json, ...}
    has_model = os.path.isdir(MODEL_CACHE) and any(
        os.path.exists(os.path.join(r, f))
        for r, _dirs, files in os.walk(MODEL_CACHE)
        for f in files
        if f.endswith(".onnx")
    )
    if has_model:
        return (PASS, f"向量模型缓存存在: {MODEL_CACHE}（离线可检索 ✅）")
    return (WARN, "向量模型缓存缺失。首次运行会联网下载（约 100MB），或把旧机的 .model_cache/ 整个拷过来即可离线。")


def check_db():
    ok = os.path.exists(DB_PATH)
    size = os.path.getsize(DB_PATH) / 1024 / 1024 if ok else 0
    msg = f"数据库 {'存在' if ok else '缺失'}（{size:.1f} MB）" if ok else "数据库缺失！无法检索，需从旧机拷贝 cyber_brain.db"
    return (PASS if ok else FAIL), msg


def auto_fix():
    """自动安装缺失的 pip 包"""
    missing = [pip_name for pip_name, import_name in parse_requirements()
               if importlib.util.find_spec(import_name) is None]
    if not missing:
        print("所有依赖已齐全，无需安装。")
        return
    print(f"检测到缺失: {', '.join(missing)}，开始安装...")
    cmd = [sys.executable, "-m", "pip", "install", "-r", REQ_FILE]
    print("$", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode == 0:
        print("✅ 依赖安装完成，重新运行 doctor.py 验证。")
    else:
        print("❌ 安装失败，请检查网络或 pip 源（如使用镜像: -i https://pypi.tuna.tsinghua.edu.cn/simple）")


def main():
    print("=" * 52)
    print("  赛博大脑 环境自检 (doctor.py)")
    print("=" * 52)

    results = []
    results.append(("Python", *check_python()))
    results.append(("数据库", *check_db()))
    results.append(("模型缓存", *check_model_cache()))
    for flag, msg in check_packages():
        results.append(("依赖", flag, msg))

    has_fail = False
    for cat, flag, msg in results:
        if flag == FAIL:
            has_fail = True
        print(f"{flag} [{cat}] {msg}")

    print("=" * 52)
    if has_fail:
        print("结论: 存在 FAIL 项，需处理后再使用。可运行: python doctor.py --fix")
    else:
        print("结论: 环境就绪 ✅ 赛博大脑可正常检索/启动")

    if "--fix" in sys.argv:
        print("\n--- 开始自动修复 ---")
        auto_fix()


if __name__ == "__main__":
    main()
