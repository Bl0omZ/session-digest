# session-digest：减少无效 token 损耗的跨 agent 会话连接 skill



这就是一个简单的 skill。读会话文件、剥离垃圾、输出干净 Markdown。

它解决的问题很实际：节省 token、快速建立上下文、把多个 agent 的会话串起来。

我日常在 Claude Code、Codex、Cursor 之间切来切去。时间一长我注意到一个反复出现的问题：上一个 agent 的工作成果，怎么带到下一个 agent 里？

最朴素的想法是找到会话文件，读进来就完了。实际操作比想象中麻烦得多。

### 光是找文件就够折腾的

三家的会话存储路径完全不同：

- Claude Code：`~/.claude/projects/<编码路径>/<uuid>.jsonl`
- Cursor：`~/.cursor/projects/<编码路径>/agent-transcripts/<id>/<id>.jsonl`
- Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`

让 agent 自己去定位，它得猜目录结构、试路径、来回好几轮。这些探索本身就在烧 token。你还没开始干正事，额度已经花出去一块了。

### 直接读进来会浪费大量无效 token

打开一个 Claude Code 的 `.jsonl`，里面满屏的 `uuid`、`tool_use_id`、`internal_chat_message_metadata_passthrough`，夹杂着 `<system-reminder>`、`<command-stdout>` 这些系统注入块。真正有价值的用户提问和 agent 回复，可能只占文件内容的三分之一。

Cursor 的文件里有 `<manually_attached_skills>`、`<timestamp>`、`turn_ended`。Codex 有 `# AGENTS.md instructions` 前言、`<INSTRUCTIONS>` 注入块、`reasoning` 思考过程。

你把这些文件原样喂给 agent，等于花钱让它消化一堆垃圾。有效信息的密度很低，token 浪费在你根本不关心的元数据上。

### 格式互不兼容

你在 Codex 里想读 Cursor 的会话，得先知道 Cursor 的存储格式，再写剥离逻辑。反过来也一样。三家各玩各的。

所以我写了 session-digest。很简单的一个 skill，帮你省掉上面这些麻烦：自动定位、自动剥离、自动归一化。它本质上是个跨 agent 的会话连接器。

---

## 我实际怎么用的

### Cursor（fable5） 做规划，Codex/Claude 来执行

我的习惯是让 Cursor 的 agent 做前期分析：拆需求、定方案、列任务。规划完了，切到 Codex 或 Claude Code 去写代码。

以前要么手动复制粘贴，要么让 Codex 自己去翻 Cursor 的目录（经常翻半天翻不对）。

现在在 Codex 里说一句：

> "用 session-digest 找到 Cursor 下 my-project 的最新会话"

直接拿到干净的上下文，只有用户问了什么、agent 回了什么。路径怎么找、格式怎么解析，skill 内部处理完了。

Claude Code 里也一样，"帮我读一下 Cursor 那边刚才的会话"就行。

### 长会话的 token 陷阱

这个坑我踩过，分享一下。

Claude Code 和 Cursor（底层也是 Claude）有个机制：会话超过一定时间后，历史消息的 token 会被重新计算。不是接着用剩余额度，是整段历史重新计入消耗。

我的经历：某天晚上跑 Claude Code 把 5 小时限额用完了。第二天早上我在同一个会话里就发了一句话，新的 5 小时额度瞬间见底。整段历史被重新算了一遍。

Cursor 也有这个问题。一个会话放了 1 小时以上再继续，用量统计里会冒出一笔巨额 token 消耗，就是历史重算的代价。

正确做法是重开会话。但重开就断了上下文。

我的解法是在新会话开头让 agent 调 session-digest 把上次会话摘要一下：

> "用 session-digest 读取上一个会话最近 30 条消息，工具调用保留入参"

输出一份精简的交接内容。上下文接上了，历史不用原样带进来，不会触发重新计算。

### 每天用 Codex 回顾昨天的会话

还有一个我每天都在用的场景：早上打开 Codex，先用 session-digest 看一眼昨天的会话，搞清楚上次做到哪了、有哪些建议还没落地、哪些决定还没决策着。这样也能够节省很多的 token

比如昨天的会话摘要出来，我让 agent 帮我整理成 review 格式：

> **今天最该看：定时任务没有自动推进失败的任务**
>
> 发生了什么：某个任务执行失败了，但定时任务没有按预期帮我重试或推进，卡在那里没人管。
>
> 怎么解决的：用户提供了人工复核证据，手动推进了流程，任务进入下一阶段。
>
> 下次怎么避免：任务指令里加一条规则，失败后自动改派或重试，要求 codex 定时任务帮助用户推进失败任务不要死等。
>
> 待你决定：是否把这条规则写进自动化流程的配置里。

一眼就知道昨天卡在哪了、怎么临时解决的、长期该改什么、今天需要我拍板什么。不用翻聊天记录，不用回忆昨晚到底聊到哪了。这比重新打开那个长会话继续聊要省钱得多，原因前面说了，长会话继续会触发历史 token 重算。

---

## 它干了什么

一个纯 Python 脚本，标准库，零额外依赖。做三件事：

1. 自动定位。按当前 agent 环境判断来源（也可以手动指定），找到对应项目最近的会话文件。
2. 剥离噪音。去掉所有无效 ID、时间戳、系统注入块、思考块。三家各自的注入格式都覆盖了。
3. 归一化输出。不管来源是谁，统一输出 Markdown：用户说了什么、agent 回了什么、调了什么工具。

工具调用信息有四档粒度可选。`none` 完全不保留，适合只关心对话内容的场景。`name` 只留工具名，知道调了什么就够了。`input` 保留入参，能看到具体操作了哪些文件、传了什么参数。`full` 连执行结果一起留，适合需要完整复现上下文的情况。

---

## 怎么调

装好 skill 之后，在 Claude Code / Codex / Cursor 里用自然语言说就行：

- "列出我最近的会话" → 输出最近 20 条会话列表
- "读一下 Cursor 那边 my-app 项目的最新会话" → 定位 Cursor 来源，匹配项目
- "跨全部来源看看最近都有哪些会话" → 搜 Claude + Codex + Cursor
- "上个会话最近 20 条消息摘要一下，工具只留名字" → 按粒度输出
- "读上个会话完整内容，输出到 handoff.md" → 落盘成文件

不用记参数。说清楚你想要什么来源、哪个项目、多少条、工具细节到什么程度，agent 会拼好参数去执行。

---

## 总结

一个纯标准库的 Python 脚本包成 skill。它把三家 agent 的会话打通了，你可以在任何一个 agent 里读到另一个 agent 的工作记录，干净的、精简的、不烧冤枉钱的。

核心价值三个：节省 token，快速建立上下文，跨 agent 连接多个会话。
