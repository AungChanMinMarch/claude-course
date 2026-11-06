#!/usr/bin/env bash
# Installs the `claude-sessions` command by linking it into ~/.local/bin.
# Safe to run again: it only replaces its own link. Use --uninstall to remove it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/claude_sessions.py"
bin_dir="$HOME/.local/bin"
link="$bin_dir/claude-sessions"

if [ "${1:-}" = "--uninstall" ]; then
    if [ -L "$link" ]; then
        rm "$link"
        echo "Removed $link"
    else
        echo "Nothing to remove: $link is not a link."
    fi
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 was not found. Please install Python 3 first." >&2
    exit 1
fi

if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "Error: $link already exists and is not a link. Not touching it." >&2
    exit 1
fi

mkdir -p "$bin_dir"
chmod +x "$script"
ln -sfn "$script" "$link"
echo "Installed: $link -> $script"

case ":$PATH:" in
    *":$bin_dir:"*) echo "Done. Try:  claude-sessions --help" ;;
    *)
        echo
        echo "Note: $bin_dir is not in your PATH yet. Add this line to ~/.bashrc:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo "Then open a new terminal and run:  claude-sessions --help"
        ;;
esac
