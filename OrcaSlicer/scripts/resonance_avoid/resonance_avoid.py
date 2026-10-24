#!/usr/bin/env python3
"""resonance_avoid.py - OrcaSlicer post-processor: no move cruises inside the resonance band.

Usage (Orca appends the G-code path as the last argument):
    python3 resonance_avoid.py [--dry-run] [--set key=value ...] <file.gcode>

Orca's own resonance avoidance only changes outer walls, and only the commanded
speed. Short moves still cruise in the band: with minimum_cruise_ratio = 0.5,
Klipper plans their top speed as if accel were half, so a 5 mm infill line at
F9000 cruises at about 110 mm/s.

How it works:
  1. Simulate the processed region with a port of Klipper's planner
     (toolhead.py Move.calc_junction + LookAheadQueue.flush): junction
     deviation, centripetal limit, minimum_cruise_ratio, extruder
     instantaneous_corner_velocity and the Z limits. Accel, velocity,
     square_corner_velocity and minimum_cruise_ratio are tracked from
     SET_VELOCITY_LIMIT / M204 in the G-code.
  2. Every XY move (print and travel) whose planned cruise speed is inside
     (band_min, band_max] and that holds it over some distance gets
     F = band_min. The next move gets its original F back.
  3. Repeat until no new move lands in the band. Slowing a move can pull its
     neighbours into the band, so this takes a few passes.

Settings (from the G-code config block, set in Printer settings):
    min_resonance_avoidance_speed, max_resonance_avoidance_speed   the band
    default_acceleration                                           start accel
Orca's "Resonance avoidance" checkbox is the on/off switch. Orca turns it off
for its calibration prints, so their speeds stay as Orca made them. Orca's own
outer wall handling still runs; this script then covers every other move.
Printer constants (printer Notes, optional, defaults match printer.cfg):
    resavoid_min_cruise_ratio = 0.5
    resavoid_square_corner_velocity = 5
    resavoid_max_velocity = 300
    resavoid_max_z_velocity = 15
    resavoid_max_z_accel = 350
    resavoid_instantaneous_corner_velocity = 1

Exit codes: 0 ok (or already processed), 1 bad input. On error the file is untouched.
Python 3 stdlib only.
"""

import math
import os
import re
import sys
import tempfile

TAG = "; RESONANCE_AVOID"
START_MARK = "; MZ FLOW TEMP START"
END_MARK = "; MZ FLOW TEMP END"
MIN_CRUISE_D = 0.05    # mm, shorter cruise parts are a pass-through, not a hold
MAX_PASSES = 20
DEFAULTS = {
    "min_cruise_ratio": 0.5,
    "square_corner_velocity": 5.0,
    "max_velocity": 300.0,
    "max_z_velocity": 15.0,
    "max_z_accel": 350.0,
    "instantaneous_corner_velocity": 1.0,
}


class ResAvoidError(Exception):
    pass


# --------------------------------------------------------------------------- config

def first_value(raw):
    raw = raw.strip().strip('"')
    return raw.split(",")[0].split(";")[0].strip()


def read_config(lines):
    cfg = {}
    in_block = False
    for line in lines:
        s = line.strip()
        if s == "; CONFIG_BLOCK_START":
            in_block = True
            continue
        if s == "; CONFIG_BLOCK_END":
            in_block = False
            continue
        if in_block and s.startswith("; ") and " = " in s:
            k, v = s[2:].split(" = ", 1)
            cfg[k.strip()] = v
    return cfg


def parse_notes(text):
    out = {}
    for m in re.finditer(r"resavoid_(\w+?)\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)", text):
        out[m.group(1)] = float(m.group(2))
    return out


