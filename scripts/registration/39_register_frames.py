"""영상 정합 (V-A2) — 페이즈 1.

구현 범위: 1-2(고정 기준점 후보 자동 검출 → 사용자 승인) + 1-3(프레임별 기준점 추적·
similarity 변환 추정). 1-1(기준 프레임 선정)은 이미 완료되어 calib/reference_frame.png +
clips.yaml site.registration_ref 에 기록되어 있다. 1-4(궤적 좌표 역변환)~1-5(정합 전/후
잔차 산출, V-A2 게이트 판정)는 1-3 결과 확인 이후 이 스크립트에 이어서 구현한다.

    python src/39_register_frames.py propose-points
    python src/39_register_frames.py track-points <clip_id>
    python src/39_register_frames.py propose-points-round2
    python src/39_register_frames.py validate-round2

track-points 는 클립 하나씩 실행한다. 8클립을 한 번에 돌리지 않는다 — 클립마다
실패율·잔차 분포를 확인하고 다음 클립으로 넘어간다(2026-08-14 사용자 결정).

2026-08-14 1-3(DJI_0481·DJI_0482) 실행 결과 점2·12·13이 매칭 불안정, 점5·6·14가
노면 위 구조물로 확인돼 6점을 기준점에서 제외 확정 — 1-2 재개(propose-points-round2
→ validate-round2). 유지 5점만으로는 min_inliers_per_frame(=6)을 채울 수 없어
빈 그리드 칸에 대해서만 후보를 다시 뽑고, 승인 전 자동 검증을 거친다.

산출(propose-points):
    registration/reference_points_candidates.json   후보 좌표·그리드 셀·점수
    registration/reference_points_preview.png        기준 프레임 위 번호 오버레이(승인용)
    registration/reference_points_candidates.meta.json

산출(track-points, 클립별 upsert — 기존 클립 행은 덮어쓰고 다른 클립 행은 보존):
    registration/frame_transforms.csv        clip_id·frame_id별 변환·인라이어·실패 여부
    registration/frame_transforms.meta.json  클립별 실패율·연속 실패 구간·잔차 분포

산출(propose-points-round2):
    registration/reference_points_candidates_round2.json
    registration/reference_points_preview_round2.png
    registration/reference_points_candidates_round2.meta.json

산출(validate-round2):
    registration/round2_validation_report.json   후보별 NCC·잔차·방향각·PASS/FAIL
    registration/round2_flagged_pt<id>_context.png  방향 플래그 후보 200x200 문맥(육안 판단용)
"""

from __future__ import annotations

# =============================================================================
# CANDIDATE GENERATION TUNING — 파라미터 규칙 1(CLAUDE.md 절대 규칙 1)의 명시적 예외
#
# 아래 값은 1-2(후보 제시) 단계에서만 쓰인다. 이 단계의 산출물은 확정 기준점이 아니라
# "사용자가 눈으로 보고 승인/기각하는 후보 목록"이며, 최종 채택은 전적으로 사용자
# 승인이 결정한다. 즉 이 값들을 조정해도 최종 정합 정확도·지표는 바뀌지 않는다 —
# 바뀌는 건 "사용자에게 몇 개·어떤 후보를 보여주느냐"뿐이다. 결과를 실제로 좌우하는
# registration.reference_points_min / transform_model / residual_tol_m 은 여전히
# load_params()로 파라미터 YAML에서 읽는다. 2026-08-13 사용자 결정.
#
# MASK_WINDOW_FRAMES: 물리적 속도로 역산하지 않는다. "계산 비용이 사실상 0이니
# 넉넉히 잡는다"는 원칙으로만 고정했다. 실행할 때마다 실제 마스킹 비율을 로그로
# 보고한다 — 그 비율이 이 값이 타당한지 판단하는 근거다.
MAX_CORNERS = 4000
QUALITY_LEVEL = 0.01
MIN_DISTANCE_PX = 15
BLOCK_SIZE = 5
VEG_HSV_LOWER = (35, 40, 40)
VEG_HSV_UPPER = (85, 255, 255)
VEG_MASK_CLOSE_PX = 31  # 침엽수 캐노피 내부의 밝은 하이라이트(저채도) 구멍을 메움 — 1차 실행 결과 확인 후 추가
MASK_WINDOW_FRAMES = 300  # ±300프레임 (~20.0s @ 29.97fps)
# =============================================================================

import csv
import json
import sys
import time

import cv2
import numpy as np
import yaml

from _paths import BASE

CALIB = BASE / "calib"
REG_OUT = BASE / "registration"
PARAMS_PATH = BASE / "docs" / "무신호횡단보도_파라미터_v02.yaml"
CLIPS_YAML_PATH = BASE / "clips.yaml"
RECORD_DIR = BASE / "record" / "before"

# alignment_homographies.json 의 클립 키 매핑. DJI_0483 은 _Cut 의 H 를 그대로 쓴다 —
# frame0 픽셀이 원본과 완전히 동일함이 T-2 무결성 검증으로 확인됨(DJI_0483_INTEGRITY_VERIFICATION.md).
CLIP_TO_HOMOG_KEY = {
    "DJI_0481": "DJI_0481", "DJI_0482": "DJI_0482", "DJI_0483": "DJI_0483_Cut",
    "DJI_0484": "DJI_0484", "DJI_0485": "DJI_0485", "DJI_0486": "DJI_0486",
    "DJI_0487": "DJI_0487", "DJI_0488": "DJI_0488",
}


def load_params() -> dict:
    return yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))


def load_clips() -> dict:
    return yaml.safe_load(CLIPS_YAML_PATH.read_text(encoding="utf-8"))


def get_reference_ref() -> tuple[str, int]:
    ref = load_clips()["site"]["registration_ref"]
    if ref["clip_id"] is None or ref["frame"] is None:
        raise RuntimeError("clips.yaml site.registration_ref 미기입 — 1-1(기준 프레임 선정)을 먼저 완료할 것")
    return ref["clip_id"], int(ref["frame"])


def load_detection_boxes(clip_id: str):
    path = BASE / "runs" / "before_l_mt09" / clip_id / "detections_pixel.csv"
    boxes = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            boxes.append((
                int(row["frame_id"]),
                float(row["x1"]), float(row["y1"]),
                float(row["x2"]), float(row["y2"]),
            ))
    return boxes


def build_dynamic_object_mask(ref_frame_id: int, boxes, shape) -> tuple[np.ndarray, float]:
    """기준 프레임 ±MASK_WINDOW_FRAMES 안의 모든 검지 박스를 합집합한 마스크.

    True = 이 픽셀에서는 코너 후보를 뽑지 않는다(차량·보행자 배제).
    """
    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    lo, hi = ref_frame_id - MASK_WINDOW_FRAMES, ref_frame_id + MASK_WINDOW_FRAMES
    n_boxes = 0
    for fid, x1, y1, x2, y2 in boxes:
        if lo <= fid <= hi:
            n_boxes += 1
            ix1, iy1 = max(0, int(x1)), max(0, int(y1))
            ix2, iy2 = min(w, int(x2) + 1), min(h, int(y2) + 1)
            mask[iy1:iy2, ix1:ix2] = True
    masked_pct = 100.0 * mask.sum() / mask.size
    print(
        f"[마스킹] frame_id {ref_frame_id} ±{MASK_WINDOW_FRAMES} "
        f"({2 * MASK_WINDOW_FRAMES + 1}프레임, {(2 * MASK_WINDOW_FRAMES + 1) / 29.97:.1f}s) "
        f"| 검지 박스 {n_boxes}개 | 마스킹 비율 {masked_pct:.2f}%"
    )
    return mask, masked_pct


