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

## Project Structure & Module Organization

Core Python code lives in `src/roundabout/`; keep reusable detection, tracking,
filtering, continuation, risk-analysis, schema, and path logic there. Command-line
helpers and export utilities belong in `scripts/`. The Streamlit interface is
under `apps/demo/`, configuration presets live in `configs/`, and tests mirror
package behavior in `tests/test_*.py`. Calibration and human-reviewed reference
data are stored in `data/calibration/` and `data/ground_truth/`. Raw videos,
model weights, generated runs, and `outputs/` are intentionally ignored. Treat
`archive/legacy/` and `docs/legacy/` as read-only historical references, not
active pipeline code.

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

The current pipeline preserves raw tracker, filtered, and merged trajectories,
but does not preserve raw detections separately. It also does not implement
pedestrian crossing events or A0/A1/B0/B1/B2 interaction classes. Do not
describe these stages as implemented until code, tests, example outputs, and
validation evidence exist.

## Measurement and Interpretation Rules

- Validate object and trajectory observation before PET, TTC, or PDI.
- Report source pixels, reference-image pixels, and world coordinates with
  explicit and separate coordinate-system and unit labels.
- The current Homography aligns videos to the `DJI_0481` reference-image pixel
  coordinate system; it is not a verified conversion to meters.
- Do not apply a pixel threshold to a future world-coordinate output without
  renaming or converting the threshold.
- Treat the current ROI sequential-occupancy-gap PET as a provisional candidate,
  not a validated conflict measure.
- Treat the current local constant-velocity TTC as a provisional image-plane
  candidate, not a validated collision measure.
- Do not compute or report site-level PDI when the complete interaction
  denominator is unavailable.
- For the eight available videos, whose usable duration totals about 29.31
  minutes, use only PDI-concept screening: interaction ordering and
  classification feasibility, input-variable feasibility, and—only for
  manually confirmed qualified events—`provisional_dpd`.
- For B2 screening, use
  `DPD_B2 = 1 / (1 + exp(0.561 * a5 + 2.713))`; deceleration `a5_mps2` is
  negative. Store `formula_version` with any result.
- Do not transfer the published DPD coefficients directly to turning vehicles
  or claim Korean site calibration.
- Mark internal targets as `internal_provisional_gate`, not external standards.

## Change Approval Boundaries

Before changing a selected model, FPS, confidence, tracking/filter/merge
threshold, coordinate calibration, safety formula, or quality gate:

1. state the affected pipeline stage;
2. show the current baseline and proposed change;
3. identify the validation sample and metrics;
4. obtain user approval before a full-video GPU run or a methodological change.

Never overwrite prior baseline outputs. Use a new configuration/output identity
and record approved methodological decisions in
`docs/validation/DECISION_LOG.md`.

## Build, Test, and Development Commands

Use Python 3.11 or newer and install the project in editable mode:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[analysis,dev,demo]'
.venv/bin/pytest
```

Preview the configured batch without executing GPU stages:

```bash
PYTHONPATH=src .venv/bin/python -m roundabout.run_batch --dry-run
```

The inventory command writes its destination. For a non-destructive comparison,
write to a temporary path rather than the tracked manifest:

```bash
PYTHONPATH=src python3 -m roundabout.inventory \
  --config configs/baseline.json \
  --output /tmp/gpt_round_raw_videos.csv
```

Rebuild the precomputed demo with
`PYTHONPATH=src python3 scripts/build_demo_bundle.py`, then launch it with
`PYTHONPATH=src .venv/bin/streamlit run apps/demo/app.py`. Do not start a
full-video GPU batch until the model and configuration have been explicitly
validated and approved.

## Testing and Completion

Tests use `unittest.TestCase` and are collected by pytest. Name files
`test_<module>.py` and methods `test_<behavior>`. Add focused regression tests
for schemas, geometry, tracking, filtering, merging, masks, units, risk
candidates, and demo-bundle behavior. No numeric coverage threshold is currently
configured.

Before completing an implementation task:

1. run relevant unit and regression tests;
2. compare with the current baseline on the same reviewed sample;
3. report configuration changes and the pipeline stage changed;
4. preserve existing output schemas or document and version intentional changes;
5. save reproducible example output and a short validation summary;
6. report limitations and excluded scope.

For quality-evaluation work, prefer event recall, complete-trajectory recall,
trajectory time coverage, fragmentation, ID switches, maximum missing gap,
stage-by-stage survival, and pedestrian-vehicle interaction-pair observation
rate. Track-count totals alone are insufficient.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Use `snake_case` for modules,
functions, and variables; `PascalCase` for classes; and uppercase names for
module constants. Preserve existing type annotations, concise docstrings,
`pathlib.Path` usage, and the `from __future__ import annotations` convention.
Keep filesystem assumptions centralized in `roundabout.paths`. No formatter or
linter is pinned, so match nearby code and group imports as standard library,
third-party, then local.

## Commit & Pull Request Guidelines

Recent history favors short, imperative summaries, sometimes with prefixes such
as `refactor:`. Use a focused subject such as
`fix: preserve track source labels`, and avoid mixing generated artifacts with
code changes. Pull requests should explain the affected pipeline stage, list
validation commands, link relevant issues or decision records, and include
screenshots or sample overlays for UI or visual-analysis changes. Never commit
raw video, weights, virtual environments, regenerated output directories, or
confidential/copyright-restricted source documents.
