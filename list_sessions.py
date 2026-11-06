#!/usr/bin/env python3
"""List your saved Claude Code sessions without using any usage.

Reads the session files in ~/.claude/projects/ directly (nothing is sent to Claude).

Usage:
  python3 list_sessions.py              # all projects, newest first
  python3 list_sessions.py siit         # only projects whose path contains "siit"
  python3 list_sessions.py -n 50        # show up to 50 sessions (default 30)
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"


def text_of(content):
    """Get plain text from a message's content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(parts)
    return ""


def read_session(path):
    title = None        # name set with /rename, if any
    summary = None      # auto summary, if any
    first_msg = None    # first real thing you typed
    cwd = None
    n_msgs = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                cwd = cwd or d.get("cwd")
                title = d.get("customTitle") or title
                if d.get("type") == "summary" and d.get("summary"):
                    summary = d["summary"]
                if d.get("type") in ("user", "assistant"):
                    n_msgs += 1
                if d.get("type") == "user" and first_msg is None and not d.get("isMeta"):
                    t = text_of((d.get("message") or {}).get("content")).strip()
                    if t and not t.startswith("<"):   # skip command/system wrappers
                        first_msg = t
    except OSError:
        return None
    name = title or summary or first_msg or "(empty session)"
    return {
        "id": path.stem,
        "name": " ".join(name.split())[:70],
        "cwd": cwd or path.parent.name,
        "msgs": n_msgs,
        "mtime": path.stat().st_mtime,
    }


def main():
    args = sys.argv[1:]
    limit = 30
    if "-n" in args:
        i = args.index("-n")
        limit = int(args[i + 1])
        del args[i:i + 2]
    filt = args[0].lower() if args else None

    if not ROOT.exists():
        print(f"No sessions folder found at {ROOT}")
        return

    sessions = []
    for f in ROOT.glob("*/*.jsonl"):
        s = read_session(f)
        if s and (not filt or filt in s["cwd"].lower()):
            sessions.append(s)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)

    home = str(Path.home())
    for s in sessions[:limit]:
        when = datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
        folder = s["cwd"].replace(home, "~")
        print(f"{when}  {s['msgs']:>4} msgs  {folder}")
        print(f"    {s['name']}")
        print(f"    claude --resume {s['id']}")
        print()
    print(f"Showing {min(limit, len(sessions))} of {len(sessions)} sessions.")


if __name__ == "__main__":
    main()
