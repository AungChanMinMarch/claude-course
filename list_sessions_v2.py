#!/usr/bin/env python3
"""List, read, and reopen your saved Claude Code sessions.

Reads the session files in ~/.claude/projects/ directly. Listing and reading
send nothing to Claude and use none of your usage. Your session files are
never changed: this script only reads them.

Usage:
  claude-sessions                  # menu of sessions started in this folder
  claude-sessions --all            # menu of sessions from every folder
  claude-sessions --all siit       # every folder whose path contains "siit"
  claude-sessions -n 50            # show up to 50 sessions (default 30)
  claude-sessions --show-empty     # also show sessions with no prompts
  claude-sessions --plain          # plain list in a pager, no menu

  claude-sessions --read 689c3e55  # read a conversation in the terminal
  claude-sessions --html 689c3e55  # read it in your browser, where each
                                   # answer can be shown or hidden by a click
  claude-sessions --open 689c3e55  # continue it in Claude Code
                                   # (goes to the right folder for you)
  claude-sessions --open 689c3e55 --no-git   # same, but skip the Git check

The menu (when you list sessions in a terminal):
  Up/Down arrows     move the highlight one session
  PgUp/PgDn          move one screen
  Home/End           first / last session
  a number           jump to that session (type 1 then 2 for no. 12)
  o                  open (continue) the highlighted session in Claude Code
  r                  read it in the terminal, then come back to the menu
  h                  open it in your browser, then come back to the menu
  d                  move it to the trash folder (asks y/n first)
  q or Esc           quit
  Example: type 2 then o to open session no. 2. No Enter is needed.

The trash: d never deletes. It MOVES the session file to
~/claude-sessions-trash/<project-folder-name>/ so you can put it back:
  mv ~/claude-sessions-trash/<folder>/<id>.jsonl ~/.claude/projects/<folder>/
(some sessions also have a folder named <id>; move it back the same way).
To delete for good, remove files from ~/claude-sessions-trash yourself.

Git check before --open (only when the folder is a Git repository):
  - fetches (downloads news from the remote; changes none of your files)
  - no local changes + new commits on the remote -> pulls with --ff-only
    (only moves forward, never merges, so no conflicts are possible)
  - uncommitted changes -> shows them and asks: continue, pull, or quit
  - local commits not pushed -> reminds you to push
  It NEVER commits and NEVER pushes for you.

For --read, --html and --open, the first 8 characters of the id are enough.

--read and --plain open in a pager ('less'): scroll with the arrow keys,
Space and b (page down/up), search with /word, and press q to close.

Colours in the list: green = the name you gave with /rename,
red = "haven't renamed yet", blue = your first prompt.
Colours turn off by themselves when the output goes to a file or another
program, or when the NO_COLOR environment variable is set.

(If you run the file directly, use "python3 list_sessions_v2.py" instead of
"claude-sessions".)

Note: this reads Claude Code's internal file format, which is not an official
interface. A future Claude Code update may change it.
"""
import argparse
import curses
import html
import json
import locale
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from string import Template

ROOT = Path.home() / ".claude" / "projects"
HOME = str(Path.home())
SHORT_ID = 8   # how many id characters to print in the list
HTML_DIR = Path(tempfile.gettempdir()) / "claude-sessions"   # where --html pages go
TRASH_DIR = Path.home() / "claude-sessions-trash"   # where the d key moves sessions
RECENT_SECONDS = 10 * 60   # "used in the last 10 minutes" = maybe open right now

# ANSI colour codes: special characters that terminals show as colours.
# The "bright" versions (9x) are easier to read on a dark background.
USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
GREEN, RED, BLUE, RESET = "\033[92m", "\033[91m", "\033[94m", "\033[0m"
YELLOW = "\033[93m"


def color(text, code):
    """Wrap text in a colour, or return it unchanged if colours are off."""
    return f"{code}{text}{RESET}" if USE_COLOR else text


# ---------------------------------------------------------------- reading files

