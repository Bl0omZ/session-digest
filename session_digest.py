#!/usr/bin/env python3
"""会话摘要：把 Claude Code / Codex / Cursor 会话压成可读 Markdown。

三个来源归一化到同一套 turn 结构后共用一个渲染器：
- Claude Code：~/.claude/projects/<编码路径>/<id>.jsonl
- Codex     ：~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl
- Cursor    ：~/.cursor/projects/<编码路径>/agent-transcripts/<id>/<id>.jsonl

剥离各来源的无效 ID 与系统/指令注入块，保留用户问题与 agent 回复，
工具调用细节按 --tools 粒度保留。默认按当前运行环境自动判断查哪个来源。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CODEX_SESSIONS = HOME / ".codex" / "sessions"
CURSOR_PROJECTS = HOME / ".cursor" / "projects"

SOURCES = ("claude", "codex", "cursor")
TOOL_RESULT_TRUNC_LINES = 50
CODEX_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

# —— 各来源的注入剥离规则 ——
# Claude：成对注入标签块；command-args 内是真实提问，单独保留。
CLAUDE_INJECTION_RE = re.compile(
    r"<(command-name|command-message|local-command-stdout|local-command-stderr"
    r"|local-command-caveat|system-reminder|command-stdout|error-message)>.*?</\1>",
    re.DOTALL,
)
CLAUDE_KEEP_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
# Cursor：注入块；user_query 内是真实提问，单独保留。
CURSOR_INJECTION_RE = re.compile(
    r"<(manually_attached_skills|timestamp|additional_data|attached_files"
    r"|current_file|user_info|available_instructions)>.*?</\1>",
    re.DOTALL,
)
CURSOR_KEEP_RE = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL)
# Codex：AGENTS.md 前言 + 指令/环境/技能注入块。
CODEX_INJECTION_RE = re.compile(
    r"<(INSTRUCTIONS|environment_context|skill|user_instructions)>.*?</\1>",
    re.DOTALL,
)
CODEX_PREAMBLE_RE = re.compile(r"^#\s*AGENTS\.md instructions\s*", re.IGNORECASE)


# ============================ 环境判断 ============================
def detect_harness() -> str | None:
    """按环境变量判断当前跑在哪个 agent 里，判断不出返回 None。"""
    e = os.environ
    ai = (e.get("AI_AGENT") or "").lower()
    # macOS 下各家桌面端会给终端注入 __CFBundleIdentifier，
    # Codex Desktop = com.openai.codex，Cursor 含 "cursor"。
    bundle = (e.get("__CFBundleIdentifier") or "").lower()
    if e.get("CLAUDECODE") or e.get("CLAUDE_CODE_SESSION_ID") or ai.startswith("claude"):
        return "claude"
    if e.get("CODEX_SANDBOX") or e.get("CODEX_HOME") or ai.startswith("codex") or "codex" in bundle:
        return "codex"
    if (e.get("CURSOR_AGENT") == "1" or e.get("CURSOR_TRACE_ID")
            or ai.startswith("cursor") or "cursor" in bundle):
        return "cursor"
    return None


# ============================ 文本剥离 ============================
def _strip(text: str, inject_re: re.Pattern, keep_re: re.Pattern | None) -> str:
    """剥离注入块；keep_re 命中的内容视为真实提问接回为纯文本。"""
    if not isinstance(text, str):
        return ""
    kept = [a.strip() for a in keep_re.findall(text)] if keep_re else []
    kept = [k for k in kept if k]
    text = inject_re.sub("", text)
    if keep_re:
        text = keep_re.sub("", text)
    body = text.strip()
    if kept:
        body = "\n".join([body] + kept) if body else "\n".join(kept)
    return body


def strip_text(text: str, source: str, role: str) -> str:
    if source == "claude":
        return _strip(text, CLAUDE_INJECTION_RE, CLAUDE_KEEP_RE)
    if source == "cursor":
        return _strip(text, CURSOR_INJECTION_RE, CURSOR_KEEP_RE)
    if source == "codex" and role == "user":
        return _strip(CODEX_PREAMBLE_RE.sub("", text), CODEX_INJECTION_RE, None)
    return text.strip() if isinstance(text, str) else ""


# ============================ 渲染层 ============================
def truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    return "\n".join(lines[:limit]) + f"\n…[截断，共 {len(lines)} 行]"


def _tool_result_text(content) -> str:
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(json.dumps(c, ensure_ascii=False))
        return "\n".join(parts)
    return "" if content is None else str(content)


def block_to_md(block: dict, tools: str, no_trunc: bool) -> str:
    t = block.get("type")
    if t == "text":
        return block.get("text", "")
    if t in ("thinking", "reasoning"):
        return ""
    if t == "tool_use":
        if tools == "none":
            return ""
        name = block.get("name", "?")
        if tools == "name":
            return f"> **[{name}]**"
        inp = json.dumps(block.get("input", {}), ensure_ascii=False, indent=2)
        return f"> **[{name}]**\n> 入参:\n```json\n{inp}\n```"
    if t == "tool_result":
        if tools != "full":
            return ""
        text = _tool_result_text(block.get("content"))
        err = " [错误]" if block.get("is_error") else ""
        if not no_trunc:
            text = truncate(text, TOOL_RESULT_TRUNC_LINES)
        return f"> **结果{err}:**\n```\n{text}\n```"
    if t == "image":
        return "[图片]"
    return ""


def turn_to_md(turn: dict, tools: str, no_trunc: bool) -> str:
    role = turn["role"]
    ts = turn.get("ts") or ""
    head = {"user": "用户", "assistant": "agent"}.get(role, role)
    head_ts = f" · {ts}" if ts else ""
    parts = []
    for b in turn["blocks"]:
        if b.get("type") == "text":
            s = b.get("text", "").strip()
        else:
            s = block_to_md(b, tools, no_trunc)
        if s:
            parts.append(s)
    body = "\n\n".join(parts)
    if not body:
        return ""
    return f"## {head}{head_ts}\n\n{body}"


def fmt_ts(iso: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", iso or "")
    return f"{m.group(1)} {m.group(2)}" if m else ""


# ============================ 三个 loader ============================
def _anthropic_turns(path: Path, source: str, role_field: str) -> list[dict]:
    """Claude / Cursor 共用：每行一条 {role/type, message:{content}}。"""
    turns: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = o.get(role_field)
            if role not in ("user", "assistant"):
                continue
            content = (o.get("message") or {}).get("content")
            blocks: list[dict] = []
            if isinstance(content, str):
                s = strip_text(content, source, role)
                if s:
                    blocks.append({"type": "text", "text": s})
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        s = strip_text(b.get("text", ""), source, role)
                        if s:
                            blocks.append({"type": "text", "text": s})
                    else:
                        blocks.append(b)
            if blocks:
                turns.append(
                    {"role": role, "ts": fmt_ts(o.get("timestamp", "")), "blocks": blocks}
                )
    return turns


def load_codex(path: Path) -> list[dict]:
    """Codex rollout：按 response_item 归组成 user/assistant turn。"""
    turns: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur and cur["blocks"]:
            turns.append(cur)
        cur = None

    def ensure(role: str):
        nonlocal cur
        if cur is None or cur["role"] != role:
            flush()
            cur = {"role": role, "ts": "", "blocks": []}

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "response_item":
                continue
            p = o.get("payload") or {}
            pt = p.get("type")
            if pt == "message":
                role = p.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = "\n".join(
                    b.get("text", "")
                    for b in (p.get("content") or [])
                    if isinstance(b, dict)
                )
                text = strip_text(text, "codex", role)
                if text:
                    ensure(role)
                    cur["blocks"].append({"type": "text", "text": text})
            elif pt in ("function_call", "custom_tool_call", "tool_search_call"):
                ensure("assistant")
                args = p.get("arguments")
                try:
                    inp = json.loads(args) if isinstance(args, str) else (args or {})
                except json.JSONDecodeError:
                    inp = {"raw": args}
                cur["blocks"].append(
                    {"type": "tool_use", "name": p.get("name") or pt, "input": inp}
                )
            elif pt in (
                "function_call_output",
                "custom_tool_call_output",
                "tool_search_output",
            ):
                ensure("assistant")
                cur["blocks"].append({"type": "tool_result", "content": p.get("output")})
    flush()
    return turns


def load_turns(source: str, path: Path) -> list[dict]:
    if source == "claude":
        return _anthropic_turns(path, "claude", "type")
    if source == "cursor":
        return _anthropic_turns(path, "cursor", "role")
    return load_codex(path)


# ============================ 会话发现 ============================
def enc(path: str, leading_dash: bool) -> str:
    """真实路径 -> 项目目录名：非字母数字字符全替换为 -。

    claude 保留前导 -（来自路径首个 /），cursor 去掉。与两家自身的
    有损编码一致，因此含 . _ 等字符的路径也能精确命中。
    """
    p = re.sub(r"[^A-Za-z0-9]", "-", path)
    return p if leading_dash else p.lstrip("-")


def iter_sessions(sources: tuple[str, ...]):
    """产出 (source, path, sid, mtime)；不读文件内容，按需再取 project。"""
    if "claude" in sources and CLAUDE_PROJECTS.is_dir():
        for p in CLAUDE_PROJECTS.glob("*/*.jsonl"):
            yield ("claude", p, p.stem, p.stat().st_mtime)
    if "codex" in sources and CODEX_SESSIONS.is_dir():
        for p in CODEX_SESSIONS.glob("*/*/*/rollout-*.jsonl"):
            m = CODEX_ID_RE.search(p.name)
            yield ("codex", p, m.group(0) if m else p.stem, p.stat().st_mtime)
    if "cursor" in sources and CURSOR_PROJECTS.is_dir():
        for p in CURSOR_PROJECTS.glob("*/agent-transcripts/*/*.jsonl"):
            yield ("cursor", p, p.stem, p.stat().st_mtime)


def session_project(source: str, path: Path) -> str:
    """会话所属项目标签：claude/cursor 取编码目录名，codex 读 session_meta 的 cwd。"""
    if source == "claude":
        return path.parent.name
    if source == "cursor":
        return path.parent.parent.parent.name
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                if o.get("type") == "session_meta":
                    return (o.get("payload") or {}).get("cwd", "")
                break
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def project_matches(source: str, path: Path, target: str) -> bool:
    """target 为真实路径时精确命中当前项目；否则按子串匹配项目标签。"""
    label = session_project(source, path)
    if target.startswith("/"):
        if source == "claude":
            return label == enc(target, True)
        if source == "cursor":
            return label == enc(target, False)
        return label == target
    return target in label


def resolve_scope(source_arg: str) -> tuple[str, ...]:
    """把 --source 值解析成要搜索的来源集合。"""
    if source_arg in SOURCES:
        return (source_arg,)
    if source_arg == "all":
        return SOURCES
    detected = detect_harness()
    return (detected,) if detected else SOURCES


def resolve_session(sid: str, scope: tuple[str, ...]) -> tuple[str, Path]:
    """按 id 或路径跨来源定位唯一会话，多命中则列出并退出。"""
    p = Path(os.path.expanduser(sid))
    if p.is_file():
        for src in SOURCES:
            root = {"claude": CLAUDE_PROJECTS, "codex": CODEX_SESSIONS,
                    "cursor": CURSOR_PROJECTS}[src]
            try:
                p.relative_to(root)
                return (src, p)
            except ValueError:
                continue
        return ("claude", p)
    exact = [(s, x) for s, x, i, _ in iter_sessions(scope) if i == sid]
    fuzzy = [(s, x) for s, x, i, _ in iter_sessions(scope) if sid in i]
    matches = exact or fuzzy
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        sys.exit(
            f"会话 ID 匹配多个（共 {len(matches)} 个），请用更长的 ID 或完整路径:\n  "
            + "\n  ".join(f"[{s}] {x}" for s, x in matches)
        )
    sys.exit(f"找不到会话: {sid}（搜索来源 {', '.join(scope)}）")


def cmd_list(scope: tuple[str, ...], project: str | None, limit: int) -> str:
    rows = sorted(iter_sessions(scope), key=lambda r: r[3], reverse=True)
    if project:
        rows = [r for r in rows if project_matches(r[0], r[1], project)]
    rows = rows[: limit or 20]
    if not rows:
        return "无匹配会话。"
    out = [f"# 最近会话（来源: {', '.join(scope)}）\n"]
    out.append("| # | 来源 | 时间 | 项目 | 会话 ID |")
    out.append("|---|---|---|---|---|")
    for i, (src, path, sid, mt) in enumerate(rows, 1):
        t = datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
        proj = session_project(src, path) or "-"
        if len(proj) > 46:
            proj = "…" + proj[-45:]
        out.append(f"| {i} | {src} | {t} | {proj} | `{sid}` |")
    out.append("\n用 `--session <会话 ID>` 恢复某个会话；`--source all` 跨全部来源。")
    return "\n".join(out) + "\n"


def default_session(scope: tuple[str, ...], project: str) -> tuple[str, Path]:
    """无 --session 时：当前项目下最近修改的会话。"""
    rows = [
        r for r in iter_sessions(scope) if project_matches(r[0], r[1], project)
    ]
    if not rows:
        sys.exit(
            f"当前项目（{project}）在来源 {', '.join(scope)} 下无会话；"
            "用 --list 浏览全部或 --session 指定。"
        )
    src, path, _, _ = max(rows, key=lambda r: r[3])
    return (src, path)


# ============================ 主流程 ============================
def digest(source: str, path: Path, tools: str, last: int, no_trunc: bool) -> str:
    turns = load_turns(source, path)
    if last > 0:
        turns = turns[-last:]
    blocks = [md for md in (turn_to_md(t, tools, no_trunc) for t in turns) if md]
    sid = CODEX_ID_RE.search(path.name)
    sid = sid.group(0) if sid else path.stem
    return f"# 会话摘要 · [{source}] {sid}\n\n" + "\n\n".join(blocks) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="session-digest",
        description="把 Claude Code / Codex / Cursor 会话压成可读 Markdown。",
    )
    ap.add_argument(
        "--source",
        choices=[*SOURCES, "auto", "all"],
        default="auto",
        help="会话来源：auto 按当前环境自动判断(默认) / claude / codex / cursor / all 全部",
    )
    ap.add_argument("--list", nargs="?", type=int, const=20, metavar="N",
                    help="列出最近 N 条会话供选择（默认 20），不解析内容")
    ap.add_argument("--project", help="项目真实路径或标签子串，默认当前目录")
    ap.add_argument("--session", help="会话 ID 或 .jsonl 路径，覆盖默认最新会话")
    ap.add_argument(
        "--tools",
        choices=["none", "name", "input", "full"],
        default="name",
        help="工具调用粒度：none 全丢 / name 仅工具名(默认) / input 名+入参 / full 名+入参+结果",
    )
    ap.add_argument("--last", type=int, default=0, help="只取最近 N 条消息（0=全量）")
    ap.add_argument("--no-truncate", action="store_true", help="full 模式下不截断工具结果")
    ap.add_argument("-o", "--output", help="输出文件路径，默认 stdout")
    args = ap.parse_args()

    scope = resolve_scope(args.source)

    if args.list is not None:
        md = cmd_list(scope, args.project, args.list)
    else:
        if args.session:
            source, path = resolve_session(args.session, scope)
        else:
            target = os.path.abspath(os.path.expanduser(args.project)) if args.project \
                else os.getcwd()
            source, path = default_session(scope, target)
        md = digest(source, path, args.tools, args.last, args.no_truncate)

    if args.output:
        out = Path(os.path.expanduser(args.output))
        out.write_text(md, encoding="utf-8")
        print(f"已写入 {out}", file=sys.stderr)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