def get_settings(cfg, overrides):
    def num(key):
        if key in overrides:
            return float(overrides[key])
        if key not in cfg or first_value(cfg[key]) == "":
            raise ResAvoidError(f"missing '{key}' in the G-code config block")
        try:
            return float(first_value(cfg[key]))
        except ValueError:
            raise ResAvoidError(f"'{key}' is not a number: {cfg[key]!r}")

    st = dict(DEFAULTS)
    st.update(parse_notes(cfg.get("printer_notes", "")))
    for k, v in overrides.items():
        if k.startswith("resavoid_"):
            st[k[len("resavoid_"):]] = float(v)
    st["lo"] = num("min_resonance_avoidance_speed")
    st["hi"] = num("max_resonance_avoidance_speed")
    if not 0 < st["lo"] < st["hi"]:
        raise ResAvoidError("need 0 < min_resonance_avoidance_speed < max_resonance_avoidance_speed")
    try:
        st["accel"] = float(first_value(cfg.get("default_acceleration", ""))) or 5000.0
    except ValueError:
        st["accel"] = 5000.0
    return st


def region(lines):
    r0 = r1 = None
    for i, line in enumerate(lines):
        s = line.strip()
        if r0 is None and s == START_MARK:
            r0 = i + 1
        elif s == END_MARK:
            r1 = i
    if r0 is not None and r1 is not None and r0 < r1:
        return r0, r1
    r0 = next((i for i, l in enumerate(lines) if l.startswith(";LAYER_CHANGE")), None)
    r1 = next((i for i, l in enumerate(lines) if l.strip() == "; EXECUTABLE_BLOCK_END"), len(lines))
    if r0 is None:
        raise ResAvoidError("no ';LAYER_CHANGE' and no flow temp markers found")
    return r0, r1


# --------------------------------------------------------------------------- planner

class Move:
    __slots__ = ("idx", "xy", "is_kin", "move_d", "axes_r", "accel", "jd",
                 "max_start_v2", "max_cruise_v2", "delta_v2", "next_junction_v2",
                 "max_mcr_start_v2", "mcr_delta_v2", "cruise_v", "cruise_d", "t")

    def __init__(self, idx, d, speed, th, st):
        # toolhead.py Move.__init__ + corexy / extruder check_move
        self.idx = idx
        self.accel = th["accel"]
        self.jd = th["jd"]
        velocity = min(speed, th["vel"])
        self.is_kin = True
        move_d = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        self.xy = bool(d[0] or d[1])
        if move_d < 1e-9:
            move_d = abs(d[3])
            inv = 1.0 / move_d if move_d else 0.0
            self.accel = 99999999.9
            velocity = speed
            self.is_kin = False
            self.axes_r = (0.0, 0.0, 0.0, d[3] * inv)
        else:
            inv = 1.0 / move_d
            self.axes_r = (d[0] * inv, d[1] * inv, d[2] * inv, d[3] * inv)
        self.move_d = move_d
        self.max_start_v2 = 0.0
        self.max_cruise_v2 = velocity * velocity
        self.delta_v2 = 2.0 * move_d * self.accel
        self.next_junction_v2 = 999999999.9
        self.max_mcr_start_v2 = 0.0
        self.mcr_delta_v2 = 2.0 * move_d * th["mcr_accel"]
        self.cruise_v = 0.0
        self.cruise_d = 0.0
        self.t = 0.0
        if self.is_kin and d[2]:
            z_ratio = move_d / abs(d[2])
            self.limit_speed(st["max_z_velocity"] * z_ratio, st["max_z_accel"] * z_ratio)

    def limit_speed(self, speed, accel):
        if speed * speed < self.max_cruise_v2:
            self.max_cruise_v2 = speed * speed
        self.accel = min(self.accel, accel)
        self.delta_v2 = 2.0 * self.move_d * self.accel
        self.mcr_delta_v2 = min(self.mcr_delta_v2, self.delta_v2)

    def calc_junction(self, prev, icv):
        if not self.is_kin or not prev.is_kin:
            return
        lim = [self.max_cruise_v2, prev.max_cruise_v2, prev.next_junction_v2,
               prev.max_start_v2 + prev.delta_v2]
        diff_r = self.axes_r[3] - prev.axes_r[3]
        if diff_r:
            lim.append((icv / abs(diff_r)) ** 2)
        max_start_v2 = min(lim)
        a, p = self.axes_r, prev.axes_r
        cos_t = -(a[0] * p[0] + a[1] * p[1] + a[2] * p[2])
        sin_d2 = math.sqrt(max(0.5 * (1.0 - cos_t), 0.0))
        cos_d2 = math.sqrt(max(0.5 * (1.0 + cos_t), 0.0))
        one_minus = 1.0 - sin_d2
        if one_minus > 0.0 and cos_d2 > 0.0:
            r_jd = sin_d2 / one_minus
            q_tan = 0.25 * sin_d2 / cos_d2
            max_start_v2 = min(max_start_v2,
                               r_jd * self.jd * self.accel,
                               r_jd * prev.jd * prev.accel,
                               self.delta_v2 * q_tan,
                               prev.delta_v2 * q_tan)
        self.max_start_v2 = max_start_v2
        self.max_mcr_start_v2 = min(max_start_v2, prev.max_mcr_start_v2 + prev.mcr_delta_v2)

    def set_junction(self, start_v2, cruise_v2, end_v2):
        half_inv = 0.5 / self.accel
        accel_d = (cruise_v2 - start_v2) * half_inv
        decel_d = (cruise_v2 - end_v2) * half_inv
        start_v, end_v = math.sqrt(start_v2), math.sqrt(end_v2)
        self.cruise_v = cruise_v = math.sqrt(cruise_v2)
        self.cruise_d = self.move_d - accel_d - decel_d
        if cruise_v > 0:
            self.t = (accel_d / ((start_v + cruise_v) * 0.5) + self.cruise_d / cruise_v
                      + decel_d / ((end_v + cruise_v) * 0.5))


