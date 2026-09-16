# 更新日志

本文件记录每个版本的主要变更。版本号遵循语义化规则（见文末）。
**版本号唯一事实源**是 `cyber_brain.py` 里的 `__version__`，用 `python tools/check_version.py` 校验一致性。

---

## [1.5.0] — 2026-09-16

### 新增
- **Web 输入框提示改为动态生成**：搜索框与「类目/赛道」输入框的示例，改为从当前库的真实类目/标签中取（最多 4 个）。空库时回落到通用文案（`类目名/标签`），因此**不携带任何特定行业示例**，使用者看到的是自己的数据。
- **版本号单一事实源**：`cyber_brain.py` 新增 `__version__`，并提供 `python cyber_brain.py --version`。
- **`tools/check_version.py`**：校验 `__version__` ↔ README 徽章 ↔ git tag 是否一致；支持 `--fix` 同步徽章、`--bump major|minor|patch` 递增版本。

### 变更
- 客户台账的「服务方」实体不再硬编码名称：改为 `CYBER_BRAIN_ROOT_ENTITY` 环境变量指定，未指定时自动取 `serves` 关系最多的 `account` 实体。
- 模块文档与注释统一改为通用表述（去掉特定部署环境的工具链描述）。

### 数据兼容性
无破坏性变更，旧库可直接使用。

---

## [1.4.0] — 2026-09-14

### 新增
- **RRF 多信号混合检索**：FTS(BM25) + LIKE + 实体 + 语义向量四路融合，中文短词（<3 字）也能召回。
- **时间感知检索**：`recall --days N` 只召回最近 N 天；时间衰减排序（`importance=high` 永不衰减）。
- **记忆生命周期管理**：`importance` 自动分级 + 过期降权 + 重复合并（`lifecycle --audit/--apply/--dedupe`）。
- **主动提取**：`summarize.py` 汇总近期 event → 滚动摘要 + 高价值碎片升级。
- **检索审计可视化**：Web 端「检索记录」页签，每次检索的召回来源与命中可回溯。

---

## [1.3.0] — 2026-09-10

### 新增
- **GEO 优化**：新增 `llms.txt`（面向 AI 爬虫的项目导航）、README 增加「AI 快速摘要」结构化块、补充 description 场景词。

---

## [1.2.0] — 2026-09-10

### 新增
- 仓库美化：LICENSE（MIT）、README 徽章、架构图 `docs/architecture.svg`、GitHub Topics。

---

## [1.1.0] — 2026-09-10

### 新增
- **`session_log.py` 会话自动打卡**：一句话记录工作 → 自动分类 + 判重 + 写入 event 碎片与工作日志。
- **MCP 工具** `session_log_tool`（action: log/today/recent）。
- **Web 端「今日」看板**：实时展示当日打卡。

### 变更
- 固化 GitHub 发布规范：`repo/` 为脱敏发布版，禁止用工作目录覆盖。

---

## [1.0.0] — 2026-09-10

### 首个版本
- 单文件 SQLite 存储；FTS5 `trigram` 中文全文检索（≥3 字走索引、<3 字回退 LIKE）。
- 四层数据模型：`content_item` / `kb_document·kb_chunk` / `memory_fragments` / `entity·entity_link`。
- 本地语义向量（`bge-small-zh-v1.5` + fastembed + ONNX，离线可用）。
- 8 类记忆碎片、滚动摘要、实体关系网。
- Web 界面：搜索 / 录入 / 浏览 / 实体关系图 / AI 问答。
- MCP 服务器：把记忆库暴露为标准工具，可接入豆包等客户端。

---

## 版本号规则

| 位 | 何时递增 | 示例 |
|---|---|---|
| **major** | **破坏性变更**：数据库结构不兼容（老库需迁移）、CLI 参数改名或删除、配置格式变化 | 换 SQLite schema、改 CLI 子命令名 |
| **minor** | **新功能**（向后兼容） | 新增检索能力、新增 Web 页面、新增 MCP 工具 |
| **patch** | **修复与文档**：bug、性能、文案、脱敏、README | 修解析错误、补文档 |

**发版约定**

1. 不按时间发版，**攒够一批同类改动再发**（避免一天连发三个版本，版本号失去信息量）。
2. 发版前三件事：改 `__version__` → 跑 `python tools/check_version.py --tag` 确认一致 → 冒烟测试。
3. 数据库结构有变更时，**必须在 Release notes 里写明**是否需要重建索引 / 是否自动迁移。
4. tag 用 `v` 前缀（`v1.5.0`），Release 标题为 `Huiran-cerebro v1.5.0`。
