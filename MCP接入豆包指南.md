# 赛博大脑 MCP 服务器 — 接入豆包指南

把赛博大脑（`C:/cyber-brain/cyber_brain.db`）暴露成 MCP 服务，让豆包等客户端能直接「读记忆、写记忆、查知识库」。

## 一、豆包连接参数（你问的三个）

| 配置项 | 值 |
|---|---|
| **服务器名称** | `cyber-brain` |
| **传输类型** | `HTTP` |
| **服务器 URL** | `http://127.0.0.1:8765/mcp` |

## 二、启动 MCP 服务器

**方式 1：双击脚本（推荐）**
双击 `C:\cyber-brain\start_mcp_server.bat`，看到 `赛博大脑 MCP 服务器 启动` 即成功。**保持窗口开着**（关窗口 = 停服务）。

**方式 2：命令行**
```bash
cd C:\cyber-brain
C:\Users\Adminn\.workbuddy\binaries\python\envs\default\Scripts\python.exe mcp_server.py --port 8765
```

**验证**：浏览器访问 `http://127.0.0.1:8765/mcp`，出现 `Bad Request: Missing session ID` 是**正常的**（说明服务在监听）；如果是连接失败/拒绝连接，说明没启动。

## 三、豆包 PC 端接入（自定义连接器）

1. 打开豆包 PC 端（doubao.com 下载）
2. 左侧菜单 → **技能 → 连接器 → 伙伴**
3. 右上角 **新建** → **新建自定义连接器**
4. 填写：
   - 服务器名称：`cyber-brain`
   - 传输类型：`HTTP`
   - 服务器 URL：`http://127.0.0.1:8765/mcp`
5. 保存
6. 新工作任务里输入：**"使用 cyber-brain，都有哪些工具"** — 若返回工具目录即接入成功

## 四、可用工具（7 个）

> ⚠️ **豆包对自定义 MCP 连接器有工具数量上限（实测加载 6-7 个）**，超出部分不加载。本服务器已把 12 个能力合并成 **6 个工具**，低频能力通过 mode 参数切换，**功能不丢失**。

| 工具 | 作用 | 合并的低频能力 |
|---|---|---|
| `recall` | 综合查询：记忆 / 知识库 / 全部 / 今日上下文（mode 切换） | 原 list_fragments、search_kb、daily_context |
| `search` | 全库搜索（文档/知识库/碎片/实体/词库） | — |
| `add_memory` | **写入记忆碎片**（fact/preference/decision/iron_rule 等 8 类） | — |
| `add_content` | 写入知识库文档（长文/报告/资料） | — |
| `stats` | 知识库统计 / 冲突检测 / 系统台账（mode 切换） | 原 detect_conflicts、get_profile |
| `entity` | 实体搜索 / 1 跳邻居 / 台账（mode 切换） | 原 search_entities、neighbors、get_profile |

**mode 参数说明：**
- `recall(query, mode, days)`：`memory` 记忆（默认）/ `kb` 知识库 / `all` 全部 / `daily` 今日开工上下文
- `stats(mode)`：`stats` 统计（默认）/ `conflicts` 冲突检测 / `profile` 系统台账
- `entity(q, mode, eid)`：`search` 搜索（默认）/ `neighbors` 关系邻居（需 eid）/ `profile` 台账

## 五、把「豆包记忆」存进赛博大脑

豆包没有官方记忆导出。两条路：

**路 A（对话导出 + MCP 写入）**
1. 豆包聊天页右上角 `···` → 导出聊天记录（txt/json）
2. 把文件发给 WorkBuddy，我用 `add_memory` 分类（fact/preference/decision…）批量入库

**路 B（日常让豆包自己存）**
在豆包对话里直接说：
> 把「XXXX」记到 cyber-brain 的 memory，类型 fact

豆包会调用 `add_memory` 工具写入赛博大脑。日常聊天里顺手让它记，长期积累。

## 六、常见问题

- **豆包报「连接失败」**：先确认 MCP 服务器窗口是否开着（`http://127.0.0.1:8765/mcp` 能访问）。
- **端口被占**：换端口启动 `python mcp_server.py --port 9000`，豆包 URL 同步改成 `http://127.0.0.1:9000/mcp`。
- **换机使用**：把 `C:\cyber-brain\` 整个拷走，装好依赖后同样方式启动。
- **手机豆包**：目前豆包移动端 MCP 支持有限，主要用 PC 端连接；手机端记录可通过同账号同步后在 PC 端导出。