def flush(queue):
    """LookAheadQueue.flush() for a queue that ends in a full stop."""
    n = len(queue)
    info = [None] * n
    next_start_v2 = next_mcr_start_v2 = peak_cruise_v2 = 0.0
    pending = 0
    for i in range(n - 1, -1, -1):
        m = queue[i]
        reachable = next_start_v2 + m.delta_v2
        start_v2 = min(m.max_start_v2, reachable)
        cruise_v2 = None
        pending += 1
        reach_mcr = next_mcr_start_v2 + m.mcr_delta_v2
        mcr_start = min(m.max_mcr_start_v2, reach_mcr)
        if mcr_start < reach_mcr:
            if mcr_start + m.mcr_delta_v2 > next_mcr_start_v2 or pending > 1:
                peak_cruise_v2 = (mcr_start + reach_mcr) * 0.5
            cruise_v2 = min((start_v2 + reachable) * 0.5, m.max_cruise_v2, peak_cruise_v2)
            pending = 0
        info[i] = (start_v2, cruise_v2, next_start_v2)
        next_start_v2 = start_v2
        next_mcr_start_v2 = mcr_start
    prev_cruise_v2 = 0.0
    for i in range(n):
        start_v2, cruise_v2, nxt = info[i]
        if cruise_v2 is None:
            cruise_v2 = min(prev_cruise_v2, start_v2)
        queue[i].set_junction(min(start_v2, cruise_v2), cruise_v2, min(nxt, cruise_v2))
        prev_cruise_v2 = cruise_v2


AXIS_RE = re.compile(r"([XYZEF])\s*([-+]?[0-9]*\.?[0-9]+)", re.I)
PARAM_RE = re.compile(r"\b([A-Z_]+)=([-+]?[0-9]*\.?[0-9]+)", re.I)
STOP_RE = re.compile(r"\s*(G4|G28|M400|M109|M190|M191|TEMPERATURE_WAIT|M600|PAUSE)\b", re.I)


def code_part(line):
    return line.split(";", 1)[0].strip()


