# 更新日志

本文件记录每个版本的主要变更。版本号遵循语义化规则（见文末）。
**版本号唯一事实源**是 `cyber_brain.py` 里的 `__version__`，用 `python tools/check_version.py` 校验一致性。

---

## [1.8.0] — 2026-10-10

> **机制补全版本（收官）**。补上外部审查 7 项 rubric 机制中最后两项，
> 并修掉 6 个在评审外部 PR 时端到端实测挖出的缺陷。
> 按语义化规则记为 **minor**（新增能力，向后兼容）。

至此，Agent Memory Atlas（2026-09-28 审查）指出的 **7 项机制全部落地**。

### 新增：墓碑（软删除）—— `tombstone`（#3）

审查原文：

> "`tombstone`：删除留下可审计的墓碑，而不是物理消失。"

- `memory_fragments` 增加 `deleted_at` 列（幂等迁移，**已用真实库验证数据零丢失**）；
- `delete_fragment()` 打标记而非物理删除 —— 行与正文都保留，
  「这条记忆曾经存在过、何时被删」可以查证，误删也能恢复；
- `restore_fragment()` / `list_deleted_fragments()`；
- **所有读取路径统一加 `deleted_at IS NULL` 谓词**（10 个文件 20 余处），
  并用**源码级护栏测试**守住，防止未来新增读取点时遗漏。
- CLI：`frag --delete <id>` / `--restore <id>` / `--deleted`。

### 新增：人工确认 —— `human_review`（#4）

审查原文：

> "`human_review` is withheld ... **No state waits on a reviewer.**"

- 新增状态 `pending_review` / `rejected`；
- `submit_for_review()` / `approve_fragment()` / `reject_fragment()` / `list_pending_reviews()`；
- 检索侧只认 `active`，所以待审碎片**天然不会**出现在检索与开工上下文里，
  人工确认后才激活；
- CLI：`lifecycle --submit-review <id>` / `--review` / `--approve <id>` / `--reject <id>`。

### 修复

- **`link()` 幂等**（#5）：同一起点重复调用不再新增记录。
  此前 `import` 命令重复运行会不断累积 `entity_link`，
  并把旧行关成零宽区间 `[d, d)`（左闭右开下永远不成立）。
  新增 `lifecycle --clean-zero-width` 清理存量死数据。
- **迁移失败不再静默**（#6）：启动迁移统一走 `_migrate()`，失败会把
  迁移名与原因打到 stderr。此前 `except Exception: pass` 让「约束没生效」
  与「一切正常」长得一模一样。
- **MCP 写入透传 `namespace`**（#7）：`add_memory` / `add_content`
  此前没把该参数传下去，导致通过 MCP 客户端无法写入指定分区。
- **`search` / `recall` 支持 `--namespace`**（#8）：
  底层一直支持，只是 CLI 这层没接 —— 此前命令行用户实际上用不了分区隔离。
- **`update_content` 的列名解析**（#11）：改为按实际表结构判断，
  不再硬编码 `_json` 后缀。此前 `entity_ids` 会拼成 `entity_ids_json`
  并抛 `OperationalError`（该字段列名不带后缀）。
- **`conv --append` 不再误报成功**（#13）：会话不存在、或 `--role`/`--text`
  为空时明确报错并置非零退出码。此前会打印 `appended` 但什么都没做成。

### 测试

`tools/test_cyber_brain.py` 由 51 条增至 **87 条**，新增四个段落：

- 【9】墓碑：正文保留、时间戳、四处读取路径过滤、恢复、审计
- 【10】人工确认：待审不进检索、批准后激活、驳回、幂等保护、审计
- 【11】**老库迁移**：构造缺 `deleted_at` 列的老表，验证能正常打开
- 两处**源码级回归护栏**（`memory_fragments` 查询必须带 `deleted_at` 谓词）

> 两处护栏都经过**负对照验证**：故意移除一处谓词 / 把索引加回 SCHEMA，
> 测试分别报出具体文件行号与 `no such column` 并以退出码 1 失败。

---

## [1.7.1] — 2026-10-10

