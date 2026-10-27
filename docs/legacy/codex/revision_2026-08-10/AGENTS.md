# Repository Guidelines

## Project Purpose

`GPT_Round` is a reproducible Vision-AI traffic-safety research project. The
current roundabout drone-video dataset remains the first development and
validation case. The broader target is pedestrian safety at Korean unsignalized
crosswalks, including local streets, apartment complexes, school campuses, and
industrial areas.

Do not treat a larger number of tracks, candidates, or risk events as evidence
of improved safety-analysis quality. Quality claims require comparison with
human-reviewed reference objects, trajectories, crossings, and interaction
pairs.

## Project Structure

Core Python code lives in `src/roundabout/`. Reusable detection, tracking,
filtering, continuation, event, schema, and path logic belongs there. Command
line/export helpers belong in `scripts/`; configuration presets in `configs/`;
tests in `tests/`. Calibration and reviewed reference data are stored in
`data/calibration/` and `data/ground_truth/`. Treat `archive/legacy/` and
`docs/legacy/` as read-only historical references.

Active methodology and validation documents are:

- `docs/methodology/REBUILD_PLAN.md`
- `docs/methodology/pdi_method_review.md`
- `docs/validation/OBJECT_TRACK_RECALL_METHOD_REVIEW.md`
- `docs/validation/DECISION_LOG.md`

Read the relevant documents before changing a pipeline stage or quality gate.

## Mandatory Pipeline Discipline

Keep these stages distinguishable and preserve reproducible outputs:

1. raw detections;
2. raw tracker trajectories;
3. filtered trajectories;
4. merged trajectories;
5. pedestrian crossing events;
6. pedestrian-vehicle interaction candidates;
7. reviewed interaction events;
8. safety indicators.

The current pipeline does not yet preserve raw detections separately and does
not yet implement crossing events or A0/A1/B0/B1/B2 interaction classes. Do not
describe these as implemented until code, tests, example outputs, and validation
evidence exist.

## Measurement and Interpretation Rules

- Validate object and trajectory observation before PET, TTC, or PDI.
- Report pixel coordinates and world coordinates with explicit, separate units.
- Do not apply a pixel-named threshold after Homography without confirming the
  coordinate system and renaming or converting the threshold.
- Treat the current ROI occupancy-gap PET and constant-velocity TTC as
  provisional candidates, not validated conflict measures.
- Do not compute or report site-level PDI when the complete interaction
  denominator is unavailable.
- For the available 30-minute video, use only a PDI-concept screening procedure:
  interaction ordering/classification, input-variable feasibility, and—only for
  manually confirmed qualified events—`provisional_dpd`.
- Use the corrected B2 equation documented in `pdi_method_review.md`; never use
  the printed equation silently. Deceleration `a5_mps2` is negative.
- Do not transfer the published DPD coefficients directly to turning vehicles or
  claim Korean site calibration.
- Mark internal targets as `internal_provisional_gate`, not external standards.

## Change Approval Boundaries

Before changing a selected model, FPS, confidence, tracking/filter/merge
threshold, coordinate calibration, safety formula, or quality gate:

1. state the affected pipeline stage;
2. show the current baseline and proposed change;
3. identify the validation sample and metrics;
4. obtain user approval before a full-video GPU run or a methodological change.

Never overwrite prior baseline outputs. Use a new configuration/output identity
and record the decision in `docs/validation/DECISION_LOG.md`.

## Testing and Completion

Use Python 3.11 or newer. Install and test with:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[analysis,dev,demo]'
.venv/bin/pytest
```

Before completing an implementation task:

1. run relevant unit and regression tests;
2. compare with the current baseline on the same reviewed sample;
3. report configuration changes and the pipeline stage changed;
4. preserve existing output schemas or document/version intentional changes;
5. save reproducible example output and a short validation summary;
6. report limitations and excluded scope.

For quality-evaluation work, prefer event recall, complete-trajectory recall,
trajectory time coverage, fragmentation, ID switches, maximum missing gap,
stage-by-stage survival, and pedestrian-vehicle interaction-pair observation
rate. Track-count totals alone are insufficient.

## Coding and Git

Follow PEP 8, existing type annotations, `pathlib.Path`, and concise docstrings.
Centralize filesystem assumptions in `roundabout.paths`. Add focused regression
tests for geometry, schemas, tracking, filtering, merging, events, units, and
visual outputs. Do not commit raw video, weights, virtual environments,
regenerated outputs, or confidential/copyright-restricted source documents.
