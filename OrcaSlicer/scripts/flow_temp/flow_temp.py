#!/usr/bin/env python3
"""flow_temp.py - OrcaSlicer post-processor: nozzle temperature from upcoming volumetric flow.

Usage (Orca appends the G-code path as the last argument):
    python3 flow_temp.py [--dry-run] [--set key=value ...] <file.gcode>

How it works:
  1. Simulate every move in the processed region and estimate its time with a
     Klipper-style lookahead planner (trapezoids, junction deviation; accel and
     square_corner_velocity tracked from SET_VELOCITY_LIMIT / M204 in the
     G-code). Travel, retract, wipe and dwell are 0 flow.
  2. Put extruded volume on a 0.1 s grid. avg(t) = max(mean flow over [t, t+W),
     mean flow over [t-W, t)), W from window_seconds(). The forward part
     catches rises early, the trailing part keeps the target up until the flow
     has really dropped (no pre-cooling).
  3. target = low + (high - low) * min(avg, max_flow) / max_flow.
     Layer 1 is fixed at nozzle_temperature_initial_layer.
  4. Backward pass: cmd[i] = max(target[i], cmd[i+1] - dt / heat_s_per_c).
     Then cmd is shifted earlier by heat_delay_s (cmd[i] = max of cmd over
     [t, t + delay]), because the nozzle barely moves for that long after a
     new setpoint.
     Heating ramps therefore start early enough to reach the target before
     a high-flow section begins. No pre-cooling: drops just lower the target.
  5. Emit "M104 S<int>" (never M109) before the move where the rounded-up
     commanded temperature for the next W seconds changes, at most once per W.
     Other M104 lines in the region are commented out. Feedrates are untouched.

On/off: the script runs only when the filament Notes have a line "flowtemp = 1"
and resonance_avoidance is on (Orca turns that off in calibration prints).
Otherwise it leaves the file untouched, so it can sit in every process preset.

Settings (printer Notes, one per line, spaces around '=' optional):
    flowtemp_heat_s_per_c = 0.5     required: seconds to heat the nozzle 1 C
    flowtemp_heat_delay_s = 3.5     optional: seconds before the nozzle starts to rise (default 0)
Filament preset fields: nozzle_temperature_range_low/high,
filament_max_volumetric_speed, nozzle_temperature_initial_layer, filament_diameter.

Exit codes: 0 ok (or already processed), 1 bad input. On error the file is untouched.
Python 3 stdlib only.
"""

import bisect
from collections import deque
import math
import os
import re
import sys
import tempfile

TAG = "; FLOW_TEMP"
START_MARK = "; MZ FLOW TEMP START"
END_MARK = "; MZ FLOW TEMP END"
GRID_DT = 0.1          # s, time grid resolution
WINDOW_MIN = 1.0       # s
WINDOW_MAX = 10.0      # s
WINDOW_FRACTION = 0.25  # share of the full temperature swing, see window_seconds()


class FlowTempError(Exception):
    pass


def window_seconds(heat_s_per_c, t_low, t_high):
    """Averaging window W (s).

    W = clamp(WINDOW_FRACTION * heat_s_per_c * (t_high - t_low),
              WINDOW_MIN, WINDOW_MAX)

    The nozzle needs heat * (high - low) seconds for a full swing. Cooling is
    not used: the script never pre-cools, so only the heating rate matters.
    Flow changes shorter than a quarter of that swing only make the heater chase
    noise it cannot follow, so W is the finest time resolution worth resolving.
    W is also the minimum spacing between emitted M104 lines.
    """
    w = WINDOW_FRACTION * heat_s_per_c * (t_high - t_low)
    return min(max(w, WINDOW_MIN), WINDOW_MAX)


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
    for m in re.finditer(r"flowtemp_(\w+?)\s*=\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)", text):
        out[m.group(1)] = float(m.group(2))
    return out