> **谓词补全修复**。由 **@jianghe9165** 贡献（[#9](https://github.com/qilunuojiang9-hue/Huiran-cerebro/pull/9)）。
> 按语义化规则记为 **patch**（修 bug，不改接口）。

### 修复：`status='active'` 谓词补齐到剩余 6 处 event 查询

1.6.0 修过「已合并（`merged`）的碎片照样被搜出来 / 照样进开工上下文」这一类问题，
但**只改了 `search_memory` 与 `daily_context`**，所有查 `event` 碎片的地方都漏了。
于是被合并掉的历史事件仍然会被算进统计与列表。

已补齐的 6 处：

| 位置 | 影响 |
|---|---|
| `cyber_brain.py` — `event --check` | 昨天有没有漏记的计数 |
| `daily_brief.py` — 今日开工简报 | 「昨天漏记提醒」的计数 |
| `session_log.py` — `is_dup()` | **影响最实际**：此前会把已合并的碎片当成「今天记过」，导致新打卡被误判为重复而**静默跳过** |
| `session_log.py` — `today()` | 今日打卡列表 |
| `session_log.py` — `recent()` | 最近 N 条打卡 |
| `web_ui.py` — `/api/daily` | 今日看板的 event 列表 |

对照组：`summarize.py` 里同一类查询本来就写着 `status='active'`，
说明这是**漏改**而不是有意设计。

### 测试

`tools/test_cyber_brain.py` 由 35 条增至 **39 条**，新增【2b】段落覆盖三个层次：

- **命令行层** —— 真实起子进程断言 `event --check` 只数 active 的 event
- **函数层** —— `session_log` 的三个读取入口都只看 active
- **不变量层** —— **源码级回归护栏**：扫描四个文件，确保所有
  `fragment_type='event'` 的查询都带 `status='active'`（防未来回归）

> 该护栏经过**负对照验证**：故意移除一处谓词后，它会报出具体文件与行号并以退出码 1 失败。

---

## [1.7.0] — 2026-10-09

> **机制补全版本**。回应 Agent Memory Atlas（2026-09-28 审查）中指出的未实现机制。
> 其中两项由 **@jianghe9165** 贡献 —— 这也是本仓库接收的**首个外部 PR**。
> 按语义化规则记为 **minor**（新增能力，向后兼容）。

背景：1.6.0 修掉了「机制声明了但没接线」的一批问题，但那次只覆盖了 7 项 rubric
机制中的 3 项。本版补上其中两项，外加一处遗漏的读取路径。

### 新增：`namespace` 写入路径（[#1](https://github.com/qilunuojiang9-hue/Huiran-cerebro/pull/1)，@jianghe9165）

审查原文：

> "`scope_enforced` is withheld because **nothing writes a namespace** other than `default`."

即：`namespace` 列已存在、检索侧也已支持按它过滤，但**没有任何写入路径会写入
`default` 以外的值** —— 隔离的「读」有了，「写」没有。

- `add_fragment` / `add_entity` / `add_content` / `add_document` 四个写入函数补上
  `namespace` 参数（末尾参数，默认 `None`，落库取值 `namespace or "default"`）；
- CLI 的 `frag` / `entity` / `content` / `doc` 四个子命令各增加 `--namespace`；
- `add_entity` 的判重（`if_exists="skip"`）同步按 namespace 隔离，
  否则跨分区的同名实体会被误判为重复而跳过。

**设计决策（选项 A）**：不传 namespace 时，写入落 `default`、检索返回全部。
这是保持既有语义（`search_memory` 原本即为 `not namespace or r["namespace"] == namespace`），
避免把「不带 namespace 的检索忽然看不到老数据」变成破坏性变更。

### 新增：`entity_link` 保留关系历史（[#2](https://github.com/qilunuojiang9-hue/Huiran-cerebro/pull/2)，@jianghe9165）

审查原文：

> "`bitemporal` is withheld because the validity window on entity links is
> **overwritten in place** and **deleted on expiry**, so the period a relation was
> believed **cannot be recovered**."

- 去掉 `entity_link` 的行级 `UNIQUE(from_id, to_id, relation)`，改为**部分唯一索引**
  只约束「当前有效」的那一条：
  `CREATE UNIQUE INDEX idx_entity_link_open ON entity_link(from_id,to_id,relation) WHERE valid_until IS NULL`；
- `link()` 每次调用**新增一条记录**，不再覆盖、不再删除：显式给 `valid_until` 只插一条
  有界历史；新起点不早于旧起点时旧记录在新起点处关闭（"从这天起改口"）；
- `neighbors(eid, as_of=...)` 新增**时间点查询** —— 传 `as_of` 可查「那一天成立的关系」，
  已失效的历史关系同样返回。时间窗统一按左闭右开 `[valid_from, valid_until)` 判断；
- CLI 新增 `neighbors` 子命令（含 `--as-of`），`link` 新增 `--valid-from` / `--valid-until`；
- **老库启动时幂等重建该表**（检测到行级 UNIQUE 才执行，先建新表 → 拷数据 → 改名），
  数据无损保留。

**行为变化（已在 CHANGELOG 与测试中写明）**：默认视图现在同时尊重 `valid_from`，
失效日按 `>` 而非 `>=` 判断 —— 即「尚未生效」与「失效当天」的关系不再出现在默认视图里。
统一口径是为了让 `as_of` 时间点查询有一致的判断标准。

### 修复

- **`frag --search` 未透传 `namespace`**：`--namespace` 在 `--add` 分支已生效，
  但 `--search` 分支没往下传，导致带 `--namespace` 检索时静默返回全部分区 ——
  参数声明了却不生效。已补上透传。这类「声明了但没接线」正是 1.6.0 修过的那类问题。

### 测试

`tools/test_cyber_brain.py` 由 19 条扩至 **35 条**（新增 namespace 写入路径 6 条、
`entity_link` 时间窗 10 条），全部通过。

---

## [1.6.1] — 2026-10-05

> 文档与项目可见性版本。**不改动任何运行逻辑**，因此按语义化规则记为 patch。
> 起因：1.6.0 修掉了一批「机制声明了但没接线」的问题后，顺带发现
> README 里有几处描述还停留在旧行为，需要一并对齐。

### 文档修正（不是新功能，是纠错）

- **去重行为描述过时**：README 仍写着「可 `--dry-run` 预演」，而 1.6.0 起
  默认就是预演、加 `--apply` 才落库。已改写，并补上 `--unmerge` 与设计取舍说明。
- **数据结构图缺表**：补上 1.6.0 新增的 `memory_mutations`（变更留痕）。
- **测试章节缺关键项**：补上 `tools/test_cyber_brain.py` 与 `tools/check_version.py`，
  并说明测试取向（测命令而非只测函数）。

### 新增文档与资产

- **界面预览**：7 张 Web 界面截图，数据由 `tools/_seed_demo.py` 一键生成（虚构内容）。
- **FAQ**：9 个常见问题（与 Mem0 / Letta / Zep 的区别、为什么用 SQLite、
  中文分词、RRF、隐私、备份、记忆膨胀等）。
- **第三方审阅章节**：如实记录 Agent Memory Atlas 的评级与 1.6.0 的修复对应关系。
- **`llms-full.txt`**：`llms.txt` 的完整版，给 LLM 提供设计取舍与命令参考。
- **`CITATION.cff`**：引用信息（含关键词），便于学术与工具链引用。
- **GitHub Pages 落地页** `docs/index.html`：含 meta / Open Graph /
  JSON-LD（`SoftwareApplication` + `FAQPage`）结构化数据。
- **社交分享预览图** `docs/social-preview.png`（1280×640）。
- **`tools/_seed_demo.py`**：生成虚构演示数据，可复现上述截图。

### 说明

截图与演示数据**全部为编造的示例内容**，不含任何真实业务数据；
生成脚本随仓库发布，任何人都能复现同样的库。

---

## [1.6.0] — 2026-10-05

> 本版是对一份外部代码审查的回应。**Agent Memory Atlas**
> （`neoneye.github.io/agent-memory-atlas/systems/huiran-cerebro/`）在 2026-09-28
> 针对 `2f48deb` 出具了逐行带锚点的报告，指出若干机制「已声明但未接线」。
> 下面每一条都能对应到那份报告的具体指控。

### 修复

- **去重此前永远不落库（最核心的一条）**：命令行分支 `lifecycle --dedupe` 硬编码了
  `dry_run=True`，而 `dedupe_fragments()` 的默认值是 `dry_run=False`——
  唯一调用点偏偏传了预览值，于是重复碎片检测**永远只打印、从不写库**。
  提示语还写着「重跑会实际标记」，实际重跑仍是预览。
  现在与 `--apply` 一致走两段式：默认预演，加 `--apply` 才真正标记。
  同时修正 `--dedupe` 的 help 文案（原文写「保留新者标记」，
  与实际实现「保留先创建者、标记后写者」相反）。
- **合并结果不被检索尊重**：`search_memory()` 以及 `daily_context()` 的三处读取
  （铁律 / 最近决策 / 高价值知识）此前都不带 `status` 谓词，
  标记为 `merged` 的碎片照样被搜出来、照样进开工上下文。已全部补上。
- **语义检索支路同样漏过滤**：`recall()` 按 id 回取碎片时未校验 status，
  已合并但早先建过索引的碎片会保留向量并被取回。已修。
- **带 namespace 调用会直接报错**：`namespace` 列此前只声明在 `memory_fragments` 上，
  但统一搜索的 scoped 分支会向 `entity` / `content_item` / `kb_document` 发送
  `AND namespace=?`，而这三张表没有该列 → SQL 报 `no such column`。
  现已在启动迁移中为这三张表补列（幂等，旧库自动升级）。
- **去重是纯两两全比对**：加长度预筛（Jaccard 不可能超过 min/max 长度比），
  显著降低实际比较量。
- **`tools/_today_smoke.py` 硬编码日期**：写死了 `2026-09-10`，第二天必然失败。改为动态取当天。

### 新增

- **`lifecycle --unmerge <id>`**：撤销合并，把碎片从 `merged` 改回 `active`。
  合并本身不删原文，所以恢复只是状态回滚。
- **变更审计表 `memory_mutations`**：记录「谁改了什么」（merge / unmerge …），
  与既有的 `memory_retrieval_audits`（只记检索）语义互补——
  外部审查指出原审计表记的是**检索**而非**变更**。新增 `list_mutations()` 读取接口。
- **`tools/test_cyber_brain.py`**：首个测试套件（19 条断言）。
  按审查建议「**测命令，而不只是测函数**」，核心断言落在「执行后数据真的变了」这一层——
  正是能抓住上述去重 bug 的那一条。

### 数据兼容性

无破坏性变更。启动时自动迁移（补 namespace 列 + 建 `memory_mutations` 表），
旧库可直接使用。

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
