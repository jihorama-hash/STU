"""Runtime package provenance helpers for execution lineage."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import cv2


def opencv_environment() -> dict[str, str]:
    """Return cv2 runtime version and the single installed owning distribution."""
    installed: dict[str, str] = {}
    for distribution in ("opencv-python", "opencv-python-headless"):
        try:
            installed[distribution] = version(distribution)
        except PackageNotFoundError:
            continue
    if len(installed) != 1:
        found = ", ".join(f"{name}=={value}" for name, value in installed.items()) or "none"
        raise RuntimeError(
            "Expected exactly one OpenCV distribution to own cv2; found: " + found
        )
    distribution, distribution_version = next(iter(installed.items()))
    return {
        "cv2_version": cv2.__version__,
        "distribution": distribution,
        "distribution_version": distribution_version,
    }