def enabled(cfg, overrides):
    """Why the script should skip this file, or None when it should run."""
    if "flowtemp" in overrides:
        on = overrides["flowtemp"] == "1"
    else:
        on = re.search(r"(?<!\w)flowtemp\s*=\s*1\b", cfg.get("filament_notes", "")) is not None
    if not on:
        return "filament Notes have no 'flowtemp = 1'"
    if first_value(overrides.get("resonance_avoidance", cfg.get("resonance_avoidance", "0"))) != "1":
        return "resonance_avoidance is off (calibration print)"
    return None


def get_settings(cfg, overrides):
    def num(key):
        if key in overrides:
            return float(overrides[key])
        if key not in cfg or first_value(cfg[key]) == "":
            raise FlowTempError(f"missing '{key}' in the G-code config block")
        try:
            return float(first_value(cfg[key]))
        except ValueError:
            raise FlowTempError(f"'{key}' is not a number: {cfg[key]!r}")

    notes = parse_notes(cfg.get("printer_notes", ""))
    for k, v in overrides.items():
        if k.startswith("flowtemp_"):
            notes[k[len("flowtemp_"):]] = float(v)
    if "heat_s_per_c" not in notes:
        raise FlowTempError("missing 'flowtemp_heat_s_per_c = <seconds>' in printer Notes")
    st = {
        "low": num("nozzle_temperature_range_low"),
        "high": num("nozzle_temperature_range_high"),
        "max_flow": num("filament_max_volumetric_speed"),
        "first": num("nozzle_temperature_initial_layer"),
        "fil_d": num("filament_diameter"),
        "heat": notes["heat_s_per_c"],
        "delay": notes.get("heat_delay_s", 0.0),
    }
    if st["heat"] <= 0:
        raise FlowTempError("flowtemp_heat_s_per_c must be > 0")
    if st["delay"] < 0:
        raise FlowTempError("flowtemp_heat_delay_s must be >= 0")
    if st["high"] < st["low"]:
        raise FlowTempError("nozzle_temperature_range_high < nozzle_temperature_range_low")
    if st["max_flow"] <= 0:
        raise FlowTempError("filament_max_volumetric_speed must be > 0")

    def opt(key, default):
        try:
            return float(first_value(cfg.get(key, ""))) or default
        except ValueError:
            return default
    st["accel"] = opt("default_acceleration", 5000.0)
    st["vmax_z"] = opt("machine_max_speed_z", 15.0)
    st["vmax_xy"] = opt("machine_max_speed_x", 300.0)
    return st


# --------------------------------------------------------------------------- simulation

WORD = re.compile(r"([A-Za-z])\s*([-+]?[0-9]*\.?[0-9]+)")


def plan_times(recs):
    """Klipper-style lookahead. Sets the duration (index 10) of each record.

    Record: [line, dist, ux, uy, uz, v, accel, jd, kinematic, vol, duration].
    Junction speed uses Klipper's junction-deviation formula
    (jd = scv^2 * (sqrt(2) - 1) / accel) plus its centripetal limit.
    Extrude-only moves and dwells stop the toolhead, as in Klipper.
    Klipper's minimum_cruise_ratio is ignored; that makes the estimate slightly
    short, which only gives the pre-heat more real lead time.
    """
    n = len(recs)
    smax = [0.0] * n
    prev = None
    for i, r in enumerate(recs):
        if not r[8]:
            prev = None
            continue
        if prev is not None:
            p = prev
            cos_t = -(r[2] * p[2] + r[3] * p[3] + r[4] * p[4])
            sin_h = math.sqrt(max(0.5 * (1.0 - cos_t), 0.0))
            cos_h = math.sqrt(max(0.5 * (1.0 + cos_t), 0.0))
            v2 = min(r[5] * r[5], p[5] * p[5])
            if 1.0 - sin_h > 0.0 and cos_h > 0.0:
                rjd = sin_h / (1.0 - sin_h)
                q = 0.25 * sin_h / cos_h
                v2 = min(v2, rjd * r[7] * r[6], rjd * p[7] * p[6],
                         2.0 * r[1] * r[6] * q, 2.0 * p[1] * p[6] * q)
            smax[i] = v2
        prev = r
    start = [0.0] * n
    end = [0.0] * n
    nxt = 0.0
    for i in range(n - 1, -1, -1):
        r = recs[i]
        if not r[8]:
            nxt = 0.0
            continue
        end[i] = nxt
        start[i] = min(smax[i], nxt + 2.0 * r[1] * r[6])
        nxt = start[i]
    reach = 0.0
    for i, r in enumerate(recs):
        if not r[8]:
            reach = 0.0
            continue
        dv2 = 2.0 * r[1] * r[6]
        start[i] = min(start[i], reach)
        end[i] = min(end[i], start[i] + dv2)
        reach = end[i]
        a = r[6]
        vs, ve = math.sqrt(start[i]), math.sqrt(end[i])
        vp = math.sqrt(max(min(r[5] * r[5], (start[i] + end[i] + dv2) / 2.0), 1e-12))
        da = (vp * vp - start[i]) / (2.0 * a)
        dd = (vp * vp - end[i]) / (2.0 * a)
        cruise = max(r[1] - da - dd, 0.0)
        r[10] = (vp - vs) / a + (vp - ve) / a + cruise / vp


