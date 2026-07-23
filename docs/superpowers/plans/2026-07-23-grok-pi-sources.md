# Grok/Pi Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 session-digest 完整支持 Grok 与 Pi 会话的列举、项目过滤、定位与摘要。

**Architecture:** 在单文件 `session_digest.py` 内扩展 `SOURCES`、检测、发现、匹配与两个专用 loader；渲染层不动。同步更新 `SKILL.md` / `README.md`。

**Tech Stack:** Python 3 标准库（`argparse`/`json`/`pathlib`/`re`/`urllib.parse`/`unittest`）

## Global Constraints

- CLI 来源名必须是 `grok` / `pi`（无 `gro` 别名）
- 零第三方依赖
- 能力与 claude/codex/cursor 完整对等（list/project/session/digest/auto/all）
- 不做 Pi 树分支折叠；不读 Grok events/terminal logs
- Python 代码遵循现有文件风格与 type hints

## File Map

| 文件 | 职责 |
|------|------|
| `session_digest.py` | 五来源发现 + load_grok/load_pi + detect + CLI |
| `SKILL.md` | skill 步骤与来源表 |
| `README.md` | 用户文档来源表与参数 |
| `tests/test_grok_pi.py` | 标准库 unittest：loader + 编码匹配（用 tempfile fixture） |

---

### Task 1: Grok/Pi loader + 发现（含测试）

**Files:**
- Create: `tests/test_grok_pi.py`
- Modify: `session_digest.py`

**Interfaces:**
- Produces: `load_grok(path) -> list[dict]`, `load_pi(path) -> list[dict]`, `enc_pi(path) -> str`, `enc_grok(path) -> str`（或内联 urllib），扩展后的 `iter_sessions` / `session_project` / `project_matches` / `detect_harness` / `load_turns` / `resolve_session` / `SOURCES`

- [ ] **Step 1: 写失败测试（loader 核心行为）**

```python
# tests/test_grok_pi.py
import json
import tempfile
import unittest
from pathlib import Path
import session_digest as sd

class TestLoadGrok(unittest.TestCase):
    def test_strips_system_reasoning_keeps_user_query_and_tools(self):
        lines = [
            {"type": "system", "content": "You are Grok"},
            {"type": "user", "content": [{"type": "text", "text": "<user_info>x</user_info>\n<user_query>\nhello\n</user_query>"}]},
            {"type": "reasoning", "id": "r1", "summary": "think"},
            {"type": "assistant", "content": "hi", "tool_calls": [
                {"id": "c1", "name": "read_file", "arguments": "{\"target_file\":\"a.py\"}"}
            ]},
            {"type": "tool_result", "tool_call_id": "c1", "content": "ok"},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "chat_history.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
            turns = sd.load_grok(p)
        roles = [t["role"] for t in turns]
        self.assertEqual(roles, ["user", "assistant"])
        user_text = " ".join(b["text"] for b in turns[0]["blocks"] if b["type"] == "text")
        self.assertIn("hello", user_text)
        self.assertNotIn("user_info", user_text)
        types = [b["type"] for b in turns[1]["blocks"]]
        self.assertIn("tool_use", types)
        self.assertIn("tool_result", types)

class TestLoadPi(unittest.TestCase):
    def test_message_toolcall_and_toolresult(self):
        lines = [
            {"type": "session", "version": 3, "id": "abc", "cwd": "/tmp/proj"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "q"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "nope"},
                {"type": "text", "text": "a"},
                {"type": "toolCall", "id": "t1", "name": "bash", "arguments": {"command": "ls"}},
            ]}},
            {"type": "message", "message": {"role": "toolResult", "toolCallId": "t1", "toolName": "bash",
                "content": [{"type": "text", "text": "out"}], "isError": False}},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
            turns = sd.load_pi(p)
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
        self.assertTrue(any(b.get("type") == "text" and b.get("text") == "a" for b in turns[1]["blocks"]))
        self.assertTrue(any(b.get("type") == "tool_use" and b.get("name") == "bash" for b in turns[1]["blocks"]))
        self.assertTrue(any(b.get("type") == "tool_result" for b in turns[1]["blocks"]))
        self.assertFalse(any(b.get("type") == "thinking" for b in turns[1]["blocks"]))

class TestProjectEnc(unittest.TestCase):
    def test_pi_and_grok_encoding(self):
        path = "/Users/me/Agent/Foo"
        self.assertEqual(sd.enc_pi(path), "--Users-me-Agent-Foo--")
        from urllib.parse import quote
        self.assertEqual(sd.enc_grok(path), quote(path, safe=""))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/lvzhibo/Agent/MySkill/session-digest && python3 -m unittest tests.test_grok_pi -v`
