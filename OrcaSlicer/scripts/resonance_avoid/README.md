# resonance_avoid

OrcaSlicer post-processing script. No move cruises inside the resonance speed band. Python 3
stdlib only.

Orca's own resonance avoidance only changes the commanded speed of outer walls. Short moves still
cruise inside the band. With `minimum_cruise_ratio = 0.5`, Klipper plans the top speed of a short
move as if accel were half. A 5 mm infill line at F9000 then cruises at about 110 mm/s.

## How it works

1. Simulates the print with a port of Klipper's planner (`toolhead.py`: `Move.calc_junction` and
   `LookAheadQueue.flush`). It includes junction deviation, the centripetal limit,
   `minimum_cruise_ratio`, the extruder `instantaneous_corner_velocity` and the Z limits. Accel,
   velocity, `square_corner_velocity` and `minimum_cruise_ratio` follow `SET_VELOCITY_LIMIT` and
   `M204` in the G-code.
2. Every XY move (print and travel) that cruises above `min` and up to `max` for more than 0.05 mm
   gets `F = min`. The next move gets its original F back.
3. Repeats until no move is left in the band. A slower move can pull its neighbours into the band,
   so this takes a few passes.

Moves that only pass through the band while they accelerate or slow down are not changed.

The processed part of the file is the same as for `flow_temp`: between `; MZ FLOW TEMP START` and
`; MZ FLOW TEMP END`, or from the first `;LAYER_CHANGE` to `; EXECUTABLE_BLOCK_END`.

## Settings

Printer settings, "Resonance avoidance" group:

- The checkbox is the on/off switch. Orca turns it off for its calibration prints, so the script
  leaves those alone. Orca's own outer wall handling still runs. The script covers every other move.
- `min_resonance_avoidance_speed` / `max_resonance_avoidance_speed`: the band.

Printer settings > Notes (optional, the defaults match `printer.cfg`):

```
resavoid_min_cruise_ratio = 0.5
resavoid_square_corner_velocity = 5
resavoid_max_velocity = 300
resavoid_max_z_velocity = 15
resavoid_max_z_accel = 350
resavoid_instantaneous_corner_velocity = 1
```

Process preset > Others > Post-processing scripts. It must come before `flow_temp.py`, which needs
the final speeds:

```
python3 /home/turizmo/dotfiles/OrcaSlicer/scripts/resonance_avoid/resonance_avoid.py
python3 /home/turizmo/dotfiles/OrcaSlicer/scripts/flow_temp/flow_temp.py
```

## Command line

```
resonance_avoid.py [--dry-run] [--set key=value ...] file.gcode
```

- `--dry-run`: print the summary and do not write the file.
- `--set resavoid_min_cruise_ratio=0.25`: override a setting for testing. This also works for
  config keys such as `min_resonance_avoidance_speed` and `resonance_avoidance`.

If a required value is missing, or the file has `G2`/`G3` arcs, the script prints an error to
stderr and exits 1. The file is not changed. If the file already has a `; RESONANCE_AVOID START`
summary, the script does nothing.
