#!/usr/bin/env python3
"""
Migrate codex sessions (~/.codex/sessions/) into OpenCode's SQLite database.

Usage:
    python3 migrate_codex_sessions.py --dry-run    # preview only
    python3 migrate_codex_sessions.py               # execute migration
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CODEX_SESSIONS_DIR = Path.home() / ".codex/sessions"
OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"

ENV_CTX_RE = re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL)


def gen_id(prefix: str) -> str:
    """Generate an ID compatible with OpenCode's format: prefix_UUID."""
    return f"{prefix}_{uuid.uuid4().hex}"


def extract_title(user_messages: list[str]) -> str:
    """Generate a short session title from the first few user messages."""
    cleaned = []
    for msg in user_messages[:3]:
        # Remove environment_context blocks
        text = ENV_CTX_RE.sub("", msg).strip()
        # Remove <turn_aborted> markers
        text = re.sub(r"<turn_aborted>.*?</turn_aborted>", "", text, flags=re.DOTALL).strip()
        # Remove codex history import markers
        if text.startswith("The following is the Codex agent history"):
            continue
        # Remove AGENTS.md boilerplate
        if text.startswith("# AGENTS.md instructions for"):
            continue
        # Collapse whitespace and newlines
        text = " ".join(text.split())
        if text and len(text) > 3:
            cleaned.append(text)
    if not cleaned:
        return "codex-migrated"
    # Take first meaningful message, truncate to ~50 chars at sentence boundary
    title = cleaned[0]
    if len(title) > 50:
        for sep in ["。", "？", "！", ". ", "? ", "! "]:
            idx = title[:50].rfind(sep)
            if idx > 15:
                title = title[:idx + 1] if sep in "。？！" else title[:idx]
                break
        else:
            title = title[:47] + "..."
    return title


def parse_codex_session(filepath: Path) -> dict[str, Any] | None:
    """Parse a codex JSONL session file, returning structured data."""
    try:
        with open(filepath) as f:
            lines = [json.loads(line) for line in f if line.strip()]
    except (json.JSONDecodeError, OSError) as e:
        print(f"  SKIP: failed to parse {filepath.name}: {e}", file=sys.stderr)
        return None

    meta = None
    messages: list[dict[str, Any]] = []
    user_messages: list[str] = []

    for obj in lines:
        t = obj.get("type")

        if t == "session_meta":
            meta = obj["payload"]

        elif t == "response_item":
            payload = obj["payload"]
            role = payload.get("role", "unknown")
            content = payload.get("content") or []

            # Extract text from content items
            texts = []
            for c in content:
                if isinstance(c, dict):
                    ct = c.get("type", "")
                    if ct == "input_text":
                        texts.append(c.get("text", ""))
                    elif ct == "output_text":
                        texts.append(c.get("text", ""))

            text = "\n".join(texts)
            ts_str = obj.get("timestamp", "")

            if role == "user" and text:
                user_messages.append(text)

            messages.append({
                "role": role,
                "text": text,
                "timestamp": ts_str,
            })

    if not meta:
        print(f"  SKIP: no session_meta in {filepath.name}", file=sys.stderr)
        return None

    return {
        "id": meta["id"],
        "cwd": meta.get("cwd", os.path.expanduser("~")),
        "timestamp": meta.get("timestamp", ""),
        "git_branch": meta.get("git", {}).get("branch", ""),
        "title": extract_title(user_messages),
        "messages": messages,
    }


