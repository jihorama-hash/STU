"""Build a small Windows blind-GT reviewer bundle without automatic outputs."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "outputs/review_tools/blind_gt_windows_R01"
SOURCE_VIDEO = Path("data/raw/before/DJI_0482.MP4")
BUNDLE_FILES = (
    Path("apps/demo/blind_gt_review.py"),
    Path("scripts/blind_gt_review_viewer.py"),
    Path("scripts/windows/README_BLIND_GT_REVIEW.md"),
    Path("scripts/windows/run_blind_gt_review.bat"),
    Path("scripts/windows/setup_blind_gt_review.bat"),
    Path("scripts/windows/validate_blind_gt_worksheets.bat"),
    Path("scripts/windows/verify_source_video.bat"),
    Path("data/ground_truth/object_track_v1/ground_truth_manifest.json"),
    Path("data/ground_truth/object_track_v1/review/README.md"),
    Path("data/ground_truth/object_track_v1/review/OBJECT_INVENTORY_INPUT_GUIDE.md"),
    Path("data/ground_truth/object_track_v1/review/VISIBILITY_INPUT_GUIDE.md"),
    Path(
        "data/ground_truth/object_track_v1/review/"
        "gate3a2_object_inventory_R01.csv"
    ),
    Path("data/ground_truth/object_track_v1/review/gate3a2_visibility_R01.csv"),
)


def build_bundle(output: Path, *, include_video: bool = False) -> list[Path]:
    """Copy the reviewed allowlist into a new portable directory."""

    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")

    copied: list[Path] = []
    for relative_path in BUNDLE_FILES:
        source = REPOSITORY_ROOT / relative_path
        if not source.is_file():
            raise FileNotFoundError(f"required bundle file is missing: {source}")
        destination = output / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(relative_path)

    video_directory = output / SOURCE_VIDEO.parent
    video_directory.mkdir(parents=True, exist_ok=True)
    if include_video:
        source_video = REPOSITORY_ROOT / SOURCE_VIDEO
        if not source_video.is_file():
            raise FileNotFoundError(f"source video is missing: {source_video}")
        shutil.copy2(source_video, output / SOURCE_VIDEO)
        copied.append(SOURCE_VIDEO)
    else:
        placeholder = video_directory / "COPY_DJI_0482_MP4_HERE.txt"
        placeholder.write_text(
            "Copy the approved source video here as DJI_0482.MP4.\n"
            "Expected SHA-256:\n"
            "168c20eede240300371aff34a53d2617a4f1f5fe8b2dad37f16016c016c39cf0\n",
            encoding="utf-8",
        )
        copied.append(placeholder.relative_to(output))
    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Windows blind-GT review bundle."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--include-video",
        action="store_true",
        help="copy the approved 3.6 GB source video into the bundle",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    copied = build_bundle(args.output, include_video=args.include_video)
    print(f"Windows blind-GT bundle: {args.output.resolve()}")
    print(f"files copied: {len(copied)}")
    if not args.include_video:
        print("source video omitted; copy DJI_0482.MP4 before running the reviewer")


if __name__ == "__main__":
    main()