def text_of(content):
    """Get plain text from a message's content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(parts)
    return ""


def typed_prompt(d):
    """Return the text if this line is a prompt you really typed, else None.

    Skips tool results, system/meta text, slash-command wrappers,
    sub-agent messages and "[Request interrupted ...]" notes.
    """
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return None
    text = text_of((d.get("message") or {}).get("content")).strip()
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return None
    return text


def lines_of(path):
    """Yield each JSON record (a dict) in a session file, skipping bad lines."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict):
                yield d


def one_line(text, width=70):
    """Squeeze text onto one line and cut it to `width` characters."""
    return " ".join(text.split())[:width]


def read_session(path):
    title = None        # name set with /rename, if any (the newest one wins)
    first_msg = None    # first real prompt you typed
    cwd = None          # folder the session was started in
    prompts = 0         # how many prompts you typed
    try:
        mtime = path.stat().st_mtime
        for d in lines_of(path):
            cwd = cwd or d.get("cwd")
            title = d.get("customTitle") or title
            text = typed_prompt(d)
            if text:
                prompts += 1
                if first_msg is None:
                    first_msg = text
    except OSError:
        return None
    return {
        "id": path.stem,
        "path": path,
        "title": one_line(title) if title else None,
        "first": one_line(first_msg) if first_msg else None,
        "first_full": first_msg,
        "name": one_line(title or first_msg or "(empty session)"),
        "cwd": cwd,
        "prompts": prompts,
        "mtime": mtime,
    }


def tool_note(block):
    """One short line describing a tool Claude used, e.g. 'Read: notes.md'."""
    name = block.get("name", "tool")
    inp = block.get("input") or {}
    detail = (inp.get("description") or inp.get("file_path")
              or inp.get("command") or inp.get("pattern") or "")
    detail = " ".join(str(detail).split())[:80]
    return f"[Claude used {name}{': ' + detail if detail else ''}]"


def conversation(path):
    """Split a session into turns: one of your prompts plus everything after it.

    Each turn is {"prompt": text or None, "when": time, "items": [...]},
    where each item is ("text", answer, time) or ("tool", note, time).
    """
    turns = []
    for d in lines_of(path):
        if d.get("isSidechain"):
            continue
        when = local_time(d.get("timestamp"))
        text = typed_prompt(d)
        if text:
            turns.append({"prompt": text, "when": when, "items": []})
            continue
        if d.get("type") != "assistant":
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            item = None
            if b.get("type") == "text" and b.get("text", "").strip():
                item = ("text", b["text"].strip(), when)
            elif b.get("type") == "tool_use":
                item = ("tool", tool_note(b), when)
            if item:
                if not turns:   # Claude spoke before your first prompt
                    turns.append({"prompt": None, "when": when, "items": []})
                turns[-1]["items"].append(item)
    return turns


# ---------------------------------------------------------------- small helpers

def same_folder(a, b):
    """True if two paths point to the same folder (follows symlinks)."""
    return os.path.realpath(a) == os.path.realpath(b)


def short_path(p):
    """Show /home/you/x as ~/x (only when it really starts with your home)."""
    if p == HOME or p.startswith(HOME + "/"):
        return "~" + p[len(HOME):]
    return p


def positive_int(text):
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def local_time(stamp):
    """Turn '2026-11-02T13:51:00.000Z' into '2026-11-02 20:51' (your time)."""
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return t.astimezone().strftime("%Y-%m-%d %H:%M")
    except (AttributeError, ValueError):
        return ""


def find_session(id_start):
    """Find the one session file whose id starts with id_start."""
    matches = [f for f in ROOT.glob("*/*.jsonl") if f.stem.startswith(id_start)]
    if not matches:
        sys.exit(f"No session id starts with '{id_start}'.")
    if len(matches) > 1:
        names = "\n  ".join(f.stem for f in matches)
        sys.exit(f"'{id_start}' matches more than one session:\n  {names}\n"
                 "Type more characters of the id.")
    return matches[0]


def load(id_start):
    path = find_session(id_start)
    s = read_session(path)
    if s is None:
        sys.exit(f"Could not read {path}")
    return s


def show_in_pager(text):
    """Show long text page by page with 'less' (q quits), or just print it."""
    if sys.stdout.isatty() and shutil.which("less"):
        subprocess.run(["less", "-R"], input=text, text=True)
    else:
        print(text)


