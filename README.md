# claude-course

A personal, beginner-friendly course for learning [Claude Code](https://code.claude.com/docs), taught *inside* Claude Code, plus a small tool I built along the way.

## claude-sessions (the tool)

List, read, and reopen your saved Claude Code sessions, with no usage cost.

```bash
git clone https://github.com/AungChanMinMarch/claude-course.git
cd claude-course/claude-sessions
./install.sh
```

Full instructions: **[claude-sessions/README.md](claude-sessions/README.md)**

## The course

| File | What it is |
| --- | --- |
| `CLAUDE.md` | Instructions that make Claude Code act as my teacher (lesson format, rules, syllabus) |
| `PROGRESS.md` | A recap after each finished lesson |

The course is written for one learner (a master's student in computer engineering, writing a journal paper), but you can copy `CLAUDE.md` as a starting point for your own.

## Layout

```
claude-course/
├── README.md
├── CLAUDE.md
├── PROGRESS.md
└── claude-sessions/
    ├── README.md
    ├── install.sh
    └── claude_sessions.py
```
