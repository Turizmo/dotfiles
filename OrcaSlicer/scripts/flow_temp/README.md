# flow_temp

OrcaSlicer post-processing script. It sets the nozzle temperature from the flow that is coming up.
The nozzle is already hot when a high-flow section starts. Python 3 stdlib only.

## How it works

1. Estimates the time of every move in the print. It uses a Klipper-style lookahead: trapezoid
   accel, junction deviation from `square_corner_velocity`, and the `SET_VELOCITY_LIMIT ACCEL=`
   values in the G-code. Travel, retract, wipe and dwell count as 0 flow.
2. Places the extruded volume on a 0.1 s grid. For each point it takes the average flow over the
   next W seconds and over the last W seconds, and uses the larger of the two. The forward window
   catches a rise early. The trailing window stops the temperature from falling before the flow
   drops.
3. `target = low + (high - low) * min(avg, max_flow) / max_flow`, using the filament preset's
   `nozzle_temperature_range_low/high` and `filament_max_volumetric_speed`.
4. Layer 1 stays at `nozzle_temperature_initial_layer`. Near the end of layer 1, the temperature can
   rise above that value to pre-heat for layer 2. The setpoint can drop `cool_delay_s` before
   layer 2, so the nozzle itself stays at that value until layer 2 starts.
5. A backward pass limits every rise to `1 / heat_s_per_c` °C per second, so each heat-up starts
   early enough. Then every rise moves `heat_delay_s` earlier and every drop `cool_delay_s`
   earlier, because the nozzle barely moves for that long after a new setpoint. So the nozzle
   starts to cool when the flow drops, not before.
6. Inserts `M104 S<int>` (never `M109`) when the needed temperature changes by 1 °C or more. It
   inserts at most one per W seconds. Each value covers the time until the next allowed `M104`,
   so the setpoint is never below what is needed. Orca's own `M104` lines in the print (for
   example the one at layer 2) are commented out. Feedrates are not changed.

Window: `W = clamp(0.25 * heat_s_per_c * (high - low), 1 s, 10 s)`.
A full temperature rise takes `heat * (high - low)` seconds. The cooling rate is not used: drops
only lower the target. The nozzle cannot follow
flow changes that are shorter than a quarter of that swing.

The processed part of the file is between `; MZ FLOW TEMP START` (end of machine start G-code) and
`; MZ FLOW TEMP END` (start of machine end G-code). If the markers are missing, the script uses the
range from the first `;LAYER_CHANGE` to `; EXECUTABLE_BLOCK_END`.

## Settings

The script is in the post-processing list of every process preset. It only changes the file when
both of these are true:

- The filament preset's Notes have the line `flowtemp = 1`. This is the on/off switch.
- `resonance_avoidance` is on in the process. Orca turns it off in calibration prints, so
  temperature towers and other tests keep their own temperatures.

Otherwise it prints why it skipped and leaves the file as it is.

Printer settings > Notes:

```
flowtemp_heat_s_per_c = 0.5
flowtemp_heat_delay_s = 3.5
flowtemp_cool_delay_s = 3.0
```

- `flowtemp_heat_s_per_c` (required): seconds for the nozzle to heat 1 °C once it is rising.
- `flowtemp_heat_delay_s` (optional, default 0): seconds after a new setpoint before the nozzle
  starts to rise. Every rise is sent this much earlier.
- `flowtemp_cool_delay_s` (optional, default 0): seconds after a lower setpoint before the nozzle
  starts to fall. Every drop is sent this much earlier. It is capped at `heat_delay_s`.

The other values come from the filament preset (`nozzle_temperature_range_low/high`,
`filament_max_volumetric_speed`, `nozzle_temperature_initial_layer`, `filament_diameter`).

Process preset > Others > Post-processing scripts:

```
python3 /home/turizmo/dotfiles/OrcaSlicer/scripts/flow_temp/flow_temp.py
```

## Command line

```
flow_temp.py [--dry-run] [--set key=value ...] file.gcode
```

- `--dry-run`: print the summary and do not write the file.
- `--set flowtemp_heat_s_per_c=0.4`: override a setting for testing. This also works for filament
  keys. `--set flowtemp=1` forces the script on, `--set flowtemp=0` off.

If a required value is missing, the script prints an error to stderr and exits 1. The file is not
changed, and Orca shows the error. The output is written to a temp file and then renamed over the
original. If the file already has a `; FLOW_TEMP START` summary, the script does nothing.

## Tuning

- Measure the heat-up during a flow-temp print: log `extruder` temperature and target from
  Moonraker every 0.25 s. For each target rise, take the time until the nozzle is within 0.5 °C.
  Fit `time = heat_delay_s + heat_s_per_c * rise`. The Revo HF 0.6 measured 3.7 s + 0.35 s/°C
  (58 rises up to 10 °C, 2026-10-25). Round up if unsure: it starts the pre-heat earlier.
- Do the same for drops to get `cool_delay_s`. The Revo HF 0.6 measured 3.1 s + 0.70 s/°C
  (46 drops, part fan mostly 30 %). Round down if unsure: the nozzle then stays hot a bit longer.
- The time estimate is about 3–7 % shorter than Orca's. Real events then come a little later than
  planned, so the pre-heat has a bit of extra lead.
- The summary comment near the top of the G-code shows W, min/max commanded temperature and the
  number of `M104` lines.
