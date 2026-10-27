from __future__ import annotations

from _paths import BASE

import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = BASE
RECORD_DIR = BASE_DIR / "record"
OUTPUT_DIR = BASE_DIR / "runs" / "phaseA_alignment"

VIDEOS = [
    ("DJI_0481", RECORD_DIR / "DJI_0481.MP4"),
    ("DJI_0482", RECORD_DIR / "DJI_0482.MP4"),
    ("DJI_0483_Cut", RECORD_DIR / "DJI_0483_Cut.mp4"),
    ("DJI_0484", RECORD_DIR / "DJI_0484.MP4"),
    ("DJI_0485", RECORD_DIR / "DJI_0485.MP4"),
    ("DJI_0486", RECORD_DIR / "DJI_0486.MP4"),
    ("DJI_0487", RECORD_DIR / "DJI_0487.MP4"),
    ("DJI_0488", RECORD_DIR / "DJI_0488.MP4"),
]

REFERENCE = "DJI_0481"
FRAME_POSITIONS = {"first": 0.0, "middle": 0.5, "last": 0.98}

# ROI 대표점: 통합 히트맵 판독에 사용되는 핵심 지점들 (0481 기준 픽셀 좌표)
ROI_CHECK_POINTS = {
    "crosswalk_northwest": (1617, 215),
    "crosswalk_southwest": (732, 965),
    "crosswalk_east": (3158, 1438),
    "roundabout_entry_west": (1145, 746),
    "roundabout_entry_south": (1608, 1210),
}


def read_frame(path: Path, position: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    target = min(max(int(total * position), 0), max(total - 1, 0))
    # cv2.set()은 키프레임 정확도 문제가 있으므로 grab으로 순차 접근하되
    # 큰 오프셋은 set 후 grab 검증으로 절충한다.
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    return frame


def estimate_homography(
    reference_gray: np.ndarray, target_gray: np.ndarray
) -> tuple[np.ndarray | None, int, float]:
    orb = cv2.ORB_create(nfeatures=6000)
    kp1, des1 = orb.detectAndCompute(reference_gray, None)
    kp2, des2 = orb.detectAndCompute(target_gray, None)
    if des1 is None or des2 is None or len(kp1) < 20 or len(kp2) < 20:
        return None, 0, float("nan")
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(matcher.match(des1, des2), key=lambda m: m.distance)
    matches = matches[: max(200, len(matches) // 3)]
    if len(matches) < 20:
        return None, len(matches), float("nan")
    src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if homography is None:
        return None, len(matches), float("nan")
    inliers = int(mask.sum())
    src_in = src[mask.ravel() == 1]
    dst_in = dst[mask.ravel() == 1]
    projected = cv2.perspectiveTransform(src_in, homography)
    rmse = float(np.sqrt(np.mean(np.sum((projected - dst_in) ** 2, axis=2))))
    return homography, inliers, rmse


def decompose(homography: np.ndarray) -> dict:
    a, b, tx = homography[0]
    c, d, ty = homography[1]
    scale = math.sqrt(abs(a * d - b * c))
    rotation_deg = math.degrees(math.atan2(c, a))
    return {"tx": tx, "ty": ty, "scale": scale, "rotation_deg": rotation_deg}


def point_shift(homography: np.ndarray, point: tuple[float, float]) -> float:
    src = np.float32([[point]])
    dst = cv2.perspectiveTransform(src, homography)[0][0]
    return float(math.hypot(dst[0] - point[0], dst[1] - point[1]))


def make_overlay(reference: np.ndarray, target: np.ndarray, out_path: Path) -> None:
    small_ref = cv2.resize(reference, None, fx=0.5, fy=0.5)
    small_tgt = cv2.resize(target, None, fx=0.5, fy=0.5)
    overlay = small_ref.copy()
    overlay[:, :, 1] = small_tgt[:, :, 1]  # G 채널만 대상 프레임: 어긋난 곳은 색분리로 보임
    cv2.imwrite(str(out_path), overlay)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reference_frame = read_frame(dict(VIDEOS)[REFERENCE], FRAME_POSITIONS["first"])
    if reference_frame is None:
        raise RuntimeError("Could not read reference frame")
    reference_gray = cv2.cvtColor(reference_frame, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(str(OUTPUT_DIR / "reference_DJI_0481_first.jpg"), reference_frame)

    rows = []
    for name, path in VIDEOS:
        if not path.exists():
            print(f"SKIP {name}: video not found")
            continue
        for pos_name, pos in FRAME_POSITIONS.items():
            frame = read_frame(path, pos)
            if frame is None:
                print(f"SKIP {name} {pos_name}: frame read failed")
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            homography, inliers, rmse = estimate_homography(reference_gray, gray)
            row = {
                "video": name,
                "frame_pos": pos_name,
                "inliers": inliers,
                "rmse_px": round(rmse, 2) if math.isfinite(rmse) else "",
            }
            if homography is not None:
                row.update({k: round(v, 3) for k, v in decompose(homography).items()})
                shifts = {
                    roi: point_shift(homography, pt) for roi, pt in ROI_CHECK_POINTS.items()
                }
                row["max_roi_shift_px"] = round(max(shifts.values()), 1)
                row["mean_roi_shift_px"] = round(sum(shifts.values()) / len(shifts), 1)
                for roi, value in shifts.items():
                    row[f"shift_{roi}"] = round(value, 1)
                if pos_name == "first" and name != REFERENCE:
                    make_overlay(
                        reference_frame, frame, OUTPUT_DIR / f"overlay_{name}_first.jpg"
                    )
            else:
                row["max_roi_shift_px"] = ""
                row["mean_roi_shift_px"] = ""
            rows.append(row)
            print(
                f"{name:>13} {pos_name:>6}: inliers={inliers:4d} rmse={row['rmse_px']} "
                f"max_roi_shift={row.get('max_roi_shift_px', '')}"
            )

    fieldnames = [
        "video", "frame_pos", "inliers", "rmse_px", "tx", "ty", "scale",
        "rotation_deg", "max_roi_shift_px", "mean_roi_shift_px",
    ] + [f"shift_{roi}" for roi in ROI_CHECK_POINTS]
    with (OUTPUT_DIR / "alignment_offsets.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    (OUTPUT_DIR / "alignment_metadata.json").write_text(
        json.dumps(
            {
                "reference": f"{REFERENCE} first frame",
                "method": "ORB(6000) + BFMatcher(Hamming, crossCheck) + RANSAC homography (reproj 5.0)",
                "roi_check_points": ROI_CHECK_POINTS,
                "note": "shift_* = 해당 ROI 대표점이 0481 기준틀에서 몇 px 이동해 보이는지",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved: {OUTPUT_DIR / 'alignment_offsets.csv'}")


if __name__ == "__main__":
    main()