def parse_timestamp(ts: str) -> int:
    """Parse ISO 8601 timestamp to Unix milliseconds."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def find_or_create_project(db: sqlite3.Connection, cwd: str) -> str:
    """Find an existing OpenCode project for the given CWD, or create one."""
    cwd_path = Path(cwd).resolve()
    cwd_str = str(cwd_path)

    # Try to match by directory prefix
    cur = db.execute(
        "SELECT w.project_id FROM workspace w WHERE ? LIKE w.directory || '%' LIMIT 1",
        (cwd_str,),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Try to find a project whose directory is a prefix of cwd
    cur = db.execute("SELECT id, worktree FROM project")
    for proj_id, worktree in cur.fetchall():
        proj_dir = Path(worktree).resolve()
        try:
            cwd_path.relative_to(proj_dir)
            return proj_id
        except ValueError:
            continue

    # Create a new project for this CWD
    # Find the git root or use the CWD itself
    git_root = cwd_str
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd_str,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_root = result.stdout.strip()
    except Exception:
        pass

    # Hash the directory as project ID (consistent with how OpenCode does it)
    import hashlib
    proj_id = hashlib.sha1(git_root.encode()).hexdigest()
    name = Path(git_root).name

    now = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Check if project already exists
    cur = db.execute("SELECT id FROM project WHERE id = ?", (proj_id,))
    if cur.fetchone():
        return proj_id

    db.execute(
        """INSERT INTO project (id, worktree, vcs, name, icon_url, icon_color,
           time_created, time_updated, sandboxes, commands)
           VALUES (?, ?, 'git', ?, NULL, NULL, ?, ?, '[]', '[]')""",
        (proj_id, git_root, name, now, now),
    )

    # Create a workspace for this project
    ws_id = gen_id("ws_mig")
    db.execute(
        """INSERT INTO workspace (id, type, name, branch, directory, project_id, time_used)
           VALUES (?, 'local', ?, '', ?, ?, ?)""",
        (ws_id, name, git_root, proj_id, now),
    )

    return proj_id


def get_workspace_id(db: sqlite3.Connection, project_id: str) -> str | None:
    """Get the workspace ID for a project."""
    cur = db.execute(
        "SELECT id FROM workspace WHERE project_id = ? LIMIT 1",
        (project_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def migrate_session(
    db: sqlite3.Connection,
    session_data: dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """Migrate one codex session into the OpenCode database."""
    sid = session_data["id"]
    cwd = session_data["cwd"]
    title = session_data["title"]
    timestamp = session_data["timestamp"]
    time_ms = parse_timestamp(timestamp)

    # Check for duplicates
    cur = db.execute("SELECT id FROM session WHERE id = ?", (sid,))
    if cur.fetchone():
        print(f"  SKIP: session {sid[:12]}... already exists", file=sys.stderr)
        return False

    # Find or create project
    proj_id = find_or_create_project(db, cwd)
    ws_id = get_workspace_id(db, proj_id)

    if dry_run:
        print(f"  [DRY] {sid[:12]}... | {title[:60]} | {cwd}")
        return True

    # Insert session
    db.execute(
        """INSERT INTO session (id, project_id, slug, directory, title, version,
           time_created, time_updated, workspace_id, agent, model, cost,
           tokens_input, tokens_output, metadata)
           VALUES (?, ?, ?, ?, ?, 'migrated', ?, ?, ?, 'codex', 'gpt-5', 0, 0, 0,
           json(?))""",
        (
            sid,
            proj_id,
            f"codex-{sid[:8]}",
            cwd,
            title,
            time_ms,
            time_ms,
            ws_id,
            json.dumps({"source": "codex-migration", "codex_cli_version": ""}),
        ),
    )

    # Insert session_messages
    seq = 1
    prev_assistant_id = None
    last_user_id = None

    for msg_idx, msg in enumerate(session_data["messages"]):
        role = msg["role"]
        text = msg["text"]
        if not text:
            continue

        msg_time = parse_timestamp(msg["timestamp"]) or time_ms

        if role == "user":
            msg_id = gen_id("msg")
            # user messages don't have parent
            db.execute(
                """INSERT INTO message (id, session_id, time_created, time_updated, data)
                   VALUES (?, ?, ?, ?, json(?))""",
                (
                    msg_id,
                    sid,
                    msg_time,
                    msg_time,
                    json.dumps({
                        "role": "user",
                        "agent": "codex",
                        "model": {"providerID": "codex", "modelID": "gpt-5"},
                        "summary": {"diffs": []},
                        "time": {"created": msg_time},
                    }),
                ),
            )
            # Add text part
            part_id = gen_id("prt")
            db.execute(
                """INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)
                   VALUES (?, ?, ?, ?, ?, json(?))""",
                (
                    part_id,
                    msg_id,
                    sid,
                    msg_time,
                    msg_time,
                    json.dumps({"type": "text", "text": text}),
                ),
            )
            last_user_id = msg_id
            prev_assistant_id = None  # reset after user message

        elif role in ("assistant", "developer"):
            parent_id = last_user_id  # always parent to last user message
            msg_id = gen_id("msg")
            db.execute(
                """INSERT INTO message (id, session_id, time_created, time_updated, data)
                   VALUES (?, ?, ?, ?, json(?))""",
                (
                    msg_id,
                    sid,
                    msg_time,
                    msg_time,
                    json.dumps({
                        "parentID": parent_id,
                        "role": "assistant",
                        "mode": "codex",
                        "agent": "codex",
                        "path": {"cwd": cwd, "root": cwd},
                        "cost": 0,
                        "tokens": {"total": 0, "input": 0, "output": 0, "reasoning": 0, "cache": {"write": 0, "read": 0}},
                        "modelID": "gpt-5",
                        "providerID": "codex",
                        "time": {"created": msg_time, "completed": msg_time},
                        "finish": "stop",
                    }),
                ),
            )
            # Add text part
            part_id = gen_id("prt")
            db.execute(
                """INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)
                   VALUES (?, ?, ?, ?, ?, json(?))""",
                (
                    part_id,
                    msg_id,
                    sid,
                    msg_time,
                    msg_time,
                    json.dumps({"type": "text", "text": text}),
                ),
            )
            prev_assistant_id = msg_id

        # session_message for tracking
        sm_id = gen_id("sm")
        sm_type = f"codex-{role}"
        db.execute(
            """INSERT INTO session_message (id, session_id, type, time_created, time_updated, data, seq)
               VALUES (?, ?, ?, ?, ?, '{}', ?)""",
            (sm_id, sid, sm_type, msg_time, msg_time, seq),
        )
        seq += 1

    print(f"  OK: {sid[:12]}... | {title[:60]}")
    return True


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN MODE ===\n")
    else:
        print("=== MIGRATION MODE ===\n")

    # Verify OpenCode DB exists
    if not OPENCODE_DB.exists():
        print(f"ERROR: OpenCode DB not found at {OPENCODE_DB}", file=sys.stderr)
        sys.exit(1)

    # Backup
    if not dry_run:
        backup_path = OPENCODE_DB.with_suffix(".db.mig_backup")
        import shutil
        shutil.copy2(OPENCODE_DB, backup_path)
        print(f"Backed up to {backup_path}\n")

    # Find all codex sessions
    session_files = sorted(CODEX_SESSIONS_DIR.rglob("*.jsonl"))
    print(f"Found {len(session_files)} codex session files\n")

    # Parse all sessions
    parsed_sessions = []
    for fp in session_files:
        data = parse_codex_session(fp)
        if data:
            parsed_sessions.append(data)

    print(f"Parsed {len(parsed_sessions)} sessions successfully\n")

    # Connect to OpenCode DB
    db = sqlite3.connect(str(OPENCODE_DB))
    db.execute("PRAGMA foreign_keys = ON")

    migrated = 0
    skipped = 0
    for i, sess in enumerate(parsed_sessions, 1):
        print(f"[{i}/{len(parsed_sessions)}] ", end="")
        result = migrate_session(db, sess, dry_run=dry_run)
        if result:
            migrated += 1
        else:
            skipped += 1

    if not dry_run:
        db.commit()
    db.close()

    print(f"\n=== Summary ===")
    print(f"Migrated: {migrated}")
    print(f"Skipped:  {skipped}")
    if dry_run:
        print("(dry run - no changes made)")


if __name__ == "__main__":
    main()
