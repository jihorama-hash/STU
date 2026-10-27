"""Create a compact contact sheet from exported manual-review samples."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_dir")
    parser.add_argument("--columns", type=int, default=3)
    args = parser.parse_args()

    review_dir = Path(args.review_dir)
    with (review_dir / "manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    panels = []
    width = 720
    for row in rows:
        image = cv2.imread(str(review_dir / row["image"]))
        if image is None:
            raise FileNotFoundError(review_dir / row["image"])
        height = round(image.shape[0] * width / image.shape[1])
        panel = cv2.resize(image, (width, height))
        number = row.get("sample_number", row.get("reference_number", "?"))
        object_class = row.get("object_class", row.get("reference_class", "?"))
        track_id = row.get("track_id", row.get("legacy_track_id", "?"))
        cv2.putText(
            panel,
            f"{number}: {object_class} #{track_id}",
            (15, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        panels.append(panel)

    panel_height = max(panel.shape[0] for panel in panels)
    blank = np.zeros((panel_height, width, 3), dtype=np.uint8)
    grid_rows = []
    for start in range(0, len(panels), args.columns):
        group = panels[start:start + args.columns]
        group += [blank] * (args.columns - len(group))
        grid_rows.append(cv2.hconcat(group))
    output = review_dir / f"contact_sheet_{len(rows)}.jpg"
    cv2.imwrite(str(output), cv2.vconcat(grid_rows))
    print(output)


if __name__ == "__main__":
    main()
