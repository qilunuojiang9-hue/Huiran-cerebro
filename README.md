# Huiran-cerebro · 赛博大脑

个人/团队记忆中枢与知识库引擎。单文件 SQLite，零服务依赖，融合了「知识库 RAG + 记忆碎片 + 实体关系 + AI 检索」四层能力，可作 AI 助手的外接记忆（支持 MCP，已适配豆包等客户端）。

> **一句话**：把 AI 的「记忆」和「知识」沉淀成本地可检索、可对话的私有知识库。

---

## 特性

- **单文件存储**：SQLite 单库（`cyber_brain.db`），备份 = 拷文件，换机零迁移成本
- **中文检索优化**：FTS5 `trigram` 分词（中文按 3 字滑窗），≥3 字走全文索引、<3 字自动回退 LIKE，不丢短词
- **四层数据模型**：
  - `content_item` 内容实体（笔记/文章/任务/决策）
  - `kb_document/kb_chunk` RAG 知识库（自动分块、向量列预留）
  - `memory_fragments` 记忆碎片（fact/preference/emotion/knowledge/decision/iron_rule/event/pitfall）
  - `entity/entity_link` 实体关系网（人/组织/项目/账号/平台/产品）
- **语义检索**：本地 `bge-small-zh-v1.5` 向量（fastembed + ONNX，离线可用）
- **记忆防遗忘**：`recall` 带回「滚动摘要 + 记忆碎片 + 关联实体」，长会话开工即带上文
- **Web 界面**：搜索 / 录入 / 浏览 / 实体关系图 / AI 问答，开箱即用
- **MCP 服务器**：把记忆库暴露为标准 MCP 工具，可接入豆包等支持 MCP 的 AI 客户端

---

## 快速开始

### 环境

- Python 3.10+
- 依赖见 `requirements.txt`（`pip install -r requirements.txt`）
- 语义检索首次需联网下载模型（已配置 `hf-mirror.com` 镜像加速）

### 初始化

```bash
# 1. 建库（自动建表）
python cyber_brain.py --db cyber_brain.db init

# 2. 写入一条记忆碎片
python cyber_brain.py --db cyber_brain.db frag --add --type fact --content "今天是周五" --subject work

# 3. 查询记忆
python cyber_brain.py --db cyber_brain.db recall "今天"

# 4. 统一搜索（一次命中实体+内容+记忆+知识库+关键词组）
python cyber_brain.py --db cyber_brain.db search "关键词"
```

### Web 界面

```bash
# 启动 Web（默认 http://127.0.0.1:8899）
python web_ui.py
# 或 Windows 双击 start_web.bat
```

### MCP 接入（AI 客户端用）

```bash
# 启动 MCP 服务器（默认 http://127.0.0.1:8765/mcp）
python mcp_server.py
# 或 Windows 双击 start_mcp_server.bat
```

豆包等客户端配置：服务器名称 `cyber-brain` / 传输类型 `HTTP` / URL `http://127.0.0.1:8765/mcp`。
详见 `MCP接入豆包指南.md`。

---

## 命令行速查

```bash
# 实体（人/组织/项目/账号/产品）
python cyber_brain.py --db cyber_brain.db entity --add --type client --name "某公司" --org "某集团"
python cyber_brain.py --db cyber_brain.db link --from 1 --to 2 --relation belongs_to

# 内容（笔记/任务/决策）
python cyber_brain.py --db cyber_brain.db content --add --title "标题" --body "正文" --type note --cat 分类

# 知识库文档（自动分块可检索）
python cyber_brain.py --db cyber_brain.db doc --add --title "文档名" --text "长文本..."

# 记忆碎片
python cyber_brain.py --db cyber_brain.db frag --add --type decision --content "决定采用方案A" --subject work

# 滚动摘要（收尾写一条，次日 recall 带回）
python cyber_brain.py --db cyber_brain.db summary --add --scope work --summary "今天完成了..."

# AI 会话落库
python cyber_brain.py --db cyber_brain.db conv --add --title "会话名" --session 2026-01-01
python cyber_brain.py --db cyber_brain.db conv --append --id 1 --role user --text "..."
```

完整命令：`python cyber_brain.py --help`

---

## 数据结构

```
entity ──< entity_link >── entity        # 工作对象 + 关系网
content_item (+ content_fts)             # 笔记/文章/任务/决策 统一实体
kb_document ─< kb_chunk ─< kb_embedding  # RAG 知识库（向量列预留）
ai_conversation                          # AI 会话落库
master_data / keyword_pack               # 字典 / 关键词组
ingest_source / ingest_record            # 数据接入 + 授权登记
memory_fragments (+ fragment_fts)        # 记忆碎片（8 类）
rolling_summaries                        # 滚动摘要 checkpoint
memory_relations                         # 碎片间关系
memory_retrieval_audits                  # 检索留痕
```

## 向量检索

- 模型：`BAAI/bge-small-zh-v1.5`（512 维，fastembed + ONNX Runtime）
- 重建索引：`python cyber_brain.py --db cyber_brain.db index`
- 语义搜索：`python cyber_brain.py --db cyber_brain.db vecsearch "词"`
- 未来可平滑迁移 pgvector（PostgreSQL）以支持更大规模

---

## 测试

```bash
# Web 界面冒烟（需 Playwright）
python tools/_frontend_smoke.py
# 图谱冒烟
python tools/_graph_smoke.py
# 碎片去重扫描（只读）
python tools/_dup_scan.py
```

## 项目结构

```
cyber_brain.py          # 核心引擎（SQLite + FTS5 + 向量 + 记忆）
web_ui.py               # Web 界面（Flask，搜索/录入/浏览/实体图/AI 问答）
mcp_server.py           # MCP 服务器（12 能力合并 6 工具，适配豆包）
daily_brief.py          # 每日开工上下文生成
doctor.py               # 环境自检（--fix 自动修）
requirements.txt        # 依赖
tools/                  # 测试与工具脚本
```

---

## License

MIT
