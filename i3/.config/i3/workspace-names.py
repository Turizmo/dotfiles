#!/usr/bin/env python3
# Rename i3 workspaces to "<num>: <app> <app> ..." so the bar shows what is on each one.
# Stdlib only: listens to events via `i3-msg -t subscribe` and renames via `i3-msg`.
# Keybindings must use `workspace number N` so they still match after a rename.

import functools
import json
import os
import re
import subprocess
import time

MAX_APP_LEN = 16  # cut long class names like "org.gnome.Nautilus"
MAX_APPS = 4      # show at most this many apps, then "+N"
SEPARATOR = " | "  # between windows, in the tile's text color
# i3bar can't draw between its buttons, so the buttons are made invisible
# (bar colors in the i3 config) and each name draws its own tile with a Pango
# background, followed by a "|" outside the tile. Needs strip_workspace_numbers
# yes: the name is "N:<tile>", and i3bar hides the "N:".
DESKTOP_SEPARATOR = "    "  # empty space
TILE = {  # (background, text) like the old i3bar colors; None = bar background
    "focused": ("#b0b5bd", "#383c4a"),
    "visible": ("#8b8b8b", "#383c4a"),  # shown on another monitor
    "urgent": ("#e53935", "#ffffff"),
    "other": (None, "#b0b5bd"),
}
# For these, show what runs inside instead of the terminal's own name: the repo
# of a Claude Code session (found via /proc), else the command from the window
# title (set by ~/.bashrc).
TERMINALS = {"xfce4-terminal", "ghostty", "alacritty", "kitty", "xterm"}

# Nerd Font icons (the bar font must include "Symbols Nerd Font"), picked and
# colored to look like the Qogir icons rofi shows. i3bar renders Pango markup.
# Known apps show only the icon; unknown apps show their name.
# No color = use the button's text color (white icons vanish on the light focused button).
def icon(glyph, color=None):
    return f"<span foreground='{color}'>{glyph}</span>" if color else glyph


ICONS = {
    "zen": icon("\U000f0e95"),                    # nf-md-circle_double: white rings
    "firefox": icon("\U000f0e95"),
    "chromium": icon("\U000f043e", "#5294e2"),    # nf-md-radiobox_marked: blue ring
    "thunar": icon("\U000f024b", "#8a7ae0"),      # nf-md-folder: purple folder
    "obsidian": icon("\U000f01c8", "#9b7cf0"),    # nf-md-diamond: purple gem
    "openscad": icon("\U000f01a6", "#f2c037"),    # nf-md-cube: yellow cube
    "orcaslicer": icon("\U000f18b4"),             # nf-md-dolphin: the orca
    "openhantek": icon("\U000f095b", "#f5c211"),  # nf-md-sine_wave: yellow wave
    "libreoffice-writer": icon("\U000f022c", "#3b7ddd"),   # blue W document
    "libreoffice-calc": icon("\U000f021b", "#43a940"),     # green X document
    "libreoffice-impress": icon("\U000f0227", "#ea6a1f"),  # orange P document
}
# Terminals show icon + text: Claude sessions get its orange spark, nvim its logo
TERMINAL_ICON = icon("\U000f018d")                # nf-md-console: dark box with >_
CLAUDE_ICON = icon("\U000f06c4", "#d97757")       # nf-md-asterisk
COMMAND_ICONS = {
    "nvim": icon("\uf36f", "#57a143"),            # nf-linux-neovim: green N
    "vim": icon("\ue62b", "#57a143"),             # nf-custom-vim
}


def i3(*args):
    return subprocess.run(["i3-msg", *args], capture_output=True, text=True, check=True).stdout


@functools.lru_cache(maxsize=64)
def repo_name(cwd):
    """Name of the git repo containing cwd, else the folder name."""
    try:
        cwd = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True, timeout=2).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return os.path.basename(cwd.rstrip("/")) or cwd