def simulate(lines, r0, r1, st, caps):
    """Plan every move in [r0, r1). caps: line indices forced to F = lo.

    Returns (planned XY moves, effective F per motion line index).
    """
    lo_f = st["lo"] * 60.0
    th = {"accel": st["accel"], "vel": st["max_velocity"],
          "scv": st["square_corner_velocity"], "mcr": st["min_cruise_ratio"]}

    def update_th():
        th["jd"] = th["scv"] ** 2 * (math.sqrt(2.0) - 1.0) / th["accel"]
        th["mcr_accel"] = th["accel"] * (1.0 - th["mcr"])

    update_th()
    pos = [0.0, 0.0, 0.0, 0.0]
    rel_xyz = False
    rel_e = True
    feed = None
    eff_f = {}
    planned = []
    queue = []
    icv = st["instantaneous_corner_velocity"]

    def stop():
        if queue:
            flush(queue)
            planned.extend(m for m in queue if m.xy)
            del queue[:]

    for i in range(r0, r1):
        c = code_part(lines[i])
        if not c:
            continue
        word = c.split(None, 1)[0].upper()
        if word in ("G0", "G1"):
            vals = {k.upper(): float(v) for k, v in AXIS_RE.findall(c[len(word):])}
            if "F" in vals:
                feed = vals["F"]
            f = lo_f if i in caps else feed
            eff_f[i] = feed
            new = list(pos)
            for j, ax in enumerate("XYZ"):
                if ax in vals:
                    new[j] = pos[j] + vals[ax] if rel_xyz else vals[ax]
            if "E" in vals:
                new[3] = pos[3] + vals["E"] if rel_e else vals["E"]
            d = [new[j] - pos[j] for j in range(4)]
            pos = new
            if not any(d) or f is None:
                continue
            m = Move(i, d, f / 60.0, th, st)
            if queue:
                m.calc_junction(queue[-1], icv)
            queue.append(m)
        elif word in ("G2", "G3"):
            raise ResAvoidError("G2/G3 arcs are not supported, turn off arc fitting")
        elif word == "G90":
            rel_xyz = False
        elif word == "G91":
            rel_xyz = True
        elif word == "M82":
            rel_e = False
        elif word == "M83":
            rel_e = True
        elif word == "G92":
            for k, v in AXIS_RE.findall(c[3:]):
                k = k.upper()
                if k in "XYZE":
                    pos["XYZE".index(k)] = float(v)
        elif word == "SET_VELOCITY_LIMIT":
            p = {k.upper(): float(v) for k, v in PARAM_RE.findall(c)}
            if "VELOCITY" in p:
                th["vel"] = p["VELOCITY"]
            if "ACCEL" in p:
                th["accel"] = p["ACCEL"]
            if "SQUARE_CORNER_VELOCITY" in p:
                th["scv"] = p["SQUARE_CORNER_VELOCITY"]
            if "MINIMUM_CRUISE_RATIO" in p:
                th["mcr"] = p["MINIMUM_CRUISE_RATIO"]
            elif "ACCEL_TO_DECEL" in p:
                th["mcr"] = max(0.0, 1.0 - p["ACCEL_TO_DECEL"] / th["accel"])
            update_th()
        elif word == "M204":
            p = {k.upper(): float(v) for k, v in re.findall(r"([SPT])([0-9.]+)", c[4:], re.I)}
            if "S" in p:
                th["accel"] = p["S"]
            elif "P" in p and "T" in p:
                th["accel"] = min(p["P"], p["T"])
            update_th()
        elif STOP_RE.match(c):
            stop()
    stop()
    return planned, eff_f


def find_caps(lines, r0, r1, st):
    caps = set()
    for n_pass in range(1, MAX_PASSES + 1):
        planned, eff_f = simulate(lines, r0, r1, st, caps)
        new = {m.idx for m in planned
               if st["lo"] + 0.01 < m.cruise_v <= st["hi"] + 0.01
               and m.cruise_d > MIN_CRUISE_D and m.idx not in caps}
        if not new:
            return caps, planned, eff_f, n_pass
        caps |= new
    raise ResAvoidError(f"did not settle after {MAX_PASSES} passes")