def simulate(lines, st):
    """Return (region, moves, layer2_t, total_t).

    moves: list of (line_index, t_start, duration, volume_mm3)
    """
    start = end = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s == START_MARK and start is None:
            start = i + 1
        elif s == END_MARK and start is not None:
            end = i
    if start is None or end is None:
        # fallback: first layer change to end of executable block
        for i, line in enumerate(lines):
            s = line.strip()
            if start is None and s == ";LAYER_CHANGE":
                start = i
            if s == "; EXECUTABLE_BLOCK_END":
                end = i
                break
        if start is None:
            raise FlowTempError(f"no '{START_MARK}' marker and no ';LAYER_CHANGE' found")
        if end is None:
            end = len(lines)
        sys.stderr.write("flow_temp: start/end markers not found, using first ;LAYER_CHANGE\n")

    area = math.pi * (st["fil_d"] / 2.0) ** 2
    pos = [0.0, 0.0, 0.0]
    abs_xyz = True
    abs_extrude = False   # Klipper: E is absolute only if G90 and M82
    e_last = 0.0
    feed = 3000.0 / 60.0
    accel = st["accel"]
    scv = 5.0
    layers = 0
    layer2_k = None
    recs = []

    for i, line in enumerate(lines):
        code = line.split(";", 1)[0].strip()
        in_region = start <= i < end
        if in_region and line.startswith(";LAYER_CHANGE"):
            layers += 1
            if layers == 2 and layer2_k is None:
                layer2_k = len(recs)
        if not code:
            continue
        up = code.upper()
        cmd = up.split(None, 1)[0]
        if cmd in ("G0", "G1"):
            w = {k.upper(): float(v) for k, v in WORD.findall(code[len(cmd):])}
            if "F" in w and w["F"] > 0:
                feed = w["F"] / 60.0
            new = list(pos)
            for ax, n in (("X", 0), ("Y", 1), ("Z", 2)):
                if ax in w:
                    new[n] = w[ax] if abs_xyz else pos[n] + w[ax]
            de = 0.0
            abs_e = abs_xyz and abs_extrude
            if "E" in w:
                de = w["E"] - e_last if abs_e else w["E"]
                if abs_e:
                    e_last = w["E"]
            dxy = math.hypot(new[0] - pos[0], new[1] - pos[1])
            dz = abs(new[2] - pos[2])
            dist = math.sqrt(dxy * dxy + dz * dz)
            v = feed
            vol = de * area if (de > 0 and dxy > 0) else 0.0
            if in_region and (dist > 0 or de != 0):
                if dist > 0:
                    if dz > 0:
                        v = min(v, st["vmax_z"] * dist / dz)
                    v = min(v, st["vmax_xy"])
                    jd = scv * scv * (math.sqrt(2.0) - 1.0) / accel
                    recs.append([i, dist, (new[0] - pos[0]) / dist, (new[1] - pos[1]) / dist,
                                 (new[2] - pos[2]) / dist, v, accel, jd, True, vol, 0.0])
                else:  # extrude-only: stops the toolhead
                    recs.append([i, 0.0, 0, 0, 0, v, accel, 0, False, 0.0,
                                 abs(de) / v if v > 0 else 0.0])
            pos = new
        elif cmd == "G4":
            w = {k.upper(): float(v) for k, v in WORD.findall(code[2:])}
            if in_region:
                recs.append([i, 0.0, 0, 0, 0, 0, 0, 0, False, 0.0,
                             w.get("P", 0.0) / 1000.0 + w.get("S", 0.0)])
        elif cmd == "G90":
            abs_xyz = True
        elif cmd == "G91":
            abs_xyz = False
        elif cmd == "M82":
            abs_extrude = True
        elif cmd == "M83":
            abs_extrude = False
        elif cmd == "G92":
            w = {k.upper(): float(v) for k, v in WORD.findall(code[3:])}
            if "E" in w:
                e_last = w["E"]
        elif cmd == "M204":
            w = {k.upper(): float(v) for k, v in WORD.findall(code[4:])}
            a = w.get("S") or w.get("P")
            if a and a > 0:
                accel = a
        elif cmd == "SET_VELOCITY_LIMIT":
            m = re.search(r"\bACCEL=([0-9.]+)", up)
            if m and float(m.group(1)) > 0:
                accel = float(m.group(1))
            m = re.search(r"SQUARE_CORNER_VELOCITY=([0-9.]+)", up)
            if m:
                scv = float(m.group(1))
    if not recs:
        raise FlowTempError("no moves found in the processed region")
    plan_times(recs)
    moves = []
    t = 0.0
    layer2_t = None
    for k, r in enumerate(recs):
        if k == layer2_k:
            layer2_t = t
        moves.append((r[0], t, r[10], r[9]))
        t += r[10]
    if layer2_t is None:
        layer2_t = t  # single-layer print: all of it is layer 1
    return (start, end), moves, layer2_t, t