Expected: FAIL（`load_grok` / `load_pi` / `enc_*` 不存在）

- [ ] **Step 3: 实现常量、编码、剥离、loader、发现、detect、接线**

在 `session_digest.py` 中：

1. `from urllib.parse import quote, unquote`
2. 扩展路径常量与 `SOURCES`
3. Grok 注入正则（可复用 Cursor 的 keep：`user_query`；注入含 `user_info`/`git_status` 等）
4. `enc_grok` / `enc_pi`
5. `detect_harness` 增加 grok/pi 分支
6. `load_grok` / `load_pi`；`load_turns` 分发
7. `iter_sessions` / `session_project` / `project_matches` / `resolve_session` 支持两家
8. argparse choices 自动跟 `SOURCES`
9. docstring / help 文案改为五家

关键实现要点（完整写入文件时按现有 ensure 风格）：

```python
GROK_SESSIONS = Path(os.environ.get("GROK_HOME", HOME / ".grok")) / "sessions"
PI_SESSIONS = HOME / ".pi" / "agent" / "sessions"
SOURCES = ("claude", "codex", "cursor", "grok", "pi")

def enc_grok(path: str) -> str:
    return quote(path, safe="")

def enc_pi(path: str) -> str:
    return "--" + path.strip("/").replace("/", "-") + "--"
```

`load_grok`：逐行 type 分发；user 文本经 `_strip`；assistant 合并 tool_calls；tool_result/backend_tool_call 挂到 assistant turn。

`load_pi`：message.role 为 user/assistant/toolResult；toolResult 用 ensure("assistant")。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest tests.test_grok_pi -v`
Expected: OK

- [ ] **Step 5: 对本机真实会话做冒烟**

```bash
python3 session_digest.py --source grok --list 5
python3 session_digest.py --source pi --list 5
python3 session_digest.py --source all --list 10
```

Expected: 表格含 grok/pi 行，无 traceback。

- [ ] **Step 6: Commit**

```bash
git add session_digest.py tests/test_grok_pi.py
git commit -m "$(cat <<'EOF'
feat: 支持 Grok/Pi 会话发现与摘要

扩展五来源对等能力，新增专用 loader 与项目编码匹配。
EOF
)"
```

---

### Task 2: 更新 SKILL.md 与 README

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 的 `--source grok|pi` 行为
- Produces: 文档与脚本行为一致

- [ ] **Step 1: 更新 SKILL.md**

- description / 正文「三家」→ 含 Grok/Pi（或改为「多家」）
- `--source` 说明加入 `grok`/`pi`
- 来源表增加两行路径与剥离项
- 步骤 1 的 agent 身份映射增加：Grok → `--source grok`，Pi → `--source pi`

- [ ] **Step 2: 更新 README.md**

- 支持来源表、安装说明中的「三家」、参数表、场景文案中需要点名的来源列表

- [ ] **Step 3: 对照验证**

Run: `python3 session_digest.py --help`
Expected: choices 含 grok/pi。

- [ ] **Step 4: Commit**

```bash
git add SKILL.md README.md
git commit -m "$(cat <<'EOF'
docs: 文档补充 Grok/Pi 来源说明

与脚本五来源能力对齐。
EOF
)"
```

---

### Task 3: 端到端验收

**Files:** 无代码改动（除非冒烟失败需热修）

- [ ] **Step 1: 按 design 验证清单跑命令**

```bash
# 1-2 list
python3 session_digest.py --source grok --list 5
python3 session_digest.py --source pi --list 5
python3 session_digest.py --source all --list 15

# 3 project（用本机真实存在的项目路径）
python3 session_digest.py --source grok --project /Users/lvzhibo/Agent/SDLCopilot/SDLDaily --last 5 --tools name
python3 session_digest.py --source pi --project /Users/lvzhibo/Agent/SDLCopilot/SDLDaily --last 5 --tools name

# 4-6 tools
python3 session_digest.py --source grok --session <从 list 抄的 id> --tools none --last 3
python3 session_digest.py --source pi --session <从 list 抄的 id> --tools full --last 5
```

Expected: 无报错；摘要无 system/thinking；Grok 无整块 user_info；full 含结果。

- [ ] **Step 2: 全量 unittest**

Run: `python3 -m unittest tests.test_grok_pi -v`
Expected: OK

- [ ] **Step 3: 若有热修则另开 commit；否则完成**