def claude_sessions():
    """Map terminal X window id -> repos of the Claude Code sessions running in it.
    Terminals export WINDOWID to their shells, and claude inherits it."""
    sessions = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() != "claude":
                    continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = dict(v.split(b"=", 1) for v in f.read().split(b"\0") if b"=" in v)
            wid = int(env[b"WINDOWID"])
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except (OSError, KeyError, ValueError):
            continue
        repos = sessions.setdefault(wid, [])
        repo = repo_name(cwd)
        if repo not in repos:
            repos.append(repo)
    return sessions


def clean(text):
    text = text.replace('"', "").replace(":", "")[:MAX_APP_LEN]
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def labels(node, sessions):
    """Bar labels for one window: icon only for known apps, icon + text in terminals."""
    if node["window"] in sessions:
        return [f"{CLAUDE_ICON} {clean(repo)}" for repo in sessions[node["window"]]]
    props = node.get("window_properties") or {}
    name = props.get("class") or props.get("instance") or node.get("name") or "?"
    name = name.split(".")[-1].lower()
    if name in TERMINALS:
        return [terminal_label(node.get("name") or "")]
    return [ICONS.get(name) or clean(name)]


def terminal_label(title):
    words = re.sub(r"^Terminal - ", "", title).split()
    # user@host:dir is the idle-prompt title, so only the shell is running
    if not words or re.match(r"\S+@\S+:", words[0]):
        return f"{TERMINAL_ICON} bash"
    if not re.search(r"\w", words[0]):
        # status glyph title ("✳ <task>") but no session found in /proc
        return f"{CLAUDE_ICON} claude"
    cmd = words[0].lower()
    return f"{COMMAND_ICONS.get(cmd, TERMINAL_ICON)} {clean(cmd)}"


def windows(node):
    if node.get("window"):
        yield node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from windows(child)


def workspaces(node):
    if node.get("type") == "workspace":
        yield node
        return
    for child in node.get("nodes", []):
        yield from workspaces(child)


def update():
    tree = json.loads(i3("-t", "get_tree"))
    state = {}
    for ws in json.loads(i3("-t", "get_workspaces")):
        state[ws["num"]] = ("focused" if ws["focused"] else "urgent" if ws["urgent"]
                            else "visible" if ws["visible"] else "other")
    sessions = claude_sessions()
    shown = [ws for ws in workspaces(tree)
             if not ws["name"].startswith("__") and ws.get("num", -1) >= 0]
    last = {}  # no separator after the last desktop on each output (one bar each)
    for ws in shown:
        last[ws["output"]] = max(last.get(ws["output"], -1), ws["num"])
    for ws in shown:
        apps = []
        for win in windows(ws):
            for name in labels(win, sessions):
                if name not in apps:
                    apps.append(name)
        if len(apps) > MAX_APPS:
            apps = apps[:MAX_APPS] + [f"+{len(apps) - MAX_APPS}"]
        text = f"{ws['num']}: {SEPARATOR.join(apps)}" if apps else str(ws["num"])
        bg, fg = TILE[state.get(ws["num"], "other")]
        bg = f" background='{bg}'" if bg else ""
        new = f"{ws['num']}:<span{bg} foreground='{fg}'> {text} </span>"
        if ws["num"] != last[ws["output"]]:
            new += DESKTOP_SEPARATOR
        if new != ws["name"]:
            i3(f'rename workspace "{ws["name"]}" to "{new}"')


def main():
    while True:
        try:
            update()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return  # i3 is gone (logout), stop
        sub = subprocess.Popen(
            ["i3-msg", "-t", "subscribe", "-m", '["window","workspace"]'],
            stdout=subprocess.PIPE, text=True,
        )
        for line in sub.stdout:
            try:
                update()
            except subprocess.CalledProcessError:
                pass
        # subscription closed, e.g. by an i3 restart; reconnect
        sub.wait()
        time.sleep(1)


if __name__ == "__main__":
    main()