# --------------------------------------------------------------------------- temperature plan

def plan(moves, layer2_t, total_t, st):
    dt = GRID_DT
    nb = int(math.ceil(total_t / dt)) + 1
    vol = [0.0] * nb
    for _, t0, dur, v in moves:
        if v <= 0:
            continue
        if dur <= 0:
            vol[min(int(t0 / dt), nb - 1)] += v
            continue
        rate = v / dur
        t1 = t0 + dur
        b = int(t0 / dt)
        while b < nb:
            lo = max(t0, b * dt)
            hi = min(t1, (b + 1) * dt)
            if hi <= lo:
                break
            vol[b] += rate * (hi - lo)
            b += 1

    W = window_seconds(st["heat"], st["low"], st["high"])
    nw = max(1, int(round(W / dt)))
    pre = [0.0] * (nb + 1)
    for i, v in enumerate(vol):
        pre[i + 1] = pre[i] + v

    span = st["high"] - st["low"]
    first = st["first"]
    target = [0.0] * nb
    avg = [0.0] * nb
    for i in range(nb):
        # Forward window [t, t+W) brings the rise in early (the backward pass
        # then adds the heating lead). Trailing window [t-W, t) stops the
        # target from falling before the flow actually drops: no pre-cooling,
        # the target falls over the W seconds after the drop.
        j = min(nb, i + nw)
        fwd = (pre[j] - pre[i]) / ((j - i) * dt)
        k = max(0, i - nw)
        bwd = (pre[i] - pre[k]) / ((i - k) * dt) if i > k else 0.0
        a = max(fwd, bwd)
        avg[i] = a
        if i * dt < layer2_t:
            # Layer 1 is fixed. The backward pass may still raise the end of
            # layer 1 above this to pre-heat for layer 2, never below it.
            target[i] = first
        else:
            target[i] = st["low"] + span * min(a, st["max_flow"]) / st["max_flow"]

    step = dt / st["heat"]
    cmd = target[:]
    for i in range(nb - 2, -1, -1):
        need = cmd[i + 1] - step
        if need > cmd[i]:
            cmd[i] = need
    # Heater delay: a setpoint takes effect delay seconds late, so command at
    # t what is needed anywhere in [t, t + delay]. Sliding max, O(n).
    nd = int(round(st["delay"] / dt))
    if nd > 0:
        shifted = [0.0] * nb
        q = deque()
        for i in range(nb - 1, -1, -1):
            while q and cmd[q[-1]] <= cmd[i]:
                q.pop()
            q.append(i)
            while q[0] > i + nd:
                q.popleft()
            shifted[i] = cmd[q[0]]
        cmd = shifted
    return W, nw, avg, target, cmd