def open_in_browser(path):
    """Open a file in your browser. Works from WSL (Windows browser) or Linux."""
    try:
        if shutil.which("wslview"):
            subprocess.run(["wslview", str(path)])
        elif shutil.which("explorer.exe") and shutil.which("wslpath"):
            win = subprocess.run(["wslpath", "-w", str(path)],
                                 capture_output=True, text=True).stdout.strip()
            subprocess.run(["explorer.exe", win])   # its exit code is unreliable
        elif shutil.which("xdg-open"):
            subprocess.run(["xdg-open", str(path)])
        else:
            return False
    except OSError:
        return False
    return True


def list_details(s):
    """The pieces of one list entry: time, prompt count word, folder, short id."""
    when = datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
    word = "prompt " if s["prompts"] == 1 else "prompts"
    folder = short_path(s["cwd"]) if s["cwd"] else "(unknown folder)"
    return when, word, folder, s["id"][:SHORT_ID]


def trash_session(s):
    """Move a session's file (and its folder, if any) to TRASH_DIR.

    Nothing is deleted. Returns where the file went. Raises OSError if the
    move is not possible (for example, the same file is already in the trash).
    """
    src = s["path"]                          # .../projects/<folder>/<id>.jsonl
    dest_dir = TRASH_DIR / src.parent.name   # keep the project folder's name
    dest = dest_dir / src.name
    extra = src.parent / src.stem            # some sessions also have <id>/
    if dest.exists() or (dest_dir / src.stem).exists():
        raise OSError(f"{short_path(str(dest))} is already in the trash")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    if extra.is_dir():
        shutil.move(str(extra), str(dest_dir / src.stem))
    return dest


# ---------------------------------------------------------------- the HTML page

PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
  :root { --bg:#f7f7f8; --fg:#1d1d1f; --card:#ffffff; --line:#dcdce0;
          --muted:#6e6e73; --you:#e9f0fd; --accent:#3b6fd8; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#18181a; --fg:#e8e8ea; --card:#232326; --line:#3a3a3f;
            --muted:#9a9aa0; --you:#1f2b40; --accent:#7ea2ee; }
  }
  body { background:var(--bg); color:var(--fg); margin:0;
         font:15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width:900px; margin:0 auto; padding:24px 16px 60px; }
  h1 { font-size:1.3rem; margin:0 0 4px; }
  .sub { margin:0 0 4px; }
  .meta { color:var(--muted); font-size:.9rem; margin:0 0 16px; }
  .bar { position:sticky; top:0; background:var(--bg); padding:8px 0;
         display:flex; gap:8px; flex-wrap:wrap; align-items:center; z-index:1; }
  button { font:inherit; padding:6px 12px; border-radius:6px; cursor:pointer;
           border:1px solid var(--line); background:var(--card); color:var(--fg); }
  button:hover { border-color:var(--accent); }
  .hint { color:var(--muted); font-size:.85rem; }
  details { background:var(--card); border:1px solid var(--line);
            border-radius:8px; margin:12px 0; overflow:hidden; }
  summary { cursor:pointer; padding:10px 14px; background:var(--you);
            list-style:none; }
  summary::-webkit-details-marker { display:none; }
  summary .head { color:var(--muted); font-size:.85rem; }
  summary .head::before { content:"\\25B6  "; color:var(--accent); }
  details[open] summary .head::before { content:"\\25BC  "; }
  .q { display:block; white-space:pre-wrap; word-wrap:break-word; margin-top:4px; }
  .a { padding:10px 14px; }
  .text { white-space:pre-wrap; word-wrap:break-word; margin:8px 0; }
  .tool { color:var(--muted); font-family:ui-monospace, monospace;
          font-size:.82rem; margin:2px 0; word-wrap:break-word; }

  /* Claude's answers after Markdown is turned into HTML */
  .text.md { white-space:normal; }
  .md > :first-child { margin-top:0; }
  .md > :last-child { margin-bottom:0; }
  .md h1, .md h2, .md h3, .md h4 { line-height:1.3; margin:1.1em 0 .4em; }
  .md h1 { font-size:1.25rem; } .md h2 { font-size:1.15rem; }
  .md h3 { font-size:1.05rem; } .md h4 { font-size:1rem; }
  .md p, .md ul, .md ol { margin:.5em 0; }
  .md li { margin:.2em 0; }
  .md a { color:var(--accent); }
  .md code { font-family:ui-monospace, monospace; font-size:.88em;
             background:var(--bg); border:1px solid var(--line);
             border-radius:4px; padding:0 4px; }
  .md pre { background:var(--bg); border:1px solid var(--line);
            border-radius:6px; padding:10px 12px; overflow-x:auto; }
  .md pre code { border:0; padding:0; background:none; font-size:.85rem; }
  .md blockquote { margin:.6em 0; padding:2px 12px; color:var(--muted);
                   border-left:3px solid var(--line); }
  .md table { border-collapse:collapse; margin:.6em 0; display:block;
              overflow-x:auto; max-width:100%; }
  .md th, .md td { border:1px solid var(--line); padding:5px 9px;
                   text-align:left; vertical-align:top; }
  .md th { background:var(--bg); }
  .md hr { border:0; border-top:1px solid var(--line); margin:1em 0; }
