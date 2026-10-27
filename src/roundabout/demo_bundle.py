"""Validation and loading for portable, precomputed demo bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


REQUIRED_MANIFEST_FIELDS = {
    "bundle_version",
    "created_at",
    "study_phase",
    "validation_status",
    "config",
    "videos",
    "tracks",
    "track_summary",
    "roi_summary",
    "risk_summary",
    "events",
}


@dataclass(frozen=True)
class DemoBundle:
    root: Path
    manifest: dict[str, object]

    @property
    def validation_status(self) -> str:
        return str(self.manifest["validation_status"])


def load_bundle(root: Path) -> DemoBundle:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Demo manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_MANIFEST_FIELDS - manifest.keys())
    if missing:
        raise ValueError(f"Demo manifest is missing fields: {', '.join(missing)}")

    for key in (
        "videos", "tracks", "track_summary", "roi_summary", "risk_summary", "events"
    ):
        referenced = root / str(manifest[key])
        if not referenced.is_file():
            raise FileNotFoundError(f"Referenced demo file not found: {referenced}")
    for key in ("validated_events", "event_assets"):
        if key in manifest:
            referenced = root / str(manifest[key])
            if not referenced.is_file():
                raise FileNotFoundError(f"Referenced demo file not found: {referenced}")
    if "event_assets" in manifest:
        assets = json.loads(
            (root / str(manifest["event_assets"])).read_text(encoding="utf-8")
        )
        for asset in assets:
            for key in ("clip", "roi_frame", "filmstrip"):
                referenced = root / str(asset[key])
                if not referenced.is_file():
                    raise FileNotFoundError(
                        f"Referenced event asset not found: {referenced}"
                    )

    return DemoBundle(root=root, manifest=manifest)
