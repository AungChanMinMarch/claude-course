# claude-sessions

A small terminal tool to **list, read, and reopen your saved [Claude Code](https://code.claude.com/docs) sessions**.

- Listing and reading use **no Claude usage**. Nothing is sent to Claude.
- Your session files are **never changed** (the only exception is the `d` key, which *moves* a session to a trash folder, so you can put it back).
- One file, **Python standard library only**. There is nothing to `pip install`.

## Requirements

- Linux, macOS, or Windows through WSL2 (the menu uses `curses`, which native Windows does not have)
- Python 3 (tested with 3.12)
- Git (only for the optional Git check when reopening a session)
- Claude Code installed, with at least one past session

## Install

```bash
git clone https://github.com/AungChanMinMarch/claude-course.git
cd claude-course/claude-sessions
./install.sh
```

The installer puts a link called `claude-sessions` in `~/.local/bin`. If that folder is not in your `PATH`, the installer tells you the one line to add to `~/.bashrc`.

Check that it works:

```bash
claude-sessions --help
```

Don't want to install anything? Run the file directly:

```bash
python3 claude_sessions.py
```

### Update

```bash
git pull
```

The link points to the file in your clone, so a pull is all you need.

### Uninstall

```bash
./install.sh --uninstall
```

## Everyday use

| Command | What it does |
| --- | --- |
| `claude-sessions` | Menu of sessions started in the current folder |
| `claude-sessions --all` | Menu of sessions from every folder |
| `claude-sessions --all thesis` | Only folders whose path contains "thesis" |
| `claude-sessions -n 50` | Show up to 50 sessions (default 30) |
| `claude-sessions --plain` | Plain list in a pager, no menu |
| `claude-sessions --show-empty` | Also show sessions where you typed no prompt |
| `claude-sessions --read 689c3e55` | Read a conversation in the terminal |
| `claude-sessions --html 689c3e55` | Read it in your browser; each answer folds open or closed |
| `claude-sessions --open 689c3e55` | Continue it in Claude Code, in the right folder |

For `--read`, `--html`, and `--open`, the first 8 characters of the session id are enough.

### Menu keys

| Key | Action |
| --- | --- |
| Up / Down | Move one session |
| PgUp / PgDn | Move one screen |
| Home / End | First / last session |
| a number | Jump to that session (type `1` then `2` for no. 12) |
| `o` | Open (continue) the highlighted session in Claude Code |
| `n` | Start a brand new session instead of continuing one. It starts in the current folder (with `--all`: in the highlighted session's folder). The Git check runs first |
| `r` | Read it in the terminal, then return to the menu |
| `h` | Open it in your browser as a saved file, then return to the menu. The file does not change afterwards |
| `w` | Open it as a live web page (a small server on your own computer, `127.0.0.1` only). After you ask Claude something new, refresh the browser tab to see it. The server stops when you quit the menu |
| `d` | Move it to the trash folder (asks y/n first) |
| `q` or Esc | Quit |

## Safety notes

**The trash.** `d` never deletes. It moves the session file to `~/claude-sessions-trash/<project-folder-name>/`. To put it back:

```bash
mv ~/claude-sessions-trash/<folder>/<id>.jsonl ~/.claude/projects/<folder>/
```

Some sessions also have a folder named `<id>`; move it back the same way.

**The Git check before `--open`.** Only when the folder is a Git repository, the tool:

- fetches (downloads news from the remote; changes none of your files);
- pulls with `--ff-only` if you have no local changes and the remote has new commits (it only moves forward, so no merge conflicts are possible);
- shows your uncommitted changes and asks what to do, if you have any;
- reminds you to push, if you have local commits that are not pushed.

It **never commits and never pushes** for you. Skip the check with `--no-git`.

## Known limits

- It reads Claude Code's internal session files in `~/.claude/projects/`. This is **not an official interface**, so a future Claude Code update may break it. If that happens, please open an issue.
- Session ids and previews come from your own machine only.

## Files

| File | Purpose |
| --- | --- |
| `claude_sessions.py` | The tool itself |
| `install.sh` | Links the tool as `claude-sessions` in `~/.local/bin` |
