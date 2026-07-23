# Design: session-digest 增加 Grok / Pi 来源

**日期:** 2026-07-23  
**状态:** 已批准（方案 1 · 单文件扩展 · 完整对等）

## 目标

在现有 Claude / Codex / Cursor 会话摘要能力上，增加 **Grok** 与 **Pi** 两家来源，能力与现有三家完整对等：`--list` / `--project` / `--session` / 摘要 / `auto` 环境识别 / `--source all`。

CLI 来源名：`grok`、`pi`（不用 `gro` 简写）。

## 架构

仍为单文件 `session_digest.py`。五家来源归一到同一套 turn 结构，共用现有渲染器。

```
--source auto|all|claude|codex|cursor|grok|pi
        │
        ▼
  detect_harness / resolve_scope
        │
        ▼
  iter_sessions → project_matches → resolve_session / default_session
        │
        ▼
  load_turns(source)  ← 新增 load_grok / load_pi
        │
        ▼
  digest → turn_to_md（现有渲染，不动）
```

`SOURCES = ("claude", "codex", "cursor", "grok", "pi")`。

## 会话路径

| 来源 | 路径 | 会话实体 |
|------|------|----------|
| Grok | `~/.grok/sessions/<URL编码cwd>/<id>/chat_history.jsonl` | 目录内的 `chat_history.jsonl` |
| Pi | `~/.pi/agent/sessions/--<path>--/<ts>_<uuid>.jsonl` | 单个 `.jsonl` |

`GROK_HOME` 可覆盖 Grok 根目录（默认 `~/.grok`）。Pi 固定 `~/.pi/agent/sessions`。

## 环境识别

- Grok：`GROK_HOME` / `GROK_AGENT` / `AI_AGENT` 以 `grok` 开头
- Pi：`PI_CODING_AGENT` / `AI_AGENT` 以 `pi` 开头

## 发现与项目匹配

### 枚举

- Grok：glob `sessions/*/*/chat_history.jsonl`，sid = 父目录名（uuid）
- Pi：glob `sessions/*/*.jsonl`，sid = 文件名中 `_` 后的 uuid；mtime 用文件本身

### 项目标签

- Grok：优先读同目录 `summary.json` 的 `info.cwd`；失败则对编码目录名 `urllib.parse.unquote`
- Pi：读首行 `type=="session"` 的 `cwd`；失败则用目录名 `--path--`

### 匹配

- 真实路径（以 `/` 开头）：与 cwd 精确相等
- Grok 编码对照：URL 百分号编码路径
- Pi 编码对照：`/` → `-`，两侧加 `--`（与 Pi 文档一致）
- 子串：匹配 cwd 或编码目录名

### 路径直传

- 文件落在对应根下则判定来源
- Grok 可传会话目录，自动拼 `chat_history.jsonl`；目录内无该文件则报错退出

## Loader

### `load_grok`

读 `chat_history.jsonl`：

- 丢弃：`system`、`reasoning`
- `user`：content 为 str 或 `[{type:text}]`；剥离 `<system-reminder>` / `<user_info>` / `<git_status>` 等注入；保留 `<user_query>` 内正文
- `assistant`：文本 + `tool_calls[]` → `tool_use`（arguments 为 JSON 字符串则 parse）
- `tool_result` → `tool_result`；`backend_tool_call` → `tool_use`（name 取 `kind.name`）
- 相邻同 role 合并为同一 turn（ensure 模式）

### `load_pi`

- 只处理 `type=="message"`
- `user` / `assistant`：保留 `text`、`toolCall`→`tool_use`、`image`→`[图片]`；丢 `thinking`
- `toolResult`：归入 assistant turn 的 `tool_result`（`isError` → `is_error`）
- 跳过 `session` / `model_change` / `thinking_level_change` 等元数据
- 树结构（`parentId`）：按文件行序线性读，不做分支折叠

## 文档

同步更新 `SKILL.md`、`README.md` 的来源表与 `--source` 说明。

## 错误处理

- 目录不存在：该来源静默跳过
- JSONL 坏行：跳过
- `summary.json` 读失败：回退 URL 解码目录名
- `--session` 多命中：列出来源+路径，要求更长 ID
- Grok 会话目录无 `chat_history.jsonl`：明确报错

## 明确不做

- Pi 会话树分支折叠 / 只走 active leaf
- Grok `events.jsonl` / terminal logs
- 引入第三方测试依赖（可用标准库 `unittest` 或手工 CLI 验证）

## 验证计划

1. `--source grok --list` / `--source pi --list` 列出本机会话
2. `--source all --list` 五家混排按 mtime
3. 按项目路径默认取到对应来源最近会话
4. `--session <短 uuid>` 消歧或唯一命中
5. 摘要含用户/agent 与工具名；无 system/thinking/reasoning；Grok 无整块 `<user_info>`
6. `--tools full` / `none` 行为正确
7. 文档已更新
