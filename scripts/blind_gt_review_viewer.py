"""Review source video frames without exposing automatic analysis results."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = REPOSITORY_ROOT / "data/raw/before/DJI_0482.MP4"
DEFAULT_REVIEW_DIR = REPOSITORY_ROOT / "data/ground_truth/object_track_v1/review"
DEFAULT_OBJECTS_WORKSHEET = DEFAULT_REVIEW_DIR / "gate3a2_object_inventory_R01.csv"
DEFAULT_VISIBILITY_WORKSHEET = DEFAULT_REVIEW_DIR / "gate3a2_visibility_R01.csv"

OBJECT_HEADERS = (
    "gt_object_id",
    "object_class",
    "first_visible_frame_index",
    "last_visible_frame_index",
    "in_scope",
    "exclusion_reason",
    "notes",
)
VISIBILITY_HEADERS = (
    "gt_object_id",
    "start_frame_index",
    "end_frame_index",
    "visibility_status",
    "occlusion_reason",
    "notes",
)
OBJECT_ID_PATTERNS = {
    "person": re.compile(r"^P\d{3}$"),
    "bicycle": re.compile(r"^B\d{3}$"),
    "car": re.compile(r"^C\d{3}$"),
    "motorcycle": re.compile(r"^M\d{3}$"),
    "bus": re.compile(r"^BUS\d{3}$"),
    "truck": re.compile(r"^T\d{3}$"),
}
VISIBILITY_STATUSES = {
    "visible",
    "partially_occluded",
    "fully_occluded",
    "not_observable",
}

WINDOW_NAME = "Blind GT Review - metadata only"
LEFT_KEYS = {81, 65361, 16777234, 2424832, 63234}
RIGHT_KEYS = {83, 65363, 16777236, 2555904, 63235}
SHIFT_LEFT_KEYS = {50331666}
SHIFT_RIGHT_KEYS = {50331668}
PAGE_BACK_KEYS = {16777238, 2162688}
PAGE_FORWARD_KEYS = {16777239, 2228224}


@dataclass(frozen=True)
class EvaluationGrid:
    start_frame: int = 4196
    end_frame: int = 5994
    frame_step: int = 2
    source_fps: float = 30000 / 1001

    def contains(self, frame_index: int) -> bool:
        return (
            self.start_frame <= frame_index <= self.end_frame
            and (frame_index - self.start_frame) % self.frame_step == 0
        )

    @property
    def frame_count(self) -> int:
        return (self.end_frame - self.start_frame) // self.frame_step + 1

    @property
    def evaluation_fps(self) -> float:
        return self.source_fps / self.frame_step

    @property
    def one_second_delta(self) -> int:
        steps = round(self.evaluation_fps)
        return steps * self.frame_step

    @property
    def five_second_delta(self) -> int:
        steps = round(5 * self.evaluation_fps)
        return steps * self.frame_step

    def timestamp_seconds(self, frame_index: int) -> float:
        return frame_index / self.source_fps


def _read_rows(path: Path, expected_headers: tuple[str, ...]) -> tuple[list[dict[str, str]], list[str]]:
    warnings: list[str] = []
    if not path.is_file():
        return [], [f"missing worksheet: {path}"]
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = tuple(reader.fieldnames or ())
            if headers != expected_headers:
                warnings.append(
                    f"{path}: header mismatch; expected {','.join(expected_headers)}"
                )
            return list(reader), warnings
    except UnicodeDecodeError:
        return [], [f"{path}: not valid UTF-8 CSV; save the worksheet as UTF-8"]
    except csv.Error as exc:
        return [], [f"{path}: invalid CSV: {exc}"]


def _parse_grid_frame(
    value: str,
    *,
    field_name: str,
    path: Path,
    line_number: int,
    grid: EvaluationGrid,
) -> tuple[int | None, list[str]]:
    label = f"{path}:{line_number} {field_name}"
    if not value.strip():
        return None, [f"{label}: value is required"]
    try:
        frame_index = int(value)
    except ValueError:
        return None, [f"{label}: not an integer: {value!r}"]
    if not grid.contains(frame_index):
        return frame_index, [
            f"{label}: {frame_index} is outside evaluation grid "
            f"{grid.start_frame}..{grid.end_frame} step {grid.frame_step}; "
            "value was not changed"
        ]
    return frame_index, []


def validate_worksheets(
    objects_path: Path,
    visibility_path: Path,
    grid: EvaluationGrid,
) -> list[str]:
    """Return warnings without inferring or modifying any reviewer value."""

    object_rows, warnings = _read_rows(objects_path, OBJECT_HEADERS)
    visibility_rows, visibility_warnings = _read_rows(
        visibility_path, VISIBILITY_HEADERS
    )
    warnings.extend(visibility_warnings)

    object_ids: set[str] = set()
    for offset, row in enumerate(object_rows, start=2):
        object_id = row.get("gt_object_id", "").strip()
        object_class = row.get("object_class", "").strip()
        if not object_id:
            warnings.append(f"{objects_path}:{offset} gt_object_id: value is required")
        elif object_id in object_ids:
            warnings.append(f"{objects_path}:{offset} gt_object_id: duplicate {object_id}")
        else:
            object_ids.add(object_id)
        pattern = OBJECT_ID_PATTERNS.get(object_class)
        if pattern is None:
            warnings.append(
                f"{objects_path}:{offset} object_class: unsupported {object_class!r}"
            )
        elif object_id and pattern.fullmatch(object_id) is None:
            warnings.append(
                f"{objects_path}:{offset}: {object_id!r} does not match "
                f"the ID rule for {object_class}"
            )

        first_frame, first_warnings = _parse_grid_frame(
            row.get("first_visible_frame_index", ""),
            field_name="first_visible_frame_index",
            path=objects_path,
            line_number=offset,
            grid=grid,
        )
        last_frame, last_warnings = _parse_grid_frame(
            row.get("last_visible_frame_index", ""),
            field_name="last_visible_frame_index",
            path=objects_path,
            line_number=offset,
            grid=grid,
        )
        warnings.extend(first_warnings)
        warnings.extend(last_warnings)
        if first_frame is not None and last_frame is not None and first_frame > last_frame:
            warnings.append(
                f"{objects_path}:{offset}: first frame {first_frame} is after "
                f"last frame {last_frame}; values were not changed"
            )

        in_scope = row.get("in_scope", "").strip().lower()
        if in_scope not in {"true", "false"}:
            warnings.append(
                f"{objects_path}:{offset} in_scope: expected true or false"
            )
        if in_scope == "false" and not row.get("exclusion_reason", "").strip():
            warnings.append(
                f"{objects_path}:{offset}: exclusion_reason is required when "
                "in_scope=false"
            )

    for offset, row in enumerate(visibility_rows, start=2):
        object_id = row.get("gt_object_id", "").strip()
        if not object_id:
            warnings.append(f"{visibility_path}:{offset} gt_object_id: value is required")
        elif object_id not in object_ids:
            warnings.append(
                f"{visibility_path}:{offset}: {object_id!r} is not present in "
                "the object inventory"
            )

        start_frame, start_warnings = _parse_grid_frame(
            row.get("start_frame_index", ""),
            field_name="start_frame_index",
            path=visibility_path,
            line_number=offset,
            grid=grid,
        )
        end_frame, end_warnings = _parse_grid_frame(
            row.get("end_frame_index", ""),
            field_name="end_frame_index",
            path=visibility_path,
            line_number=offset,
            grid=grid,
        )
        warnings.extend(start_warnings)
        warnings.extend(end_warnings)
        if start_frame is not None and end_frame is not None and start_frame > end_frame:
            warnings.append(
                f"{visibility_path}:{offset}: start frame {start_frame} is after "
                f"end frame {end_frame}; values were not changed"
            )

        visibility_status = row.get("visibility_status", "").strip()
        if visibility_status not in VISIBILITY_STATUSES:
            warnings.append(
                f"{visibility_path}:{offset} visibility_status: unsupported "
                f"{visibility_status!r}"
            )
    return warnings


def print_validation(warnings: list[str]) -> None:
    if not warnings:
        print("worksheet validation: OK")
        return
    print(f"worksheet validation: {len(warnings)} warning(s)", file=sys.stderr)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)


class FrameReader:
    def __init__(self, video_path: Path, cache_size: int = 24) -> None:
        self.lock = threading.RLock()
        self.capture = cv2.VideoCapture(str(video_path))
        if not self.capture.isOpened():
            raise FileNotFoundError(f"cannot open video: {video_path}")
        self.width = round(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = round(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.frame_count = round(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.last_index: int | None = None
        self.cache_size = cache_size
        self.cache: OrderedDict[int, np.ndarray] = OrderedDict()

    def read(self, frame_index: int) -> np.ndarray:
        """Decode one source frame without concurrent access to VideoCapture."""

        with self.lock:
            return self._read_unlocked(frame_index)

    def _read_unlocked(self, frame_index: int) -> np.ndarray:
        cached = self.cache.get(frame_index)
        if cached is not None:
            self.cache.move_to_end(frame_index)
            return cached

        if self.last_index is not None and 0 < frame_index - self.last_index <= 10:
            for _ in range(self.last_index + 1, frame_index):
                if not self.capture.grab():
                    raise RuntimeError(f"cannot skip to source frame {frame_index}")
        else:
            if not self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
                raise RuntimeError(f"cannot seek to source frame {frame_index}")

        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"cannot decode source frame {frame_index}")
        decoded_index = round(self.capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if decoded_index != frame_index:
            raise RuntimeError(
                f"requested source frame {frame_index}, decoded {decoded_index}; "
                "review stopped instead of silently correcting the index"
            )
        self.last_index = frame_index
        self.cache[frame_index] = frame
        self.cache.move_to_end(frame_index)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return frame

    def close(self) -> None:
        with self.lock:
            self.capture.release()


class BlindReviewViewer:
    def __init__(
        self,
        video_path: Path,
        objects_path: Path,
        visibility_path: Path,
        grid: EvaluationGrid,
        window_width: int,
        window_height: int,
    ) -> None:
        self.video_path = video_path
        self.objects_path = objects_path
        self.visibility_path = visibility_path
        self.grid = grid
        self.window_width = window_width
        self.window_height = window_height
        self.reader = FrameReader(video_path)
        if (self.reader.width, self.reader.height) != (3840, 2160):
            raise RuntimeError(
                "blind pilot requires 3840x2160 source frames; got "
                f"{self.reader.width}x{self.reader.height}"
            )
        if self.reader.frame_count <= grid.end_frame:
            raise RuntimeError(
                f"video has {self.reader.frame_count} frames; grid ends at {grid.end_frame}"
            )
        if abs(self.reader.fps - grid.source_fps) > 1e-3:
            raise RuntimeError(
                f"video FPS {self.reader.fps} does not match expected {grid.source_fps}"
            )
        self.current_index = grid.start_frame
        self.playing = False
        self.zoom = 1.0
        self.center_x = self.reader.width / 2
        self.center_y = self.reader.height / 2
        self.last_transform = (0, 0, 1.0, 0, 0)
        self.status_message = "blind metadata only"

    def _move(self, delta: int) -> None:
        target = min(
            self.grid.end_frame,
            max(self.grid.start_frame, self.current_index + delta),
        )
        if not self.grid.contains(target):
            raise RuntimeError(f"navigation produced a non-grid frame: {target}")
        self.current_index = target

    def _jump(self) -> None:
        self.playing = False
        try:
            raw_value = input(
                f"jump to evaluation frame [{self.grid.start_frame}.."
                f"{self.grid.end_frame} step {self.grid.frame_step}]: "
            ).strip()
        except EOFError:
            self.status_message = "jump unavailable: terminal input is closed"
            return
        try:
            target = int(raw_value)
        except ValueError:
            self.status_message = f"invalid frame index: {raw_value!r}"
            print(f"WARNING: {self.status_message}", file=sys.stderr)
            return
        if not self.grid.contains(target):
            self.status_message = f"rejected non-grid frame {target}; value was not corrected"
            print(f"WARNING: {self.status_message}", file=sys.stderr)
            return
        self.current_index = target
        self.status_message = f"jumped to source frame {target}"

    def _set_zoom(self, zoom: float) -> None:
        self.zoom = min(8.0, max(1.0, zoom))
        if self.zoom == 1.0:
            self.center_x = self.reader.width / 2
            self.center_y = self.reader.height / 2
        self.status_message = f"zoom {self.zoom:.1f}x"

    def _mouse_callback(self, event: int, x: int, y: int, _flags: int, _data: object) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        crop_x, crop_y, scale, offset_x, offset_y = self.last_transform
        if scale <= 0:
            return
        source_x = crop_x + (x - offset_x) / scale
        source_y = crop_y + (y - offset_y) / scale
        self.center_x = min(self.reader.width, max(0.0, source_x))
        self.center_y = min(self.reader.height, max(0.0, source_y))
        self.status_message = (
            f"zoom center source=({self.center_x:.0f}, {self.center_y:.0f})"
        )

    def _render(self, frame: np.ndarray) -> np.ndarray:
        source_height, source_width = frame.shape[:2]
        crop_width = max(1, round(source_width / self.zoom))
        crop_height = max(1, round(source_height / self.zoom))
        x1 = round(self.center_x - crop_width / 2)
        y1 = round(self.center_y - crop_height / 2)
        x1 = min(source_width - crop_width, max(0, x1))
        y1 = min(source_height - crop_height, max(0, y1))
        crop = frame[y1:y1 + crop_height, x1:x1 + crop_width]

        scale = min(
            self.window_width / crop_width,
            self.window_height / crop_height,
        )
        view_width = max(1, round(crop_width * scale))
        view_height = max(1, round(crop_height * scale))
        view = cv2.resize(crop, (view_width, view_height), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((self.window_height, self.window_width, 3), dtype=np.uint8)
        offset_x = (self.window_width - view_width) // 2
        offset_y = (self.window_height - view_height) // 2
        canvas[offset_y:offset_y + view_height, offset_x:offset_x + view_width] = view
        self.last_transform = (x1, y1, scale, offset_x, offset_y)

        cv2.rectangle(canvas, (0, 0), (self.window_width, 92), (0, 0, 0), -1)
        timestamp = self.grid.timestamp_seconds(self.current_index)
        state = "PLAY" if self.playing else "PAUSE"
        cv2.putText(
            canvas,
            f"source frame {self.current_index} | PTS {timestamp:.6f} s | "
            f"EVALUATION FRAME | {state}",
            (18, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.85,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            f"source 3840x2160 | grid 4196..5994 step 2 | zoom {self.zoom:.1f}x | "
            f"{self.status_message}",
            (18, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (180, 255, 180),
            1,
            cv2.LINE_AA,
        )
        return canvas

    def _validate(self) -> None:
        warnings = validate_worksheets(
            self.objects_path,
            self.visibility_path,
            self.grid,
        )
        print_validation(warnings)
        self.status_message = (
            "worksheet validation OK"
            if not warnings
            else f"worksheet warnings: {len(warnings)} (see terminal)"
        )

    @staticmethod
    def print_help() -> None:
        print(
            "keys: Left/Right or a/d=1 evaluation frame; "
            "Shift+Left/Right or A/D=about 1 second; "
            "J/L or PageUp/PageDown=about 5 seconds; Space=play/pause; "
            "g=jump; +/-/0=zoom; mouse click=recenter; v=validate; q/Esc=quit"
        )

    def run(self) -> None:
        self._validate()
        self.print_help()
        try:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WINDOW_NAME, self.window_width, self.window_height)
            cv2.setMouseCallback(WINDOW_NAME, self._mouse_callback)
        except cv2.error as exc:
            raise RuntimeError(
                "OpenCV HighGUI is unavailable. Install a GUI-enabled OpenCV build "
                "and run in a desktop session; opencv-python-headless cannot open the viewer."
            ) from exc

        try:
            while True:
                frame = self.reader.read(self.current_index)
                cv2.imshow(WINDOW_NAME, self._render(frame))
                delay_ms = max(1, round(1000 / self.grid.evaluation_fps)) if self.playing else 0
                key = cv2.waitKeyEx(delay_ms)
                if key == -1:
                    if self.playing:
                        if self.current_index == self.grid.end_frame:
                            self.playing = False
                            self.status_message = "end of evaluation grid"
                        else:
                            self._move(self.grid.frame_step)
                    continue

                low_key = key & 0xFF
                if key in LEFT_KEYS or low_key == ord("a"):
                    self.playing = False
                    self._move(-self.grid.frame_step)
                elif key in RIGHT_KEYS or low_key == ord("d"):
                    self.playing = False
                    self._move(self.grid.frame_step)
                elif key in SHIFT_LEFT_KEYS or low_key == ord("A"):
                    self.playing = False
                    self._move(-self.grid.one_second_delta)
                elif key in SHIFT_RIGHT_KEYS or low_key == ord("D"):
                    self.playing = False
                    self._move(self.grid.one_second_delta)
                elif key in PAGE_BACK_KEYS or low_key == ord("J"):
                    self.playing = False
                    self._move(-self.grid.five_second_delta)
                elif key in PAGE_FORWARD_KEYS or low_key == ord("L"):
                    self.playing = False
                    self._move(self.grid.five_second_delta)
                elif low_key in {ord(" "), ord("p")}:
                    self.playing = not self.playing
                    self.status_message = "play" if self.playing else "pause"
                elif low_key == ord("g"):
                    self._jump()
                elif low_key in {ord("+"), ord("=")}:
                    self._set_zoom(self.zoom * 1.5)
                elif low_key in {ord("-"), ord("_")}:
                    self._set_zoom(self.zoom / 1.5)
                elif low_key == ord("0"):
                    self._set_zoom(1.0)
                elif low_key == ord("v"):
                    self._validate()
                elif low_key in {ord("h"), ord("?")}:
                    self.print_help()
                elif low_key == ord("q") or key == 27:
                    break
        finally:
            self.reader.close()
            cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Metadata-only viewer for the DJI_0482 Gate 3-A2 blind review."
    )
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--start-frame", type=int, default=4196)
    parser.add_argument("--end-frame", type=int, default=5994)
    parser.add_argument("--frame-step", type=int, default=2)
    parser.add_argument("--source-fps", type=float, default=30000 / 1001)
    parser.add_argument("--objects-worksheet", type=Path, default=DEFAULT_OBJECTS_WORKSHEET)
    parser.add_argument(
        "--visibility-worksheet",
        type=Path,
        default=DEFAULT_VISIBILITY_WORKSHEET,
    )
    parser.add_argument("--window-width", type=int, default=1600)
    parser.add_argument("--window-height", type=int, default=900)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate worksheets and exit without opening a GUI.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    grid = EvaluationGrid(
        start_frame=args.start_frame,
        end_frame=args.end_frame,
        frame_step=args.frame_step,
        source_fps=args.source_fps,
    )
    if grid.frame_count != 900:
        raise SystemExit(
            f"refusing non-canonical grid: expected 900 frames, got {grid.frame_count}"
        )

    if args.validate_only:
        warnings = validate_worksheets(
            args.objects_worksheet,
            args.visibility_worksheet,
            grid,
        )
        print_validation(warnings)
        raise SystemExit(1 if warnings else 0)

    viewer = BlindReviewViewer(
        video_path=args.video,
        objects_path=args.objects_worksheet,
        visibility_path=args.visibility_worksheet,
        grid=grid,
        window_width=args.window_width,
        window_height=args.window_height,
    )
    try:
        viewer.run()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
