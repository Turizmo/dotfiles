#!/usr/bin/env python3
"""Render the QMK keymap in keymap.c as a PNG cheat sheet.

Usage: qmk-keymap-render.py [keymap.c] [out.png]
"""
import re
import subprocess
import sys
from pathlib import Path

KEYMAP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "/home/turizmo/MEGA/Prosjekter/qmk_firmware/git/keyboards/handwired/"
    "dactyl_manuform_turizmo/4x5_turizmo/keymaps/default/keymap.c")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / ".cache/qmk-keymap.png"

# One entry per row of the LAYOUT macro: which columns the keys sit in,
# on the left half and on the right half. Column 0 is the outer left column.
ROWS = [
    ([0, 1, 2, 3, 4], [0, 1, 2, 3, 4]),
    ([0, 1, 2, 3, 4], [0, 1, 2, 3, 4]),
    ([0, 1, 2, 3, 4], [0, 1, 2, 3, 4]),
    ([1, 2], [2, 3]),          # macro row: under the S/D and K/L columns
    ([3.5, 4.5, 5.5], [-1.5, -0.5, 0.5]),  # thumb row 1, points inward
    ([3.5, 4.5, 5.5], [-1.5, -0.5, 0.5]),  # thumb row 2, points inward
]

# Shift per row, in key heights. The thumb cluster sits half a row lower
# than the macro row, so it keeps a half key margin below M.
ROW_DROP = {4: -0.5, 5: -0.5}

LABELS = {
    "XXXXXXX": "", "_______": "▽", "KC_NO": "", "KC_TRNS": "▽",
    "NO_AE": "Æ", "NO_OSTR": "Ø", "NO_ARNG": "Å",
    "NO_QUES": "?", "NO_QUOT": "'", "NO_DQUO": '"', "NO_EXLM": "!",
    "NO_GRV": "`", "NO_TILD": "~", "NO_CIRC": "^", "NO_AT": "@",
    "NO_LBRC": "[", "NO_RBRC": "]", "NO_LCBR": "{", "NO_RCBR": "}",
    "NO_LPRN": "(", "NO_RPRN": ")", "NO_LABK": "&lt;", "NO_RABK": "&gt;",
    "NO_SLSH": "/", "NO_BSLS": "\\", "NO_PIPE": "|", "NO_AMPR": "&amp;",
    "NO_EQL": "=", "NO_PLUS": "+", "NO_MINS": "-", "NO_UNDS": "_",
    "NO_ASTR": "*", "NO_HASH": "#", "NO_DLR": "$", "NO_PERC": "%",
    "KC_COMM": ",", "KC_DOT": ".", "KC_PERC": "%",
    "KC_SPC": "Space", "KC_BSPC": "Bksp", "KC_ENT": "Enter", "KC_ESC": "Esc",
    "KC_TAB": "Tab", "KC_DEL": "Del", "KC_INS": "Ins", "KC_APP": "Menu",
    "KC_LCTL": "Ctrl", "KC_RCTL": "Ctrl", "KC_LALT": "Alt", "KC_LGUI": "Gui",
    "KC_LSFT": "Shift", "KC_PSCR": "PrtSc", "KC_PAUSE": "Pause",
    "KC_HOME": "Home", "KC_END": "End", "KC_PGUP": "PgUp", "KC_PGDN": "PgDn",
    "KC_LEFT": "←", "KC_RIGHT": "→", "KC_UP": "↑", "KC_DOWN": "↓",
    "KC_MPRV": "⏮", "KC_MNXT": "⏭", "KC_MPLY": "⏯",
    "KC_VOLD": "Vol-", "KC_VOLU": "Vol+",
    "QK_BOOT": "BOOT", "LANG_TG": "NO/US",
    "GUI_H": "H", "GUI_J": "J", "GUI_K": "K", "GUI_L": "L",
    "DM_REC1": "Rec1", "DM_REC2": "Rec2", "DM_PLY1": "Play1", "DM_PLY2": "Play2",
    "R_TL_ACL": "Speed", "R_SET_1": "x40", "R_SET_2": "x20",
    "R_SET_3": "x10", "R_SET_4": "x5",
    "R_WH_L": "Wh ←", "R_WH_R": "Wh →", "R_WH_U": "Wh ↑", "R_WH_D": "Wh ↓",
    "R_MS_L": "Ms ←", "R_MS_R": "Ms →", "R_MS_U": "Ms ↑", "R_MS_D": "Ms ↓",
    "R_LEFT": "←", "R_RIGHT": "→", "R_UP": "↑", "R_DOWN": "↓",
    "MS_BTN1": "Btn1", "MS_BTN2": "Btn2", "MS_BTN3": "Btn3",
    "MS_BTN4": "Btn4", "MS_BTN5": "Btn5",
}