</style>
<!-- Markdown -> HTML (marked) and a safety filter (DOMPurify).
     Loaded from the internet. Without internet the page still works,
     and answers are shown as plain text. -->
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
</head>
<body>
<main>
<h1>$title</h1>
$sub
<p class="meta">$meta</p>
<div class="bar">
  <button type="button" onclick="setAll(true)">Show all answers</button>
  <button type="button" onclick="setAll(false)">Hide all answers</button>
  <span class="hint">Click a question to show or hide its answer.
  Keys: <b>s</b> show all, <b>h</b> hide all.</span>
</div>
$turns
</main>
<script>
  function setAll(open) {
    document.querySelectorAll("details").forEach(function (d) { d.open = open; });
  }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "s") setAll(true);
    if (e.key === "h") setAll(false);
  });

  // Turn each answer's Markdown into formatted HTML, if the libraries loaded.
  if (window.marked && window.DOMPurify) {
    document.querySelectorAll(".text").forEach(function (el) {
      try {
        var raw = el.textContent;
        el.innerHTML = DOMPurify.sanitize(marked.parse(raw, { gfm: true }));
        el.classList.add("md");
        el.querySelectorAll("a").forEach(function (a) {
          a.target = "_blank"; a.rel = "noopener noreferrer";
        });
      } catch (err) { /* keep the plain text if anything goes wrong */ }
    });
  }
</script>
</body>
</html>
""")


def build_html(s, turns):
    """Make the full HTML page for one session."""
    esc = html.escape
    parts = []
    for i, t in enumerate(turns, 1):
        prompt = t["prompt"] if t["prompt"] is not None else "(before your first prompt)"
        items = []
        for kind, text, _when in t["items"]:
            css = "text" if kind == "text" else "tool"
            items.append(f'<div class="{css}">{esc(text)}</div>')
        if not items:
            items.append('<div class="tool">(no answer saved)</div>')
        parts.append(
            "<details>\n"
            f'<summary><span class="head">#{i} &middot; {esc(t["when"])}</span>'
            f'<span class="q">{esc(prompt)}</span></summary>\n'
            f'<div class="a">\n' + "\n".join(items) + "\n</div>\n</details>"
        )
    folder = short_path(s["cwd"]) if s["cwd"] else "(unknown folder)"
    meta = (f"{esc(folder)} &middot; {s['prompts']} prompts &middot; "
            f"id {esc(s['id'])}")
    # If renamed: the name is the big title and the first prompt goes below it.
    sub = f'<p class="sub">{esc(s["first"])}</p>' if s["title"] and s["first"] else ""
    return PAGE.substitute(title=esc(s["name"]), sub=sub, meta=meta,
                           turns="\n".join(parts) or "<p>(empty session)</p>")


# ---------------------------------------------------------------- Git check

def git(cwd, *args, timeout=30):
    """Run one git command in folder cwd. Returns (ok, output text)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")   # never hang on a password prompt
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                           text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, f"git {args[0]} took longer than {timeout} seconds"
    except OSError as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def warn(text):
    print(color(text, YELLOW))


