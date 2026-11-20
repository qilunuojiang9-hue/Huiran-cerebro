# 发版检查清单

发版前按顺序过一遍。**任何一步不过，就不发。**

---

## 1. 脱敏（硬门槛）

```bash
python tools/check_sanitize.py --history
```

必须 `P0 = 0 且 P1 = 0`。

- `P0` = 绝对不能发（公司名、客户名、内部域名、真实路径）
- `P1` = 大概率不该发
- `P2` = 提示，人工扫一眼

> 仓库已装 `.git/hooks/pre-push`，`git push` 时会自动跑这一步，命中即中止。
> **不要用 `--no-verify` 绕过。**

---

## 2. 版本号一致

```bash
python tools/check_version.py        # 校验
python tools/check_version.py --fix  # 不一致时同步 README 徽章
```

**版本号唯一事实源**是 `cyber_brain.py` 的 `__version__`。

按语义化递增：

| 位 | 何时用 |
|---|---|
| major | 数据库结构不兼容、CLI 改名或删除、配置格式变化 |
| minor | 新功能（向后兼容） |
| patch | 修 bug、性能、文档、脱敏 |

---

## 3. 测试

```bash
python tools/test_cyber_brain.py
```

必须全通过。当前基线：**87 条**。

---

## 4. 文档

- `CHANGELOG.md` 增加对应版本条目（含「升级说明」：是否需要迁移 / 重建索引）
- 若数据库结构有变更，**必须在 Release notes 里写明**

---

## 5. 提交与推送

```bash
git add <具体文件>          # 不要用 -A，容易带入不该提交的文件
git commit
git push origin master
git tag -a vX.Y.Z -m "..."
git push origin vX.Y.Z
```

推送后验证：

```bash
git rev-parse HEAD          # 本地 sha
git ls-remote origin master # 远端 sha，两者必须一致
```

---

## 6. 建 Release

```bash
gh release create vX.Y.Z --title "Huiran-cerebro vX.Y.Z" --notes "..."
```

标题格式固定 `Huiran-cerebro vX.Y.Z`。

---

## 常见坑

| 坑 | 说明 |
|---|---|
| **整体覆盖脱敏文件** | `README.md` / `COLLAB.md` / `MCP接入豆包指南.md` 是「两套版本」，本地版含真实信息。**只能增量补丁，不能整体拷贝** |
| **跨库复制用 `SELECT *`** | 老库经多次 `ALTER TABLE` 后列顺序与新库不同，会整体错位。必须显式列名 |
| **`git status` 看到包线符告警** | Windows 的 CRLF 提示，不影响内容，但 `diff` 会显示大量假差异，比对时用 `--strip-trailing-cr` |
| **直接敲 `git push` 绕过检查** | 已有 pre-push hook 兜底；但仍建议走 `发布到GitHub.bat` |
| **忘了补向量索引** | 改了记忆相关代码后，确认 `index_vectors()` 仍被正确调用 |