LAYER_NAMES = {}


def label(code):
    code = code.strip()
    if code in LABELS:
        return LABELS[code]
    m = re.fullmatch(r"LT\((\d+),\s*(\w+)\)", code)
    if m:
        return f"{label(m.group(2))}/L{m.group(1)}"
    m = re.fullmatch(r"(?:KC|NO)_(\w+)", code)
    if m:
        return m.group(1)
    return code


def split_keys(body):
    keys, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            keys.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        keys.append(cur.strip())
    return keys


def parse_layers(text):
    layers = []
    for m in re.finditer(r"\[(\d+)\]\s*=\s*LAYOUT\(", text):
        idx, start = int(m.group(1)), m.end()
        depth, i = 1, start
        while depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        comment = re.match(r"\s*//\s*(.+)", body)
        if comment:
            LAYER_NAMES[idx] = comment.group(1).strip()
        body = re.sub(r"//[^\n]*", "", body)
        layers.append((idx, split_keys(body)))
    return layers


KEY_W, KEY_H, GAP = 74, 50, 6
# Space between the halves, in key columns. It holds the two thumb clusters.
HALF_GAP = 3.5 * (KEY_W + GAP)
PAD, TITLE_H = 18, 30


def layer_svg(keys, x0, y0):
    out, i, y = [], 0, y0
    for r, (left, right) in enumerate(ROWS):
        drop = ROW_DROP.get(r, 0) * (KEY_H + GAP)
        row = keys[i:i + len(left) + len(right)]
        i += len(row)
        spots = [(c, 0) for c in left] + [(c, 1) for c in right]
        for (col, half), code in zip(spots, row):
            kx = x0 + (col + 5 * half) * (KEY_W + GAP) + (HALF_GAP if half else 0)
            ky = y + drop
            txt = label(code)
            size = 15 if len(txt) <= 5 else 11
            out.append(
                f'<rect x="{kx:.0f}" y="{ky:.0f}" width="{KEY_W}" height="{KEY_H}" rx="7" '
                f'class="key"/>'
                f'<text x="{kx + KEY_W / 2:.0f}" y="{ky + KEY_H / 2 + 5:.0f}" '
                f'font-size="{size}" class="lbl">{txt}</text>')
        y += KEY_H + GAP
    return "\n".join(out), y


def main():
    layers = parse_layers(KEYMAP.read_text())
    lw = 5 * 2 * (KEY_W + GAP) + HALF_GAP
    lh = (len(ROWS) + max([0] + list(ROW_DROP.values()))) * (KEY_H + GAP) + TITLE_H
    cols = 2
    rows = (len(layers) + cols - 1) // cols
    w = PAD + cols * (lw + PAD)
    h = PAD + rows * (lh + PAD)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}">',
        '<style>'
        'rect.bg{fill:#1c1f26}'
        'rect.key{fill:#2b303b;stroke:#454c5c;stroke-width:1}'
        'text{font-family:"DejaVu Sans",sans-serif;fill:#e6e9ef;text-anchor:middle}'
        'text.title{font-size:17px;font-weight:bold;fill:#8fb6ff;text-anchor:start}'
        '</style>',
        f'<rect class="bg" x="0" y="0" width="{w:.0f}" height="{h:.0f}"/>']
    for n, (idx, keys) in enumerate(layers):
        x0 = PAD + (n % cols) * (lw + PAD)
        y0 = PAD + (n // cols) * (lh + PAD)
        name = LAYER_NAMES.get(idx, f"Layer {idx}")
        parts.append(f'<text class="title" x="{x0}" y="{y0 + 18}">{idx}: {name}</text>')
        body, _ = layer_svg(keys, x0, y0 + TITLE_H)
        parts.append(body)
    parts.append("</svg>")
    svg = "\n".join(parts)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsvg-convert", "-o", str(OUT)], input=svg.encode(), check=True)
    print(OUT)


if __name__ == "__main__":
    main()