def build_vegetation_mask(frame_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    veg = cv2.inRange(hsv, np.array(VEG_HSV_LOWER), np.array(VEG_HSV_UPPER))
    # 침엽수 캐노피 안쪽의 저채도 하이라이트(가지·햇빛 반사)는 HSV 임계값만으로는
    # 녹색으로 안 잡힌다 — 초록으로 완전히 둘러싸인 작은 구멍을 형태학적 닫힘으로 메움
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (VEG_MASK_CLOSE_PX, VEG_MASK_CLOSE_PX))
    veg = cv2.morphologyEx(veg, cv2.MORPH_CLOSE, kernel)
    return veg > 0


def assign_grid_cell(x: float, y: float, w: int, h: int, rows: int, cols: int) -> tuple[int, int]:
    col = min(cols - 1, int(x / w * cols))
    row = min(rows - 1, int(y / h * rows))
    return row, col


def propose_points() -> None:
    rpd = load_params()["registration"]["reference_point_detection"]
    grid_rows = rpd["grid_rows"]["value"]
    grid_cols = rpd["grid_cols"]["value"]
    n_min = rpd["candidates_to_present"]["min"]
    n_max = rpd["candidates_to_present"]["max"]

    clip_id, ref_frame_id = get_reference_ref()
    ref = cv2.imread(str(CALIB / "reference_frame.png"))
    if ref is None:
        raise FileNotFoundError(CALIB / "reference_frame.png")
    h, w = ref.shape[:2]
    gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)

    boxes = load_detection_boxes(clip_id)
    dyn_mask, masked_pct = build_dynamic_object_mask(ref_frame_id, boxes, ref.shape)
    veg_mask = build_vegetation_mask(ref)
    exclude_mask = dyn_mask | veg_mask
    veg_pct = 100.0 * veg_mask.sum() / veg_mask.size
    print(
        f"[마스킹] 초목(HSV) 비율 {veg_pct:.2f}% | 합산(차량·보행자+초목) 제외 비율 "
        f"{100.0 * exclude_mask.sum() / exclude_mask.size:.2f}%"
    )
    print("[마스킹] 그림자는 자동 검출하지 않음 — 승인 단계에서 사용자가 번호 보고 직접 제외")

    cv_mask = (~exclude_mask).astype(np.uint8) * 255
    corners = cv2.goodFeaturesToTrack(
        gray, maxCorners=MAX_CORNERS, qualityLevel=QUALITY_LEVEL,
        minDistance=MIN_DISTANCE_PX, blockSize=BLOCK_SIZE, mask=cv_mask,
    )
    if corners is None:
        raise RuntimeError("마스킹 후 코너 후보가 하나도 없음 — MASK_WINDOW_FRAMES/HSV 범위 재검토 필요")

    response = cv2.cornerMinEigenVal(gray, blockSize=BLOCK_SIZE)
    pts = []
    for c in corners[:, 0, :]:
        x, y = float(c[0]), float(c[1])
        r, col = assign_grid_cell(x, y, w, h, grid_rows, grid_cols)
        score = float(response[int(round(y)), int(round(x))])
        pts.append({"x": x, "y": y, "row": r, "col": col, "score": score})

    by_cell: dict[tuple[int, int], list[dict]] = {}
    for p in pts:
        by_cell.setdefault((p["row"], p["col"]), []).append(p)
    for cell_pts in by_cell.values():
        cell_pts.sort(key=lambda p: -p["score"])

    empty_cells = [
        (r, c) for r in range(grid_rows) for c in range(grid_cols) if (r, c) not in by_cell
    ]
    if empty_cells:
        print(f"[경고] 후보가 하나도 없는 그리드 칸: {empty_cells} (전부 마스킹됐거나 코너 없음)")

    # 1라운드 — 칸마다 최우수 후보 1개(공간 분산 보장)
    selected: list[dict] = [cell_pts[0] for cell_pts in by_cell.values()]
    # 2라운드 — 잔여 후보를 점수순으로 채워 max까지
    remaining = [p for cell_pts in by_cell.values() for p in cell_pts[1:]]
    remaining.sort(key=lambda p: -p["score"])
    for p in remaining:
        if len(selected) >= n_max:
            break
        selected.append(p)
    selected.sort(key=lambda p: -p["score"])

    if len(selected) < n_min:
        print(
            f"[경고] 후보 {len(selected)}개 < 최소 제시 목표 {n_min}개 — "
            f"마스킹 영역이 과도하거나 코너 자체가 부족함"
        )

    REG_OUT.mkdir(exist_ok=True)
    candidates = [
        {
            "id": i,
            "x_px": round(p["x"], 1),
            "y_px": round(p["y"], 1),
            "grid_row": p["row"],
            "grid_col": p["col"],
            "score": round(p["score"], 6),
        }
        for i, p in enumerate(selected, start=1)
    ]

    out_json = REG_OUT / "reference_points_candidates.json"
    out_json.write_text(
        json.dumps(
            {
                "clip_id": clip_id,
                "frame_id": ref_frame_id,
                "grid_rows": grid_rows,
                "grid_cols": grid_cols,
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    preview = ref.copy()
    for row in range(1, grid_rows):
        y = int(h * row / grid_rows)
        cv2.line(preview, (0, y), (w, y), (0, 255, 255), 2)
    for col in range(1, grid_cols):
        x = int(w * col / grid_cols)
        cv2.line(preview, (x, 0), (x, h), (0, 255, 255), 2)
    overlay = preview.copy()
    overlay[dyn_mask] = (0, 0, 255)
    overlay[veg_mask] = (0, 180, 0)
    preview = cv2.addWeighted(overlay, 0.25, preview, 0.75, 0)
    for c in candidates:
        pt = (int(c["x_px"]), int(c["y_px"]))
        cv2.circle(preview, pt, 14, (0, 140, 255), 4)
        cv2.putText(
            preview, str(c["id"]), (pt[0] + 16, pt[1] - 16),
            cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 140, 255), 4, cv2.LINE_AA,
        )
    out_png = REG_OUT / "reference_points_preview.png"
    cv2.imwrite(str(out_png), preview)

    meta = {
        "generated_by": "src/39_register_frames.py:propose_points",
        "inputs": {
            "reference_frame": str((CALIB / "reference_frame.png").relative_to(BASE)),
            "detections_csv": str(
                (BASE / "runs" / "before_l_mt09" / clip_id / "detections_pixel.csv").relative_to(BASE)
            ),
            "params_yaml": str(PARAMS_PATH.relative_to(BASE)),
            "params_yaml_keys_used": [
                "registration.reference_point_detection.grid_rows",
                "registration.reference_point_detection.grid_cols",
                "registration.reference_point_detection.candidates_to_present",
            ],
            "clips_yaml_keys_used": ["site.registration_ref"],
        },
        "clip_id": clip_id,
        "frame_id": ref_frame_id,
        "candidate_generation_tuning_note": (
            "MAX_CORNERS/QUALITY_LEVEL/MIN_DISTANCE_PX/BLOCK_SIZE/VEG_HSV_*/"
            "MASK_WINDOW_FRAMES는 파라미터 규칙 1의 예외(후보 생성 전용, 최종 결과 미영향). "
            "스크립트 상단 CANDIDATE GENERATION TUNING 블록 참고."
        ),
        "dynamic_mask_window_frames": MASK_WINDOW_FRAMES,
        "dynamic_mask_pct": round(masked_pct, 3),
        "vegetation_mask_pct": round(veg_pct, 3),
        "empty_grid_cells": empty_cells,
        "n_candidates_presented": len(candidates),
        "outputs": [str(out_json.relative_to(BASE)), str(out_png.relative_to(BASE))],
    }
    (REG_OUT / "reference_points_candidates.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[완료] 후보 {len(candidates)}개 → {out_json}")
    print(f"[완료] 검토용 이미지 → {out_png}")


# =============================================================================
# 1-2 재개(2026-08-14) — 빈 그리드 칸 후보 재검출
#
# 유지 5점(1·7·8·9·11)은 그대로 두고, 나머지 5칸에 대해서만 후보를 다시 뽑는다.
# 제외된 6점: 2·12·13(매칭 불안정, NCC 낮거나 재투영 잔차 상시 3px 초과) /
# 5·6·14(노면 위 0.1~0.2m 구조물로 육안 확인 — 평면 정합 가정 위반).
# 근거: docs/무신호횡단보도_파라미터_v02.yaml meta.changelog 0.2.3.
# =============================================================================
KEPT_IDS = {1, 7, 8, 9, 11}
REMOVED_IDS = {2, 5, 6, 12, 13, 14}
CANDIDATES_PER_EMPTY_CELL = 3  # 칸당 여유 후보(자동검증 탈락 대비) — evidence C, 1-2 후보생성값과 같은 성격의 예외


def propose_points_round2() -> None:
    rpd = load_params()["registration"]["reference_point_detection"]
    grid_rows = rpd["grid_rows"]["value"]
    grid_cols = rpd["grid_cols"]["value"]

    kept_ids, kept_ref_pts, kept_grid_cells = load_reference_points_final()
    kept_cells = {gc for pid, gc in zip(kept_ids, kept_grid_cells) if pid in KEPT_IDS}
    empty_cells = [
        (r, c) for r in range(grid_rows) for c in range(grid_cols) if (r, c) not in kept_cells
    ]
    print(f"[대상 칸] 유지 5점이 덮는 칸: {sorted(kept_cells)}")
    print(f"[대상 칸] 재검출 대상(빈 칸): {empty_cells}")

    clip_id, ref_frame_id = get_reference_ref()
    ref = cv2.imread(str(CALIB / "reference_frame.png"))
    if ref is None:
        raise FileNotFoundError(CALIB / "reference_frame.png")
    h, w = ref.shape[:2]
    gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)

    boxes = load_detection_boxes(clip_id)
    dyn_mask, masked_pct = build_dynamic_object_mask(ref_frame_id, boxes, ref.shape)
    veg_mask = build_vegetation_mask(ref)
    # 유지 5점 주변은 이미 승인된 지점이므로 재검출 대상에서 제외(중복 방지)
    kept_mask = np.zeros((h, w), dtype=bool)
    for x, y in kept_ref_pts:
        xi, yi = int(round(float(x))), int(round(float(y)))
        kept_mask[max(0, yi - MIN_DISTANCE_PX):yi + MIN_DISTANCE_PX, max(0, xi - MIN_DISTANCE_PX):xi + MIN_DISTANCE_PX] = True
    exclude_mask = dyn_mask | veg_mask | kept_mask

    cv_mask = (~exclude_mask).astype(np.uint8) * 255
    corners = cv2.goodFeaturesToTrack(
        gray, maxCorners=MAX_CORNERS, qualityLevel=QUALITY_LEVEL,
        minDistance=MIN_DISTANCE_PX, blockSize=BLOCK_SIZE, mask=cv_mask,
    )
    if corners is None:
        raise RuntimeError("마스킹 후 코너 후보가 하나도 없음")

    response = cv2.cornerMinEigenVal(gray, blockSize=BLOCK_SIZE)
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for c in corners[:, 0, :]:
        x, y = float(c[0]), float(c[1])
        r, col = assign_grid_cell(x, y, w, h, grid_rows, grid_cols)
        if (r, col) not in empty_cells:
            continue  # 이미 유지점이 덮는 칸은 재검출 안 함
        score = float(response[int(round(y)), int(round(x))])
        by_cell.setdefault((r, col), []).append({"x": x, "y": y, "row": r, "col": col, "score": score})

    still_empty = [cell for cell in empty_cells if cell not in by_cell]
    if still_empty:
        print(f"[경고] 재검출 후에도 후보가 하나도 없는 칸: {still_empty} — 이 칸은 무리해서 채우지 않는다")

    selected = []
    for cell in empty_cells:
        cell_pts = sorted(by_cell.get(cell, []), key=lambda p: -p["score"])[:CANDIDATES_PER_EMPTY_CELL]
        selected.extend(cell_pts)

    REG_OUT.mkdir(exist_ok=True)
    candidates = [
        {
            "id": 100 + i,  # 기존 1-14와 겹치지 않도록 101부터
            "x_px": round(p["x"], 1), "y_px": round(p["y"], 1),
            "grid_row": p["row"], "grid_col": p["col"], "score": round(p["score"], 6),
        }
        for i, p in enumerate(selected, start=1)
    ]

    out_json = REG_OUT / "reference_points_candidates_round2.json"
    out_json.write_text(
        json.dumps(
            {
                "clip_id": clip_id, "frame_id": ref_frame_id,
                "kept_ids": sorted(KEPT_IDS), "removed_ids": sorted(REMOVED_IDS),
                "target_empty_cells": empty_cells, "still_empty_cells": still_empty,
                "candidates": candidates,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    preview = ref.copy()
    for row in range(1, grid_rows):
        y = int(h * row / grid_rows)
        cv2.line(preview, (0, y), (w, y), (0, 255, 255), 2)
    for col in range(1, grid_cols):
        x = int(w * col / grid_cols)
        cv2.line(preview, (x, 0), (x, h), (0, 255, 255), 2)
    for pid, (x, y) in zip(kept_ids, kept_ref_pts):
        if pid in KEPT_IDS:
            pt = (int(x), int(y))
            cv2.circle(preview, pt, 14, (0, 200, 0), 4)
            cv2.putText(preview, str(pid), (pt[0] + 16, pt[1] - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 200, 0), 4, cv2.LINE_AA)
    for c in candidates:
        pt = (int(c["x_px"]), int(c["y_px"]))
        cv2.circle(preview, pt, 14, (0, 140, 255), 4)
        cv2.putText(preview, str(c["id"]), (pt[0] + 16, pt[1] - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 140, 255), 4, cv2.LINE_AA)
    out_png = REG_OUT / "reference_points_preview_round2.png"
    cv2.imwrite(str(out_png), preview)

    meta = {
        "generated_by": "src/39_register_frames.py:propose_points_round2",
        "kept_ids": sorted(KEPT_IDS), "removed_ids": sorted(REMOVED_IDS),
        "target_empty_cells": empty_cells, "still_empty_cells": still_empty,
        "n_candidates_presented": len(candidates),
        "outputs": [str(out_json.relative_to(BASE)), str(out_png.relative_to(BASE))],
    }
    (REG_OUT / "reference_points_candidates_round2.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[완료] round2 후보 {len(candidates)}개 → {out_json}")
    print(f"[완료] 검토용 이미지 → {out_png}")


# =============================================================================
# 1-3 — 프레임별 기준점 추적 · similarity 변환 추정
# =============================================================================


def first_frame(video_path) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"프레임 읽기 실패: {video_path}")
    return frame


def estimate_h_to_ref(gray_src: np.ndarray, gray_ref: np.ndarray) -> np.ndarray:
    """27번 스크립트(src/27_make_interim_outputs.py estimate_h_to_ref)와 동일한 방법.

    ORB(nfeatures=6000) + BFMatcher(Hamming, crossCheck) 상위 max(200, n//3)매치 +
    findHomography(RANSAC, 5.0px). 여기서는 클립 첫 프레임의 탐색 시작 위치(seed)를
    구하는 용도로만 쓴다 — 최종 변환이 아니다.
    """
    orb = cv2.ORB_create(nfeatures=6000)
    kp1, des1 = orb.detectAndCompute(gray_src, None)
    kp2, des2 = orb.detectAndCompute(gray_ref, None)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(bf.match(des1, des2), key=lambda m: m.distance)
    matches = matches[: max(200, len(matches) // 3)]
    src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return H


def load_reference_points_final():
    data = json.loads((REG_OUT / "reference_points_final.json").read_text(encoding="utf-8"))
    ids = [p["id"] for p in data["points"]]
    coords = np.array([[p["x_px"], p["y_px"]] for p in data["points"]], dtype=np.float32)
    grid_cells = [(p["grid_row"], p["grid_col"]) for p in data["points"]]
    return ids, coords, grid_cells


def extract_templates(ref_gray: np.ndarray, coords: np.ndarray, radius: int) -> list[np.ndarray]:
    h, w = ref_gray.shape
    templates = []
    for x, y in coords:
        xi, yi = int(round(float(x))), int(round(float(y)))
        x0, x1 = max(0, xi - radius), min(w, xi + radius + 1)
        y0, y1 = max(0, yi - radius), min(h, yi + radius + 1)
        templates.append(ref_gray[y0:y1, x0:x1].copy())
    return templates


def get_frame0_seed_inv_h(clip_id: str, ref_gray: np.ndarray, ref_clip_id: str) -> np.ndarray:
    """ref-frame 좌표 -> 이 클립 frame0 픽셀좌표로 매핑하는 H(3x3)의 역변환.

    DJI_0481 자체도 frame0(파일 시작)과 기준 프레임(frame 2848, t≈95s)이 다르므로
    동일한 방법을 쓴다 — 2026-08-14 측정(registration/clip_first_frame_offset_diagnostic.json)
    결과 항등변환 가정 시 어긋남이 DJI_0481조차 평균 13.4px(최대 20.7px), 나머지
    클립은 27~195px로 search_radius_px(15px)를 훨씬 초과해 전 클립에 적용한다.
    탐색 시작 위치로만 쓰므로 27번(alignment_homographies.json) 폐기 판단
    (MIGRATION_PLAN.md §5)과 충돌하지 않는다.
    """
    f0_ref_clip_gray = cv2.cvtColor(first_frame(RECORD_DIR / f"{ref_clip_id}.MP4"), cv2.COLOR_BGR2GRAY)
    h_within = estimate_h_to_ref(f0_ref_clip_gray, ref_gray)  # ref_clip frame0 -> ref(frame 2848)
    if clip_id == ref_clip_id:
        h_total = h_within
    else:
        homog = json.loads((CALIB / "alignment_homographies.json").read_text(encoding="utf-8"))["videos"]
        h_clip = np.array(homog[CLIP_TO_HOMOG_KEY[clip_id]]["h"], dtype=np.float64)  # clip frame0 -> ref_clip frame0
        h_total = h_within @ h_clip  # clip frame0 -> ref
    return np.linalg.inv(h_total)  # ref -> clip frame0


def get_clip_fps_and_usable_duration(clip_id: str) -> tuple[float, float]:
    for c in load_clips()["clips"]:
        if c["clip_id"] == clip_id:
            return c["fps"], c.get("usable_duration_s", c["duration_s"])
    raise KeyError(f"clips.yaml 에 {clip_id} 없음")


def write_frame_transforms(rows: list[dict], clip_id: str) -> None:
    path = REG_OUT / "frame_transforms.csv"
    fieldnames = [
        "clip_id", "frame_id", "scale", "rotation_deg", "tx", "ty",
        "n_inliers", "n_points_tracked", "status", "inlier_grid_cells", "residual_rms_px",
    ]
    existing = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f) if r["clip_id"] != clip_id]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in existing:
            w.writerow(r)
        for r in rows:
            w.writerow(r)


def write_frame_transforms_meta(clip_id: str, summary: dict) -> None:
    path = REG_OUT / "frame_transforms.meta.json"
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data["generated_by"] = "src/39_register_frames.py:track_points"
    data["params_yaml_keys_used"] = [
        "registration.transform_model",
        "registration.point_tracking.search_radius_px",
        "registration.point_tracking.template_radius_px",
        "registration.point_tracking.ransac_reproj_threshold_px",
        "registration.point_tracking.min_inliers_per_frame",
    ]
    data.setdefault("clips", {})[clip_id] = summary
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def track_points(clip_id: str) -> None:
    params = load_params()
    reg = params["registration"]
    if reg["transform_model"] != "similarity":
        raise RuntimeError("registration.transform_model 이 similarity 가 아님 — 임의 승격 금지")
    pt = reg["point_tracking"]
    search_r = pt["search_radius_px"]["value"]
    tmpl_r = pt["template_radius_px"]["value"]
    ransac_thr = pt["ransac_reproj_threshold_px"]["value"]
    min_inliers = pt["min_inliers_per_frame"]["value"]

    ref_clip_id, ref_frame_id = get_reference_ref()
    ref_img = cv2.imread(str(CALIB / "reference_frame.png"))
    if ref_img is None:
        raise FileNotFoundError(CALIB / "reference_frame.png")
    ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
    frame_h, frame_w = ref_gray.shape

    ids, ref_pts, grid_cells = load_reference_points_final()
    n_pts = len(ids)
    templates = extract_templates(ref_gray, ref_pts, tmpl_r)

    seed_inv_h = get_frame0_seed_inv_h(clip_id, ref_gray, ref_clip_id)
    predicted = cv2.perspectiveTransform(ref_pts.reshape(-1, 1, 2), seed_inv_h).reshape(-1, 2)

    fps, usable_s = get_clip_fps_and_usable_duration(clip_id)
    max_frame_id = int(round(usable_s * fps))

    video_path = RECORD_DIR / f"{clip_id}.MP4"
    cap = cv2.VideoCapture(str(video_path))

    rows: list[dict] = []
    prev_M = None
    fail_run_lengths: list[int] = []
    current_fail_run = 0
    n_ok = 0
    n_failed = 0
    residuals: list[float] = []

    t0 = time.time()
    frame_id = 0
    while frame_id < max_frame_id:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        matched = np.zeros((n_pts, 2), dtype=np.float32)
        roi_half = search_r + tmpl_r
        for i in range(n_pts):
            px, py = predicted[i]
            x0 = int(round(float(px))) - roi_half
            y0 = int(round(float(py))) - roi_half
            x1, y1 = x0 + 2 * roi_half + 1, y0 + 2 * roi_half + 1
            x0c, y0c = max(0, x0), max(0, y0)
            x1c, y1c = min(frame_w, x1), min(frame_h, y1)
            roi = gray[y0c:y1c, x0c:x1c]
            tmpl = templates[i]
            if roi.shape[0] < tmpl.shape[0] or roi.shape[1] < tmpl.shape[1]:
                matched[i] = predicted[i]  # 프레임 경계 밖 — 예측 위치 유지, RANSAC이 걸러내길 기대
                continue
            res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
            # 미조치(2026-08-14, PHASE1_REGISTRATION_DIAGNOSIS_20260814.md §6): 상관값
            # 하한 검사 없음, subpixel 보간 없음(minMaxLoc은 정수 픽셀만 반환). 구현하지 않음
            # — 관측범위 문제로 CEI 산출이 보류돼 우선순위 없음. 재개 시 검토.
            _, _, _, max_loc = cv2.minMaxLoc(res)
            matched[i, 0] = x0c + max_loc[0] + tmpl_r
            matched[i, 1] = y0c + max_loc[1] + tmpl_r

        M, inlier_mask = cv2.estimateAffinePartial2D(
            ref_pts, matched, method=cv2.RANSAC, ransacReprojThreshold=ransac_thr
        )
        n_inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0

        if M is not None and n_inliers >= min_inliers:
            status = "OK"
            n_ok += 1
            inlier_idx = [i for i in range(n_pts) if inlier_mask[i, 0]]
            inlier_cells = sorted(set(grid_cells[i] for i in inlier_idx))
            proj = cv2.transform(ref_pts[inlier_idx].reshape(-1, 1, 2), M).reshape(-1, 2)
            resid = np.linalg.norm(matched[inlier_idx] - proj, axis=1)
            residual_rms = float(np.sqrt(np.mean(resid ** 2)))
            residuals.append(residual_rms)
            scale = float(np.hypot(M[0, 0], M[1, 0]))
            rot_deg = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
            tx, ty = float(M[0, 2]), float(M[1, 2])
            prev_M = M
            predicted = cv2.transform(ref_pts.reshape(-1, 1, 2), prev_M).reshape(-1, 2)
            if current_fail_run > 0:
                fail_run_lengths.append(current_fail_run)
                current_fail_run = 0
        else:
            status = "FAILED"
            n_failed += 1
            current_fail_run += 1
            inlier_cells = []
            residual_rms = scale = rot_deg = tx = ty = None
            if prev_M is not None:
                predicted = cv2.transform(ref_pts.reshape(-1, 1, 2), prev_M).reshape(-1, 2)
            # prev_M 이 아직 없으면(첫 프레임부터 실패) seed 예측 위치를 그대로 유지

        rows.append({
            "clip_id": clip_id, "frame_id": frame_id,
            "scale": scale, "rotation_deg": rot_deg, "tx": tx, "ty": ty,
            "n_inliers": n_inliers, "n_points_tracked": n_pts, "status": status,
            "inlier_grid_cells": ";".join(f"{r},{c}" for r, c in inlier_cells),
            "residual_rms_px": residual_rms,
        })
        frame_id += 1

    cap.release()
    if current_fail_run > 0:
        fail_run_lengths.append(current_fail_run)
    elapsed_s = time.time() - t0

    n_total = n_ok + n_failed
    residual_summary = None
    if residuals:
        arr = np.array(residuals)
        residual_summary = {
            "mean_px": float(arr.mean()), "median_px": float(np.median(arr)),
            "p95_px": float(np.percentile(arr, 95)), "max_px": float(arr.max()),
            "n": len(arr),
        }
    fail_run_summary = {
        "n_runs": len(fail_run_lengths),
        "lengths": fail_run_lengths,
        "max_run": max(fail_run_lengths) if fail_run_lengths else 0,
        "mean_run": float(np.mean(fail_run_lengths)) if fail_run_lengths else 0.0,
    }

    write_frame_transforms(rows, clip_id)
    write_frame_transforms_meta(clip_id, {
        "n_frames_processed": n_total, "n_ok": n_ok, "n_failed": n_failed,
        "fail_rate_pct": round(100.0 * n_failed / n_total, 3) if n_total else None,
        "consecutive_fail_runs": fail_run_summary,
        "residual_rms_px": residual_summary,
        "elapsed_s": round(elapsed_s, 1),
        "reference_clip_id": ref_clip_id, "reference_frame_id": ref_frame_id,
        "params_used": {
            "search_radius_px": search_r, "template_radius_px": tmpl_r,
            "ransac_reproj_threshold_px": ransac_thr, "min_inliers_per_frame": min_inliers,
        },
    })

    print(f"[완료] {clip_id}: {n_total}프레임 처리, OK {n_ok} / FAILED {n_failed} "
          f"({100.0 * n_failed / n_total:.2f}% 실패), 소요 {elapsed_s:.1f}s")
    if residual_summary:
        print(f"[잔차] mean {residual_summary['mean_px']:.3f}px / median {residual_summary['median_px']:.3f}px "
              f"/ p95 {residual_summary['p95_px']:.3f}px / max {residual_summary['max_px']:.3f}px")
    print(f"[연속 실패 구간] {fail_run_summary['n_runs']}개, 최대 길이 {fail_run_summary['max_run']}프레임, "
          f"평균 길이 {fail_run_summary['mean_run']:.1f}프레임")
    print(f"[산출] registration/frame_transforms.csv (clip_id={clip_id} 행 upsert)")
    print(f"[산출] registration/frame_transforms.meta.json (clip_id={clip_id} 항목 upsert)")


# =============================================================================
# 1-2 재개(2026-08-14) — 승인 전 자동 검증
# =============================================================================


def load_round2_candidates():
    data = json.loads((REG_OUT / "reference_points_candidates_round2.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["candidates"]]
    coords = np.array([[c["x_px"], c["y_px"]] for c in data["candidates"]], dtype=np.float32)
    cells = [(c["grid_row"], c["grid_col"]) for c in data["candidates"]]
    return ids, coords, cells


# 미조치(2026-08-14, docs/PHASE1_REGISTRATION_DIAGNOSIS_20260814.md §6):
#   1. NCC 하한 검사 없음 — scores를 반환하지만 이 함수도 호출부도 하한 검사를 하지 않는다.
#      낮은 신뢰도 매칭도 그대로 RANSAC에 입력된다. 구현하지 않음(관측범위 문제로 CEI
#      산출 자체가 보류돼 우선순위가 없어짐 — 재개 시 검토).
#   2. Subpixel 보간 없음 — cv2.minMaxLoc이 정수 픽셀 위치만 반환한다. matched 좌표가
#      항상 정수 격자에 고정됨(frame 0-4400, 11점, 48,411개 좌표값 전수 확인 — 비정수 0개).
#      최대 0.5px 계통오차. 구현하지 않음(위와 같은 이유).
def match_points_with_scores(gray, predicted, templates_list, roi_half, tmpl_r, frame_w, frame_h):
    matched = np.zeros((len(templates_list), 2), dtype=np.float32)
    scores = [None] * len(templates_list)
    for i, tmpl in enumerate(templates_list):
        px, py = predicted[i]
        x0 = int(round(float(px))) - roi_half
        y0 = int(round(float(py))) - roi_half
        x1, y1 = x0 + 2 * roi_half + 1, y0 + 2 * roi_half + 1
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(frame_w, x1), min(frame_h, y1)
        roi = gray[y0c:y1c, x0c:x1c]
        if roi.shape[0] < tmpl.shape[0] or roi.shape[1] < tmpl.shape[1]:
            matched[i] = predicted[i]
            continue
        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        matched[i, 0] = x0c + max_loc[0] + tmpl_r
        matched[i, 1] = y0c + max_loc[1] + tmpl_r
        scores[i] = float(max_val)
    return matched, scores


def validate_round2_candidates() -> None:
    params = load_params()
    reg = params["registration"]
    pt = reg["point_tracking"]
    search_r = pt["search_radius_px"]["value"]
    tmpl_r = pt["template_radius_px"]["value"]
    ransac_thr = pt["ransac_reproj_threshold_px"]["value"]

    val = reg["reference_point_validation"]
    test_clips = val["test_clips"]
    windows_by_clip = val["test_window_frames"]
    min_base_inliers = val["min_inliers_for_base_fit"]["value"]
    ncc_min = val["ncc_mean_min"]["value"]
    resid_mean_max = val["residual_mean_max_px"]["value"]
    resid_p95_max = val["residual_p95_max_px"]["value"]
    angle_max = val["direction_radial_angle_max_deg"]["value"]

    ref_clip_id, ref_frame_id = get_reference_ref()
    ref_img = cv2.imread(str(CALIB / "reference_frame.png"))
    ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
    frame_h, frame_w = ref_gray.shape
    center = np.array([frame_w / 2.0, frame_h / 2.0])
    roi_half = search_r + tmpl_r

    all_ids, all_ref_pts, _ = load_reference_points_final()
    kept_idx = [i for i, pid in enumerate(all_ids) if pid in KEPT_IDS]
    kept_ids = [all_ids[i] for i in kept_idx]
    kept_ref_pts = all_ref_pts[kept_idx]
    kept_templates = extract_templates(ref_gray, kept_ref_pts, tmpl_r)

    cand_ids, cand_ref_pts, cand_cells = load_round2_candidates()
    cand_templates = extract_templates(ref_gray, cand_ref_pts, tmpl_r)
    n_cand = len(cand_ids)

    # clip -> {cand_id: {"ncc": [...], "resid_by_base": {4: [...], 5: [...]}, "vecs": [...]}}
    per_clip_results: dict[str, dict[int, dict]] = {
        clip_id: {cid: {"ncc": [], "resid_by_base": {4: [], 5: []}, "vecs": []} for cid in cand_ids}
        for clip_id in test_clips
    }

    for clip_id in test_clips:
        windows = windows_by_clip[clip_id]
        window_ranges = [tuple(windows[k]) for k in ("front", "mid", "end")]
        max_frame = max(hi for lo, hi in window_ranges)
        print(f"[검증] {clip_id}: 구간 {window_ranges}, {max_frame}프레임까지 디코드")

        seed_inv_h = get_frame0_seed_inv_h(clip_id, ref_gray, ref_clip_id)
        predicted_kept = cv2.perspectiveTransform(kept_ref_pts.reshape(-1, 1, 2), seed_inv_h).reshape(-1, 2)

        cap = cv2.VideoCapture(str(RECORD_DIR / f"{clip_id}.MP4"))
        prev_M_base = None
        n_base_ok_frames = 0

        frame_id = 0
        while frame_id < max_frame:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            in_window = any(lo <= frame_id < hi for lo, hi in window_ranges)

            matched_kept, _ = match_points_with_scores(
                gray, predicted_kept, kept_templates, roi_half, tmpl_r, frame_w, frame_h
            )
            M_base, mask_base = cv2.estimateAffinePartial2D(
                kept_ref_pts, matched_kept, method=cv2.RANSAC, ransacReprojThreshold=ransac_thr
            )
            n_base = int(mask_base.sum()) if mask_base is not None else 0
            base_ok = M_base is not None and n_base >= min_base_inliers

            if in_window and base_ok:
                n_base_ok_frames += 1
                predicted_cand = cv2.transform(cand_ref_pts.reshape(-1, 1, 2), M_base).reshape(-1, 2)
                matched_cand, scores_cand = match_points_with_scores(
                    gray, predicted_cand, cand_templates, roi_half, tmpl_r, frame_w, frame_h
                )
                bucket = 5 if n_base >= 5 else 4
                for i, cid in enumerate(cand_ids):
                    resid = float(np.linalg.norm(matched_cand[i] - predicted_cand[i]))
                    per_clip_results[clip_id][cid]["resid_by_base"][bucket].append(resid)
                    per_clip_results[clip_id][cid]["vecs"].append(matched_cand[i] - predicted_cand[i])
                    if scores_cand[i] is not None:
                        per_clip_results[clip_id][cid]["ncc"].append(scores_cand[i])

            if base_ok:
                prev_M_base = M_base
            if prev_M_base is not None:
                predicted_kept = cv2.transform(kept_ref_pts.reshape(-1, 1, 2), prev_M_base).reshape(-1, 2)
            frame_id += 1
        cap.release()
        print(f"[검증] {clip_id}: 대상 구간 내 base_ok 프레임 {n_base_ok_frames}개")

    # ---- 집계 ----
    report = {"candidates": []}
    print()
    print(f"{'id':>5s} {'cell':>7s} | " + " | ".join(
        f"{c}:ncc(mean/min) resid(mean/p95,5/5|4/5)" for c in test_clips
    ) + " | dir_flag | PASS")
    for idx, cid in enumerate(cand_ids):
        row = {"id": cid, "grid_cell": list(cand_cells[idx]), "per_clip": {}, "direction_flag": False}
        overall_pass = True
        radial_dir = cand_ref_pts[idx] - center
        radial_dir_norm = radial_dir / (np.linalg.norm(radial_dir) + 1e-9)
        angles = {}
        parts = []
        for clip_id in test_clips:
            r = per_clip_results[clip_id][cid]
            ncc_arr = np.array(r["ncc"]) if r["ncc"] else np.array([])
            resid_all = r["resid_by_base"][4] + r["resid_by_base"][5]
            resid_arr = np.array(resid_all) if resid_all else np.array([])
            ncc_mean = float(ncc_arr.mean()) if ncc_arr.size else None
            ncc_min_v = float(ncc_arr.min()) if ncc_arr.size else None
            resid_mean = float(resid_arr.mean()) if resid_arr.size else None
            resid_p95 = float(np.percentile(resid_arr, 95)) if resid_arr.size else None
            resid_mean_5 = float(np.mean(r["resid_by_base"][5])) if r["resid_by_base"][5] else None
            resid_mean_4 = float(np.mean(r["resid_by_base"][4])) if r["resid_by_base"][4] else None
            n5, n4 = len(r["resid_by_base"][5]), len(r["resid_by_base"][4])

            vecs = np.array(r["vecs"]) if r["vecs"] else np.zeros((0, 2))
            mean_vec = vecs.mean(axis=0) if len(vecs) else np.array([0.0, 0.0])
            vec_norm = mean_vec / (np.linalg.norm(mean_vec) + 1e-9)
            angle_deg = float(np.degrees(np.arccos(np.clip(np.dot(radial_dir_norm, vec_norm), -1, 1))))
            angles[clip_id] = angle_deg

            passed = (
                ncc_mean is not None and ncc_mean >= ncc_min
                and resid_mean is not None and resid_mean <= resid_mean_max
                and resid_p95 is not None and resid_p95 <= resid_p95_max
            )
            overall_pass = overall_pass and passed

            row["per_clip"][clip_id] = {
                "ncc_mean": ncc_mean, "ncc_min": ncc_min_v,
                "resid_mean": resid_mean, "resid_p95": resid_p95,
                "resid_mean_5of5": resid_mean_5, "n_5of5": n5,
                "resid_mean_4of5": resid_mean_4, "n_4of5": n4,
                "mean_vec": mean_vec.tolist(), "angle_vs_radial_deg": angle_deg,
            }
            ncc_s = f"{ncc_mean:.3f}/{ncc_min_v:.3f}" if ncc_mean is not None else "N/A"
            resid_s = f"{resid_mean:.2f}/{resid_p95:.2f}"
            resid5_s = f"{resid_mean_5:.2f}({n5})" if resid_mean_5 is not None else "-"
            resid4_s = f"{resid_mean_4:.2f}({n4})" if resid_mean_4 is not None else "-"
            parts.append(f"ncc={ncc_s} resid={resid_s} [5/5={resid5_s} 4/5={resid4_s}] ang={angle_deg:.0f}")

        dir_flag = all(angles.get(c, 999) < angle_max for c in test_clips)
        row["direction_flag"] = dir_flag
        row["pass"] = overall_pass
        report["candidates"].append(row)

        cell_s = f"({cand_cells[idx][0]},{cand_cells[idx][1]})"
        print(f"{cid:5d} {cell_s:>7s} | " + " | ".join(parts) +
              f" | {'HEIGHT?' if dir_flag else '-':>8s} | {'PASS' if overall_pass else 'fail'}")

    report["thresholds"] = {
        "ncc_mean_min": ncc_min, "residual_mean_max_px": resid_mean_max,
        "residual_p95_max_px": resid_p95_max, "direction_radial_angle_max_deg": angle_max,
        "min_inliers_for_base_fit": min_base_inliers,
    }
    report["kept_ids"] = sorted(KEPT_IDS)
    report["removed_ids"] = sorted(REMOVED_IDS)
    out_path = REG_OUT / "round2_validation_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[완료] 검증표 → {out_path}")

    # 방향 플래그 후보 200x200 문맥 이미지
    flagged = [row for row in report["candidates"] if row["direction_flag"]]
    if flagged:
        CTX, TMPL_R = 100, tmpl_r
        for row in flagged:
            cid = row["id"]
            x, y = cand_ref_pts[cand_ids.index(cid)]
            xi, yi = int(round(float(x))), int(round(float(y)))
            x0, y0 = max(0, xi - CTX), max(0, yi - CTX)
            crop = ref_img[y0:yi + CTX, x0:xi + CTX].copy()
            lx, ly = xi - x0, yi - y0
            cv2.drawMarker(crop, (lx, ly), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
            cv2.rectangle(crop, (lx - TMPL_R, ly - TMPL_R), (lx + TMPL_R, ly + TMPL_R), (0, 255, 255), 2)
            cv2.putText(crop, f"pt{cid} HEIGHT?", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
            out_img = REG_OUT / f"round2_flagged_pt{cid}_context.png"
            cv2.imwrite(str(out_img), crop)
            print(f"[플래그] pt{cid} 방향 플래그(높이 의심) 문맥 이미지 → {out_img}")
    else:
        print("[플래그] 방향 플래그 후보 없음")


# =============================================================================
# 1-2 재개(2026-08-14) — 사용자 수동 지정점 검증
#
# round2 자동 검증(5점 기준모델로 후보를 개별 평가)은 기준모델 자체가 화면
# 오른쪽에 쏠려 있어 먼 후보의 잔차가 부풀려지는 구조적 한계가 드러났다
# (2026-08-14, r=0.58~0.64 거리상관 확인). 사용자가 노면 여부를 육안으로
# 직접 확인해 지정한 점은, 후보 취급하지 않고 유지 5점과 동등하게 하나의
# RANSAC 적합에 전부 포함시켜 평가한다 — production(track_points)과 같은
# min_inliers_per_frame(=6) 기준을 그대로 쓴다.
#
# 입력 파일: registration/round2_manual_points.json
#   {"points": [{"id": <int>, "x_px": <float>, "y_px": <float>, "grid_cell": [row,col]}, ...]}
# =============================================================================


def load_manual_points():
    path = REG_OUT / "round2_manual_points.json"
    if not path.exists():
        raise RuntimeError(f"{path} 없음 — 사용자 지정 좌표를 먼저 저장할 것")
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [p["id"] for p in data["points"]]
    coords = np.array([[p["x_px"], p["y_px"]] for p in data["points"]], dtype=np.float32)
    cells = [tuple(p["grid_cell"]) for p in data["points"]]
    return ids, coords, cells


def validate_manual_points() -> None:
    params = load_params()
    reg = params["registration"]
    pt = reg["point_tracking"]
    search_r = pt["search_radius_px"]["value"]
    tmpl_r = pt["template_radius_px"]["value"]
    ransac_thr = pt["ransac_reproj_threshold_px"]["value"]
    min_inliers = pt["min_inliers_per_frame"]["value"]

    val = reg["reference_point_validation"]
    test_clips = val["test_clips"]
    windows_by_clip = val["test_window_frames"]
    angle_max = val["direction_radial_angle_max_deg"]["value"]

    ref_clip_id, ref_frame_id = get_reference_ref()
    ref_img = cv2.imread(str(CALIB / "reference_frame.png"))
    ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
    frame_h, frame_w = ref_gray.shape
    center = np.array([frame_w / 2.0, frame_h / 2.0])
    roi_half = search_r + tmpl_r

    all_ids, all_ref_pts, all_cells = load_reference_points_final()
    kept_idx = [i for i, pid in enumerate(all_ids) if pid in KEPT_IDS]
    kept_ids = [all_ids[i] for i in kept_idx]
    kept_ref_pts = all_ref_pts[kept_idx]
    kept_cells = [all_cells[i] for i in kept_idx]

    manual_ids, manual_ref_pts, manual_cells = load_manual_points()

    ids = kept_ids + manual_ids
    ref_pts = np.vstack([kept_ref_pts, manual_ref_pts])
    cells = kept_cells + manual_cells
    n_pts = len(ids)
    templates = extract_templates(ref_gray, ref_pts, tmpl_r)
    print(f"[검증] 전체 {n_pts}점: 유지 {kept_ids} + 수동지정 {manual_ids}")

    per_clip = {
        clip_id: {
            "ncc": {pid: [] for pid in ids}, "resid": {pid: [] for pid in ids},
            "inlier": {pid: [] for pid in ids}, "vecs": {pid: [] for pid in ids},
            "frame_status": [],
        }
        for clip_id in test_clips
    }

    for clip_id in test_clips:
        windows = windows_by_clip[clip_id]
        window_list = [(name, tuple(windows[name])) for name in ("front", "mid", "end")]
        max_frame = max(hi for _, (lo, hi) in window_list)
        print(f"[검증] {clip_id}: 구간 {window_list}, {max_frame}프레임까지 디코드")

        seed_inv_h = get_frame0_seed_inv_h(clip_id, ref_gray, ref_clip_id)
        predicted = cv2.perspectiveTransform(ref_pts.reshape(-1, 1, 2), seed_inv_h).reshape(-1, 2)

        cap = cv2.VideoCapture(str(RECORD_DIR / f"{clip_id}.MP4"))
        prev_M = None

        frame_id = 0
        while frame_id < max_frame:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            win_tag = None
            for name, (lo, hi) in window_list:
                if lo <= frame_id < hi:
                    win_tag = name
                    break

            matched, scores = match_points_with_scores(
                gray, predicted, templates, roi_half, tmpl_r, frame_w, frame_h
            )
            M, mask = cv2.estimateAffinePartial2D(
                ref_pts, matched, method=cv2.RANSAC, ransacReprojThreshold=ransac_thr
            )
            n_inl = int(mask.sum()) if mask is not None else 0
            status_ok = M is not None and n_inl >= min_inliers

            if win_tag is not None:
                per_clip[clip_id]["frame_status"].append((win_tag, frame_id, status_ok, n_inl))
                if M is not None:
                    proj = cv2.transform(ref_pts.reshape(-1, 1, 2), M).reshape(-1, 2)
                    for i, pid in enumerate(ids):
                        resid = float(np.linalg.norm(matched[i] - proj[i]))
                        per_clip[clip_id]["resid"][pid].append(resid)
                        per_clip[clip_id]["inlier"][pid].append(bool(mask[i, 0]))
                        per_clip[clip_id]["vecs"][pid].append(matched[i] - predicted[i])
                        if scores[i] is not None:
                            per_clip[clip_id]["ncc"][pid].append(scores[i])

            if status_ok:
                prev_M = M
            if prev_M is not None:
                predicted = cv2.transform(ref_pts.reshape(-1, 1, 2), prev_M).reshape(-1, 2)
            frame_id += 1
        cap.release()

    report = {"ids": ids, "kept_ids": kept_ids, "manual_ids": manual_ids, "points": []}
    for idx, pid in enumerate(ids):
        cell = cells[idx]
        radial_dir = ref_pts[idx] - center
        radial_dir_norm = radial_dir / (np.linalg.norm(radial_dir) + 1e-9)
        row = {"id": pid, "grid_cell": list(cell), "per_clip": {}}
        angles = {}
        for clip_id in test_clips:
            d = per_clip[clip_id]
            ncc_arr = np.array(d["ncc"][pid]) if d["ncc"][pid] else np.array([])
            resid_arr = np.array(d["resid"][pid]) if d["resid"][pid] else np.array([])
            inlier_arr = np.array(d["inlier"][pid]) if d["inlier"][pid] else np.array([])
            vecs = np.array(d["vecs"][pid]) if d["vecs"][pid] else np.zeros((0, 2))
            mean_vec = vecs.mean(axis=0) if len(vecs) else np.array([0.0, 0.0])
            vec_norm = mean_vec / (np.linalg.norm(mean_vec) + 1e-9)
            angle_deg = float(np.degrees(np.arccos(np.clip(np.dot(radial_dir_norm, vec_norm), -1, 1))))
            angles[clip_id] = angle_deg
            row["per_clip"][clip_id] = {
                "ncc_mean": float(ncc_arr.mean()) if ncc_arr.size else None,
                "ncc_min": float(ncc_arr.min()) if ncc_arr.size else None,
                "resid_mean": float(resid_arr.mean()) if resid_arr.size else None,
                "resid_p95": float(np.percentile(resid_arr, 95)) if resid_arr.size else None,
                "inlier_rate": float(inlier_arr.mean()) if inlier_arr.size else None,
                "n_frames": int(resid_arr.size),
                "angle_vs_radial_deg": angle_deg,
            }
        row["direction_flag"] = all(angles.get(c, 999) < angle_max for c in test_clips)
        report["points"].append(row)

    frame_level = {}
    for clip_id in test_clips:
        entries = per_clip[clip_id]["frame_status"]
        n_total = len(entries)
        n_fail = sum(1 for _, _, ok, _ in entries if not ok)
        runs, cur, last_win = [], 0, None
        for win_tag, fid, ok, n_inl in entries:
            if win_tag != last_win:
                if cur > 0:
                    runs.append(cur)
                cur, last_win = 0, win_tag
            if not ok:
                cur += 1
            else:
                if cur > 0:
                    runs.append(cur)
                cur = 0
        if cur > 0:
            runs.append(cur)
        frame_level[clip_id] = {
            "n_total": n_total, "n_fail": n_fail,
            "fail_rate_pct": round(100.0 * n_fail / n_total, 2) if n_total else None,
            "fail_runs": {"n": len(runs), "lengths": runs, "max": max(runs) if runs else 0,
                          "mean": float(np.mean(runs)) if runs else 0.0},
        }
    report["frame_level"] = frame_level

    out_path = REG_OUT / "manual_points_validation_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"{'id':>5s} {'cell':>7s} | " + " | ".join(f"{c}: ncc/resid/inlier%/ang" for c in test_clips) + " | dir")
    for row in report["points"]:
        cell_s = f"({row['grid_cell'][0]},{row['grid_cell'][1]})"
        parts = []
        for clip_id in test_clips:
            pc = row["per_clip"][clip_id]
            ncc_s = f"{pc['ncc_mean']:.3f}/{pc['ncc_min']:.3f}" if pc["ncc_mean"] is not None else "N/A"
            resid_s = f"{pc['resid_mean']:.2f}/{pc['resid_p95']:.2f}" if pc["resid_mean"] is not None else "N/A"
            inlier_s = f"{100 * pc['inlier_rate']:.0f}%" if pc["inlier_rate"] is not None else "N/A"
            parts.append(f"ncc={ncc_s} resid={resid_s} inlier={inlier_s} ang={pc['angle_vs_radial_deg']:.0f}")
        flag_s = "HEIGHT?" if row["direction_flag"] else "-"
        print(f"{row['id']:5d} {cell_s:>7s} | " + " | ".join(parts) + f" | {flag_s}")

    print()
    for clip_id in test_clips:
        fl = frame_level[clip_id]
        print(f"[프레임 실패율] {clip_id}: {fl['n_fail']}/{fl['n_total']} ({fl['fail_rate_pct']}%) | "
              f"연속실패구간 {fl['fail_runs']['n']}개, 최대 {fl['fail_runs']['max']}프레임, "
              f"평균 {fl['fail_runs']['mean']:.1f}프레임")

    print(f"\n[완료] {out_path}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "propose-points":
        propose_points()
    elif len(sys.argv) >= 3 and sys.argv[1] == "track-points":
        track_points(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "propose-points-round2":
        propose_points_round2()
    elif len(sys.argv) >= 2 and sys.argv[1] == "validate-round2":
        validate_round2_candidates()
    elif len(sys.argv) >= 2 and sys.argv[1] == "validate-manual":
        validate_manual_points()
    else:
        print("사용법: python src/39_register_frames.py propose-points")
        print("       python src/39_register_frames.py track-points <clip_id>")
        print("       python src/39_register_frames.py propose-points-round2")
        print("       python src/39_register_frames.py validate-round2")
        print("       python src/39_register_frames.py validate-manual")
        raise SystemExit(1)