def schedule(moves, cmd, W, st):
    """Pick emission points. Returns {line_index: temp}.

    M104 can only go between lines, and at most once per W seconds. After an
    emission at t, the next chance is the first move starting at or after t + W.
    So the value emitted at t is ceil(max(cmd)) up to that next chance, which
    keeps the setpoint at or above cmd at all times.
    """
    dt = GRID_DT
    n = len(cmd)
    starts = [m[1] for m in moves]
    current = int(round(st["first"]))   # set by M109 just before the region
    last_t = -1e9
    out = {}
    last_bin = -1
    for k, (idx, t0, dur, _) in enumerate(moves):
        b = min(int(t0 / dt), n - 1)
        if b == last_bin or t0 - last_t < W:
            continue
        last_bin = b
        nxt = bisect.bisect_left(starts, t0 + W, k + 1)
        horizon = starts[nxt] if nxt < len(starts) else t0 + max(W, dur)
        peak = max(cmd[b:min(n, int(horizon / dt) + 1)] or [cmd[b]])
        want = int(math.ceil(peak - 1e-6))
        if want != current:
            out[idx] = want
            current = want
            last_t = t0
    return out


# --------------------------------------------------------------------------- main

def process(path, dry_run, overrides):
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        lines = fh.readlines()
    if any(l.startswith(TAG + " START") for l in lines):
        print("flow_temp: file already processed, nothing to do")
        return 0
    cfg = read_config(lines)
    skip = enabled(cfg, overrides)
    if skip:
        print(f"flow_temp: {skip}, nothing to do")
        return 0
    st = get_settings(cfg, overrides)
    (r0, r1), moves, layer2_t, total_t = simulate(lines, st)
    W, nw, avg, target, cmd = plan(moves, layer2_t, total_t, st)
    emits = schedule(moves, cmd, W, st)

    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    out = []
    removed = 0
    for i, line in enumerate(lines):
        if i in emits:
            out.append(f"M104 S{emits[i]} ; flow_temp{nl}")
        if r0 <= i < r1 and re.match(r"\s*M104\b", line, re.I):
            out.append("; flow_temp removed: " + line)
            removed += 1
            continue
        out.append(line)

    temps = list(emits.values()) or [int(round(st["first"]))]
    summary = [
        f"{TAG} START",
        f"; window_s = {W:.2f}  heat_s_per_c = {st['heat']}  heat_delay_s = {st['delay']}",
        f"; range = {st['low']:.0f}-{st['high']:.0f} C  max_flow = {st['max_flow']} mm3/s  layer1 = {st['first']:.0f} C",
        f"; commanded min/max = {min(temps)}/{max(temps)} C  M104 added = {len(emits)}  M104 commented = {removed}",
        f"; estimated region time = {total_t / 60:.1f} min  peak avg flow = {max(avg):.1f} mm3/s",
        f"{TAG} END",
    ]
    # Put the summary right after Orca's header block (or at the top).
    ins = 0
    for i, line in enumerate(out):
        if line.strip() == "; HEADER_BLOCK_END":
            ins = i + 1
            break
    out[ins:ins] = [s + nl for s in summary]

    for s in summary[1:-1]:
        print("flow_temp" + s[1:])
    if dry_run:
        print("flow_temp: dry run, file not written")
        return 0

    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".flow_temp.", dir=d)
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
                sys.stderr.write("flow_temp: --set needs key=value\n")
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
        sys.stderr.write(f"flow_temp: file not found: {path}\n")
        return 1
    try:
        return process(path, dry, overrides)
    except FlowTempError as e:
        sys.stderr.write(f"flow_temp: ERROR: {e}. File not modified.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
