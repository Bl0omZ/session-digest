---
name: session-digest
description: 会话摘要——把 Claude Code / Codex / Cursor / Grok / Pi 的会话记录压成可读 Markdown：默认按当前运行环境定位会话，剥离 uuid/时间戳/工具调用 ID 与系统指令注入，保留用户问题与 agent 回复，工具调用细节按 --tools 粒度保留。用户想查看或恢复某个会话、跨多家 agent 找回历史会话、导出或归档会话、把会话交接给另一个 agent、从会话写复盘或总结时使用。
---

# 会话摘要

把 Claude Code / Codex / Cursor / Grok / Pi 的会话记录压成可读 Markdown。各来源归一化到同一套结构后共用一个渲染器，输出统一。剥离无效 ID 与系统/指令注入块，保留用户问题与 agent 回复；工具调用细节按 `--tools` 粒度保留。

## 步骤

1. 选定来源并定位会话。**你自己知道跑在哪个 agent 里，调用时直接用 `--source` 指定对应来源**：Claude Code → `--source claude`，Codex → `--source codex`，Cursor → `--source cursor`，Grok → `--source grok`，Pi → `--source pi`。只有你确实无法确定自己所在环境时，才省略 `--source`（默认 `auto`，由脚本读环境变量自行判断，仍判断不出则搜全部来源）。定位到所选来源下当前项目最近修改的会话。
   - 不知道要找哪个会话时，先用 `--list [N]`（默认 20）列出最近会话；跨来源看全部用 `--source all --list`，按项目过滤用 `--project <路径或子串>`。
   - 用 `--session <id|路径>` 恢复指定会话，在所选来源内匹配（`--source all` 时跨全部来源）。Grok 也可传会话目录（自动读其中的 `chat_history.jsonl`）。
   - 完成判据：脚本定位到唯一会话且零报错。`--list` 列出候选、或 `--session` 多命中时（输出带 `[来源]` 前缀），复述给用户请其用更长 ID 或完整路径消歧。
2. 用 `--tools` 控制工具调用粒度（默认 `name`）：`none` 全丢 / `name` 仅工具名 / `input` 名+入参 / `full` 名+入参+结果（结果默认截断 50 行，`--no-truncate` 不截）。
3. 大会话用 `--last N` 取最近 N 条消息；输出用 `-o <file>` 落盘，默认 stdout。
4. 执行 `python3 <SKILL_DIR>/session_digest.py …`，把输出交给用户或按要求 `-o` 写文件。
   - 完成判据：脚本零报错退出，输出含用户与 agent 的对话回合，且不含 `uuid`/工具调用 ID 等原始标识与系统注入块。

## 参数

| 参数 | 默认 | 作用 |
|---|---|---|
| `--source <来源>` | `auto` | 优先由 agent 按自身身份指定 `claude`/`codex`/`cursor`/`grok`/`pi`；`auto` 让脚本读环境变量判断；`all` 跨全部来源 |
| `--list [N]` | 关（`N`=20） | 列出最近 N 条会话供选择，不解析内容 |
| `--project <路径\|子串>` | 当前目录 | 真实路径按项目精确定位；子串按项目标签模糊过滤 |
| `--session <id\|路径>` | 最新会话 | 会话 ID 或 `.jsonl` 路径，跨来源匹配 |
| `--tools <级>` | `name` | 工具调用粒度：`none`/`name`/`input`/`full` |
| `--last <N>` | `0`（全量） | 只取最近 N 条消息 |
| `--no-truncate` | 关 | `full` 下不截断工具结果 |
| `-o <file>` | stdout | 输出文件路径 |

## 来源与剥离规则

| 来源 | 会话路径 | 剥离项（除通用 ID/时间戳外） |
|---|---|---|
| Claude Code | `~/.claude/projects/<编码路径>/<id>.jsonl` | `<system-reminder>`/`<command-*>` 等注入块；`<command-args>` 内为真实提问，保留 |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` | `# AGENTS.md instructions` 前言、`<INSTRUCTIONS>`/`<environment_context>`/`<skill>` 注入块、`developer` 角色消息、`reasoning`（思考） |
| Cursor | `~/.cursor/projects/<编码路径>/agent-transcripts/<id>/<id>.jsonl` | `<manually_attached_skills>`/`<timestamp>` 等注入块、`turn_ended` 元数据行；`<user_query>` 内为真实提问，保留 |
| Grok | `~/.grok/sessions/<URL编码cwd>/<id>/chat_history.jsonl` | `system`/`reasoning`；`<system-reminder>`/`<user_info>`/`<git_status>` 等注入；`<user_query>` 内为真实提问，保留 |
| Pi | `~/.pi/agent/sessions/--<path>--/<ts>_<uuid>.jsonl` | `thinking`；`session`/`model_change` 等元数据行 |

统一剥离：各类 `uuid`/`call_id`/`tool_use_id`/`internal_chat_message_metadata_passthrough` 等无效 ID、原始时间戳、思考块。统一保留：用户文本、agent 文本、工具调用（按 `--tools` 粒度）、图片（标注 `[图片]`）。