def move_time(planned):
    return sum(m.t for m in planned)


# --------------------------------------------------------------------------- main

def set_f(line, f, nl):
    """Replace or add the F word on a G0/G1 line, keep the comment."""
    body, sep, comment = line.rstrip("\r\n").partition(";")
    body = re.sub(r"\s*F[-+]?[0-9]*\.?[0-9]+", "", body, flags=re.I).rstrip()
    out = f"{body} F{f:.0f}"
    if sep:
        out += " ;" + comment
    return out + nl


def process(path, dry_run, overrides):
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        lines = fh.readlines()
    if any(l.startswith(TAG + " START") for l in lines):
        print("resonance_avoid: file already processed, nothing to do")
        return 0
    cfg = read_config(lines)
    if first_value(overrides.get("resonance_avoidance", cfg.get("resonance_avoidance", "0"))) != "1":
        # Off in the printer preset, or a calibration print (Orca turns it off there).
        print("resonance_avoid: resonance_avoidance is off, nothing to do")
        return 0
    st = get_settings(cfg, overrides)
    r0, r1 = region(lines)
    before, _ = simulate(lines, r0, r1, st, set())
    caps, after, eff_f, passes = find_caps(lines, r0, r1, st)
    in_band = sum(1 for m in before if st["lo"] + 0.01 < m.cruise_v <= st["hi"] + 0.01
                  and m.cruise_d > MIN_CRUISE_D)

    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    out = list(lines)
    motion = sorted(eff_f)
    restore = 0
    for k, i in enumerate(motion):
        if i in caps:
            out[i] = set_f(lines[i], st["lo"] * 60.0, nl)
        elif k and motion[k - 1] in caps and eff_f[i] is not None:
            # The capped line changed the modal F; give this line its own back.
            if not any(k.upper() == "F" for k, _ in AXIS_RE.findall(code_part(lines[i]))):
                out[i] = set_f(lines[i], eff_f[i], nl)
                restore += 1

    added = move_time(after) - move_time(before)
    summary = [
        f"{TAG} START",
        f"; band = {st['lo']:.0f}-{st['hi']:.0f} mm/s  min_cruise_ratio = {st['min_cruise_ratio']}"
        f"  scv = {st['square_corner_velocity']}",
        f"; moves cruising in band before = {in_band}  capped to {st['lo']:.0f} mm/s = {len(caps)}"
        f"  passes = {passes}  F restored = {restore}",
        f"; XY move time {move_time(before) / 60:.1f} min, added {added:.0f} s",
        f"{TAG} END",
    ]
    ins = 0
    for i, line in enumerate(out):
        if line.strip() == "; HEADER_BLOCK_END":
            ins = i + 1
            break
    out[ins:ins] = [s + nl for s in summary]

    for s in summary[1:-1]:
        print("resonance_avoid" + s[1:])
    if dry_run:
        print("resonance_avoid: dry run, file not written")
        return 0

    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".resonance_avoid.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.writelines(out)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return 0


def main(argv):
    dry = False
    overrides = {}
    args = []
    it = iter(argv)
    for a in it:
        if a == "--dry-run":
            dry = True
        elif a == "--set":
            kv = next(it, "")
            if "=" not in kv:
                sys.stderr.write("resonance_avoid: --set needs key=value\n")
                return 1
            k, v = kv.split("=", 1)
            overrides[k.strip()] = v.strip()
        else:
            args.append(a)
    if not args:
        sys.stderr.write(__doc__)
        return 1
    path = args[-1]
    if not os.path.isfile(path):
        sys.stderr.write(f"resonance_avoid: file not found: {path}\n")
        return 1
    try:
        return process(path, dry, overrides)
    except ResAvoidError as e:
        sys.stderr.write(f"resonance_avoid: ERROR: {e}. File not modified.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