def ask(choices):
    """Ask until the user types one of the choices (a dict: key -> meaning)."""
    menu = "   ".join(f"[{k}] {v}" for k, v in choices.items())
    while True:
        print(menu)
        try:
            answer = input("Your choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "q"
        if answer in choices:
            return answer
        print(f"Please type one of: {', '.join(choices)}")


def pull(cwd):
    """Fast-forward pull. Git refuses safely if it cannot (nothing is lost)."""
    print("Pulling (fast-forward only)...")
    ok, out = git(cwd, "pull", "--ff-only", timeout=120)
    if ok:
        print(color("Pull done.", GREEN))
    else:
        warn("Pull did not happen. Git said:")
        print("  " + out.replace("\n", "\n  "))
    return ok


def git_check(cwd):
    """Check the session's folder with Git before opening Claude.

    Returns True to go on and open the session, False to stop.
    It may pull (fast-forward only). It never commits and never pushes.
    """
    if not shutil.which("git"):
        return True
    ok, out = git(cwd, "rev-parse", "--is-inside-work-tree")
    if not ok or out != "true":
        print("Git check: this folder is not a Git repository, skipping.")
        return True

    must_ask = False    # True = something needs your decision
    can_pull = False    # True = offer [p] pull in the menu

    ok, branch = git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = branch if ok else None
    print(f"Git check: branch {branch or '(none)'}")

    # 1. Is Git in the middle of something unfinished?
    #    Git leaves these marker files while such an operation is open.
    busy = False
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
        ok, rel = git(cwd, "rev-parse", "--git-path", marker)
        if ok and os.path.exists(os.path.join(cwd, rel)):
            busy = True
    if busy:
        warn("Git is in the middle of an unfinished operation "
             "(merge/rebase/cherry-pick). Finish or abort it first.")
        must_ask = True
    if branch is None:
        warn("You are not on a branch (\"detached HEAD\"). Skipping pull.")
        must_ask = True

    # 2. Uncommitted changes?
    ok, status = git(cwd, "status", "--short")
    dirty = ok and bool(status)
    if dirty:
        files = status.splitlines()
        warn(f"Uncommitted changes ({len(files)} files):")
        for line in files[:20]:
            print("    " + line)
        if len(files) > 20:
            print(f"    ... and {len(files) - 20} more")
        print("  Suggestion: quit, check with 'git status' and 'git diff', "
              "then 'git add <files>' and 'git commit'.")
        must_ask = True

    # 3. Anything new on the remote? (only on a normal branch with an upstream)
    if branch and not busy:
        ok, upstream = git(cwd, "rev-parse", "--abbrev-ref",
                           "--symbolic-full-name", "@{u}")
        if not ok:
            print(f"Branch {branch} has no upstream (no remote branch it tracks). "
                  "Skipping pull check.")
        else:
            print(f"Fetching from {upstream.split('/')[0]}...")
            ok, out = git(cwd, "fetch", "--quiet", timeout=60)
            if not ok:
                warn("Could not fetch (offline? login needed?). Git said:")
                print("  " + out.replace("\n", "\n  "))
                must_ask = True
            else:
                ok, counts = git(cwd, "rev-list", "--left-right", "--count",
                                 "HEAD...@{u}")
                ahead, behind = (int(x) for x in counts.split()) if ok else (0, 0)
                if ahead and behind:
                    warn(f"Your branch and {upstream} have both moved on "
                         f"({ahead} local, {behind} remote commits). "
                         "A fast-forward pull is not possible.")
                    must_ask = True
                elif behind:
                    print(f"{behind} new commit(s) on {upstream}.")
                    if dirty:
                        can_pull = True   # let the user choose
                    elif not pull(cwd):
                        must_ask = True
                elif ahead:
                    print(f"{ahead} local commit(s) not pushed yet. "
                          "Suggestion: 'git push' when you are ready.")
                else:
                    print(color(f"Up to date with {upstream}.", GREEN))

    if not must_ask:
        return True

    print()
    while True:
        choices = {"c": "continue without pulling" if can_pull else "continue"}
        if can_pull:
            choices["p"] = "pull, then continue"
        choices["q"] = "quit"
        answer = ask(choices)
        if answer == "q":
            print("Stopped. Nothing was opened.")
            return False
        if answer == "c":
            return True
        if pull(cwd):          # answer == "p"
            return True
        can_pull = False       # pull failed safely: ask again without [p]


# ---------------------------------------------------------------- the menu

ROWS_PER_SESSION = 4   # header line, name line, first-prompt line, empty line


def put(win, y, x, text, attr=0):
    """Write text on the screen, cut to fit. Ignores 'off the screen' errors."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w - 1:
        return
    try:
        win.addnstr(y, x, text, w - 1 - x, attr)
    except curses.error:
        pass   # e.g. very wide characters at the right edge


def menu(stdscr, sessions, where, sel, status):
    """Draw the session menu and wait for keys.

    Returns (action, sel): action is "o", "r", "h", "d", or None for quit,
    and sel is the position (0 = first) of the highlighted session.
    """
    try:
        curses.curs_set(0)          # hide the blinking cursor
    except curses.error:
        pass
    green = red = blue = 0
    if USE_COLOR and curses.has_colors():
        try:
            curses.start_color()
            curses.use_default_colors()   # keep your terminal's background
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_RED, -1)
            curses.init_pair(3, curses.COLOR_BLUE, -1)
            green = curses.color_pair(1) | curses.A_BOLD
            red = curses.color_pair(2) | curses.A_BOLD
            blue = curses.color_pair(3) | curses.A_BOLD
        except curses.error:
            pass

    n = len(sessions)
    top = 0          # the session shown at the top of the screen
    digits = ""      # number typed so far, e.g. "1" then "12"
    while True:
        h, w = stdscr.getmaxyx()
        page = max(1, (h - 4) // ROWS_PER_SESSION)   # sessions that fit
        if sel < top:
            top = sel
        if sel >= top + page:
            top = sel - page + 1

        stdscr.erase()
        put(stdscr, 0, 0, f"Claude Code sessions ({where})   "
                          f"{sel + 1} of {n}", curses.A_BOLD)
        for i in range(top, min(n, top + page)):
            s = sessions[i]
            y = 2 + (i - top) * ROWS_PER_SESSION
            when, word, folder, sid = list_details(s)
            mark = ">" if i == sel else " "
            head = f"{mark}{i + 1:>3}. {when}  {s['prompts']:>4} {word}  id {sid}  {folder}"
            if s["older_copy"]:
                head += "  (same start as a newer one)"
            put(stdscr, y, 0, head, curses.A_REVERSE if i == sel else 0)
            if s["title"]:
                put(stdscr, y + 1, 6, s["title"], green)
            else:
                put(stdscr, y + 1, 6, "haven't renamed yet", red)
            put(stdscr, y + 2, 6, s["first"] or "(no prompt)", blue)

        if digits:
            status = f"Go to number: {digits}"
        put(stdscr, h - 2, 0, status, curses.A_BOLD)
        put(stdscr, h - 1, 0, "Up/Down move  number jump  "
                              "o open  r read  h html  d trash  q quit")
        stdscr.refresh()

        key = stdscr.getch()
        status = ""
        if ord("0") <= key <= ord("9"):
            d = digits + chr(key)
            if not 1 <= int(d) <= n:      # too big: start a new number
                d = chr(key)
            if 1 <= int(d) <= n:
                digits = d
                sel = int(d) - 1
            else:
                digits = ""
            continue
        digits = ""
        if key == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif key == curses.KEY_DOWN:
            sel = min(n - 1, sel + 1)
        elif key == curses.KEY_PPAGE:
            sel = max(0, sel - page)
        elif key == curses.KEY_NPAGE:
            sel = min(n - 1, sel + page)
        elif key == curses.KEY_HOME:
            sel = 0
        elif key == curses.KEY_END:
            sel = n - 1
        elif key in (ord("o"), ord("r"), ord("h")):
            return chr(key), sel
        elif key == ord("d"):
            # Ask on the bottom lines. Only "y" moves; any other key cancels.
            s = sessions[sel]
            question = f"Move no. {sel + 1} to {short_path(str(TRASH_DIR))}? y/n"
            note = ""
            if datetime.now().timestamp() - s["mtime"] < RECENT_SECONDS:
                note = ("Careful: used in the last 10 minutes. "
                        "It may be open in Claude Code right now!")
            for y in (h - 3, h - 2):
                try:
                    stdscr.move(y, 0)
                    stdscr.clrtoeol()
                except curses.error:
                    pass
            put(stdscr, h - 3, 0, note, red)
            put(stdscr, h - 2, 0, question, curses.A_BOLD)
            stdscr.refresh()
            if stdscr.getch() in (ord("y"), ord("Y")):
                return "d", sel
            status = "Not moved."
        elif key in (ord("q"), 27):        # 27 = the Esc key
            return None, sel
        # any other key (or a window resize): just draw again


def menu_mode(sessions, where):
    """Show the menu; run read/html and come back; open leaves for Claude."""
    locale.setlocale(locale.LC_ALL, "")        # so non-English text shows right
    os.environ.setdefault("ESCDELAY", "25")    # make Esc react quickly
    sel, status = 0, ""
    while True:
        try:
            action, sel = curses.wrapper(menu, sessions, where, sel, status)
        except KeyboardInterrupt:              # Ctrl+C
            return
        if action is None:
            return
        s = sessions[sel]
        if action == "o":
            open_mode(s["id"])                 # becomes Claude Code; no return
            return
        if action == "r":
            read_mode(s["id"])
            status = ""
        elif action == "h":
            path, opened = html_mode(s["id"])
            status = (f"No. {sel + 1} opened in your browser." if opened
                      else f"Could not open a browser. File: {path}")
        elif action == "d":
            try:
                dest = trash_session(s)
            except OSError as e:
                status = f"Not moved: {e}"
                continue
            sessions.pop(sel)
            status = f"Moved to {short_path(str(dest))}"
            if not sessions:
                print(status)
                print("No sessions left in this list.")
                return
            sel = min(sel, len(sessions) - 1)


# ---------------------------------------------------------------- the modes

def read_mode(id_start):
    s = load(id_start)
    out = [
        f"Session: {s['title'] or '(not renamed yet)'}",
        f"First:   {s['first'] or '(no prompt)'}",
        f"Folder:  {short_path(s['cwd']) if s['cwd'] else '(unknown)'}",
        f"Id:      {s['id']}",
        f"Prompts: {s['prompts']}",
        "",
    ]
    for t in conversation(s["path"]):
        if t["prompt"] is not None:
            out += ["", f"=================== YOU  {t['when']}", t["prompt"], ""]
        for kind, text, when in t["items"]:
            if kind == "text":
                out += [f"------------------- CLAUDE  {when}", text, ""]
            else:
                out.append("  " + text)
    out += ["", "(end of session)",
            f"To continue it in Claude Code:  claude-sessions --open {s['id'][:SHORT_ID]}"]
    show_in_pager("\n".join(out))


def html_mode(id_start):
    """Write the HTML page and open it. Returns (file path, opened or not)."""
    s = load(id_start)
    page = build_html(s, conversation(s["path"]))
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    out = HTML_DIR / f"{s['id']}.html"
    out.write_text(page, encoding="utf-8")
    print(f"Saved: {out}")
    opened = open_in_browser(out)
    if opened:
        print("Opening it in your browser...")
    else:
        print("Could not open a browser. Open the file above yourself.")
    return out, opened


def open_mode(id_start, check_git=True):
    s = load(id_start)
    if not s["cwd"]:
        sys.exit("Cannot tell which folder this session was started in.")
    if not os.path.isdir(s["cwd"]):
        sys.exit(f"The session's folder no longer exists: {s['cwd']}")
    if not shutil.which("claude"):
        sys.exit("The 'claude' command was not found.")
    if check_git and not git_check(s["cwd"]):
        sys.exit(0)
    print(f"Opening in {short_path(s['cwd'])}: {s['name']}")
    os.chdir(s["cwd"])
    # Replace this script with Claude Code, running in the session's folder.
    os.execvp("claude", ["claude", "--resume", s["id"]])


def plain_list(shown, total, where, hidden):
    """The list as plain text, shown in the pager (q closes it)."""
    out = []
    for s in shown:
        when, word, folder, sid = list_details(s)
        out.append(f"{when}  {s['prompts']:>4} {word}  id {sid}  {folder}")
        if s["title"]:
            out.append("    " + color(s["title"], GREEN))
        else:
            out.append("    " + color("haven't renamed yet", RED))
        out.append("    " + color(s["first"] or "(no prompt)", BLUE))
        if s["older_copy"]:
            out.append("    (same first prompt as a newer session above: compare prompt counts)")
        out.append("")
    out.append(f"Showing {len(shown)} of {total} sessions ({where}).")
    if hidden:
        out.append(f"Hidden: {hidden} empty sessions (use --show-empty to see them).")
    out.append("Use an id:  --read ID (terminal)  --html ID (browser)  --open ID (continue)")
    out.append("(press q to close this list)")
    show_in_pager("\n".join(out))


def list_mode(args):
    here = os.getcwd()
    filt = args.filter.lower() if args.filter else None

    sessions = []
    for f in ROOT.glob("*/*.jsonl"):
        s = read_session(f)
        if s is None:
            continue
        if args.all:
            folder = s["cwd"] or f.parent.name
            if filt and filt not in folder.lower():
                continue
        else:
            if not s["cwd"] or not same_folder(s["cwd"], here):
                continue
        sessions.append(s)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)

    # Mark older sessions that start with the same prompt as a newer one
    # in the same folder. This only says "same start"; it does NOT tell
    # which session holds more work (compare the prompt counts yourself).
    seen = set()
    for s in sessions:
        s["older_copy"] = False
        if s["first_full"] and not s["title"]:
            key = (s["cwd"], s["first_full"])
            if key in seen:
                s["older_copy"] = True
            seen.add(key)

    empty = [s for s in sessions if s["prompts"] == 0 and not s["title"]]
    if not args.show_empty:
        sessions = [s for s in sessions if s not in empty]
    hidden = 0 if args.show_empty else len(empty)

    if not sessions:
        if args.all:
            print("No Claude Code sessions found.")
        else:
            print(f"No Claude Code sessions in {short_path(here)}")
            print("(use --all to see sessions from every folder)")
        if hidden:
            print(f"Hidden: {hidden} empty sessions (use --show-empty to see them).")
        return

    shown = sessions[:args.n]
    where = "every folder" if args.all else short_path(here)
    # The menu needs a real terminal for keys and screen. Otherwise
    # (output to a file or another program, or --plain) print the list.
    if args.plain or not (sys.stdin.isatty() and sys.stdout.isatty()):
        plain_list(shown, len(sessions), where, hidden)
    else:
        menu_mode(shown, where)


def main():
    parser = argparse.ArgumentParser(
        description="List, read, or reopen saved Claude Code sessions. "
                    "Default: a menu of sessions started in the current folder.")
    parser.add_argument("filter", nargs="?", default=None,
                        help="with --all: only folders whose path contains this text")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-a", "--all", action="store_true",
                      help="list sessions from every folder, not just this one")
    mode.add_argument("-r", "--read", metavar="ID",
                      help="read a session in the terminal (uses no Claude usage)")
    mode.add_argument("-w", "--html", metavar="ID",
                      help="read a session in your browser, answers fold open/closed")
    mode.add_argument("-o", "--open", metavar="ID",
                      help="continue a session in Claude Code, in its own folder")
    parser.add_argument("-n", type=positive_int, default=30, metavar="N",
                        help="how many sessions to list (default 30)")
    parser.add_argument("--show-empty", action="store_true",
                        help="also list sessions where you typed no prompt")
    parser.add_argument("--plain", action="store_true",
                        help="plain list in a pager instead of the menu")
    parser.add_argument("--no-git", action="store_true",
                        help="with --open: skip the Git check")
    args = parser.parse_args()

    if args.filter and not args.all:
        parser.error("a filter text only works together with --all")
    if args.no_git and not args.open:
        parser.error("--no-git only works together with --open")
    if args.plain and (args.read or args.html or args.open):
        parser.error("--plain only works when listing sessions")
    if not ROOT.exists():
        sys.exit(f"No sessions folder found at {ROOT}")

    if args.read:
        read_mode(args.read)
    elif args.html:
        html_mode(args.html)
    elif args.open:
        open_mode(args.open, check_git=not args.no_git)
    else:
        list_mode(args)


if __name__ == "__main__":
    main()
