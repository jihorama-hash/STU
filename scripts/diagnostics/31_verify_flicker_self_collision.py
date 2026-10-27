"""ByteTrack 클래스 플리커링으로 인한 무단횡단자-차량 근접 오탐(자기충돌) 검증.

Phase B Day3 보고서 §6: 27_make_interim_outputs.py가 만드는 jaywalkers.csv의
vehicle_nearby=True 판정 중 일부가, 같은 물리적 보행자가 몇 프레임 동안 트래커에 의해
person↔car로 클래스가 바뀌면서 별도 track_id로 분리되어 생긴 "자기 자신과의 충돌"일
가능성이 있다(DJI_0482 track 80(person 우세)/92(car로 잠깐 분리) 사례로 최초 발견).

jaywalkers.csv 산출 시 사용한 것과 동일한 근접도 판정(차도 내 무단횡단 구간 ±2초,
150px 이내)을 이번엔 "어느 차량 track_id가 가장 가까웠는지"까지 남겨서 재계산하고,
그 차량 트랙의 클래스 이력에 person이 섞여 있으면서(=플리커링 흔적) 보행자 트랙과
시간상 겹치거나 0.5초 이내로 인접하는 경우를 "자기충돌 의심"으로 표시한다.

    python src/31_verify_flicker_self_collision.py

출력:
    runs/before_l_mt09/combined_interim/jaywalk_vehicle_flicker_audit.csv
        vehicle_nearby=True 44건 전체에 대한 진단 내역
    runs/before_l_mt09/combined_interim/jaywalk_crosswalk_risk_summary_adjusted.csv
        자기충돌 의심 건을 제외하고 다시 집계한 횡단보도별 위험도
        (원본 jaywalk_crosswalk_risk_summary.csv는 비교용으로 그대로 둠)
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

from _paths import BASE

SRC_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("interim_outputs_27", SRC_DIR / "27_make_interim_outputs.py")
io27 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io27)

CALIB = BASE / "calib"
PET_DIR = BASE / "runs" / "before_l_mt09"
OUT = PET_DIR / "combined_interim"

TIME_ADJACENCY_SEC = 0.5  # 보행자·차량 트랙이 이 시간 이내로 겹치거나 인접하면 "동일 물체 분리" 의심


def build_jay_area(zones: list, road: np.ndarray) -> np.ndarray:
    """27_make_interim_outputs.py와 동일한 로직으로 무단횡단 판정 영역(차도 안쪽 & 횡단보도 버퍼 밖)을 재구성."""
    cw_mask = np.zeros_like(road)
    for z in zones:
        if z.get("side"):
            cv2.fillPoly(cw_mask, [np.array(z["polygon"], dtype=np.int32)], 255)
    cw_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (io27.CROSSWALK_BUFFER_PX * 2 + 1, io27.CROSSWALK_BUFFER_PX * 2 + 1)
    )
    cw_mask = cv2.dilate(cw_mask, cw_kernel)
    erode_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (io27.ROADWAY_ERODE_FOR_JAY_PX * 2 + 1, io27.ROADWAY_ERODE_FOR_JAY_PX * 2 + 1)
    )
    road_inner = cv2.erode(road, erode_kernel)
    return (road_inner > 0) & (cw_mask == 0)


def build_vehicle_track_index(tracks: dict) -> list[tuple[str, list]]:
    """다수결 클래스가 차량인 트랙만 추린다 (person 여부는 시간창 내에서 별도로 재확인)."""
    index = []
    for vtid, vrows in tracks.items():
        cls_names = [r[3] for r in vrows]
        majority = max(set(cls_names), key=cls_names.count)
        if majority in io27.VEHICLE_CLASSES:
            index.append((vtid, vrows))
    return index


def nearest_vehicle_track(pts_in_native, vehicle_index, exclude_tid, t0, t1):
    """무단횡단 구간(원본 픽셀)에 시간창 내에서 가장 가까웠던 차량 track_id와 그 진단 정보.

    has_person은 트랙 전체 이력이 아니라, 실제로 근접도 계산에 쓰인 시간창(sub) 내
    프레임만 기준으로 판단한다 — 트랙 전체 중 이 근접 시점과 무관한 다른 구간에 있었던
    person 오검출까지 "자기충돌"로 잘못 묶이는 것을 막기 위함.
    """
    jp = np.array([[x, y] for _, x, y in pts_in_native], dtype=np.float64)
    best = None
    for vtid, vrows in vehicle_index:
        if vtid == exclude_tid:
            continue
        sub = [(t, x, y, cls) for t, x, y, cls in vrows if t0 <= t <= t1]
        if not sub:
            continue
        vp = np.array([[x, y] for _, x, y, _ in sub], dtype=np.float64)
        d = float(np.sqrt(((jp[:, None, :] - vp[None, :, :]) ** 2).sum(axis=2)).min())
        if best is None or d < best[0]:
            has_person_in_window = any(cls == "person" for _, _, _, cls in sub)
            best = (d, vtid, has_person_in_window, vrows[0][0], vrows[-1][0])
    return best


def time_gap(a_t0: float, a_t1: float, b_t0: float, b_t1: float) -> float:
    """두 시간구간의 간격(초). 겹치면 0."""
    if a_t1 < b_t0:
        return b_t0 - a_t1
    if b_t1 < a_t0:
        return a_t0 - b_t1
    return 0.0


def main() -> None:
    zones = json.load((CALIB / "rois_split.json").open(encoding="utf-8"))["zones"]
    h_json = json.load((CALIB / "alignment_homographies.json").open(encoding="utf-8"))
    hmap = {vid: np.array(v["h"]) for vid, v in h_json["videos"].items()}
    road = cv2.imread(str(CALIB / "roadway_mask.png"), cv2.IMREAD_GRAYSCALE)
    jay_area = build_jay_area(zones, road)
    H_img, W_img = road.shape

    tracks_by_video = {vid: io27.read_tracks(tpath) for vid, _, tpath in io27.VIDEOS}
    vehicle_index_by_video = {vid: build_vehicle_track_index(tracks) for vid, tracks in tracks_by_video.items()}

    jay_rows = list(csv.DictReader((OUT / "jaywalkers.csv").open(encoding="utf-8-sig", newline="")))
    flagged = [r for r in jay_rows if r["vehicle_nearby"] == "True"]

    audit_rows = []
    suspect_keys: set[tuple[str, str]] = set()
    for r in flagged:
        vid, tid = r["source_video"], r["track_id"]
        h = hmap[vid]
        rows = tracks_by_video[vid][tid]
        pts_in_native = []
        for t, x, y, _ in rows:
            rx, ry = io27.apply_h(h, x, y)
            if 0 <= rx < W_img and 0 <= ry < H_img and jay_area[int(ry), int(rx)]:
                pts_in_native.append((t, x, y))
        if not pts_in_native:
            continue
        t0 = pts_in_native[0][0] - io27.VEHICLE_TIME_WINDOW_SEC
        t1 = pts_in_native[-1][0] + io27.VEHICLE_TIME_WINDOW_SEC
        best = nearest_vehicle_track(pts_in_native, vehicle_index_by_video[vid], tid, t0, t1)
        if best is None:
            continue
        dist, vtid, has_person, v_t0, v_t1 = best
        p_t0, p_t1 = rows[0][0], rows[-1][0]
        gap = time_gap(p_t0, p_t1, v_t0, v_t1)
        adjacent = gap <= TIME_ADJACENCY_SEC
        suspect = has_person and adjacent
        if suspect:
            suspect_keys.add((vid, tid))
        audit_rows.append(
            {
                "source_video": vid,
                "jaywalker_track_id": tid,
                "reported_min_vehicle_distance_px": r["min_vehicle_distance_px"],
                "nearest_crosswalk": r["nearest_crosswalk"],
                "near_crosswalk": r["near_crosswalk"],
                "nearest_vehicle_track_id": vtid,
                "recomputed_min_distance_px": round(dist, 1),
                "vehicle_track_has_person_frames": has_person,
                "vehicle_track_time_gap_sec": round(gap, 2),
                "self_collision_suspect": suspect,
            }
        )

    audit_path = OUT / "jaywalk_vehicle_flicker_audit.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
        w.writeheader()
        w.writerows(audit_rows)

    # 자기충돌 의심 건 제외한 조정판 횡단보도별 위험도
    before = {}
    after = {}
    for r in jay_rows:
        if r["near_crosswalk"] != "True":
            continue
        name = r["nearest_crosswalk"]
        b = before.setdefault(name, {"near_crosswalk_jaywalkers": 0, "vehicle_nearby": 0})
        a = after.setdefault(name, {"near_crosswalk_jaywalkers": 0, "vehicle_nearby": 0})
        b["near_crosswalk_jaywalkers"] += 1
        a["near_crosswalk_jaywalkers"] += 1
        if r["vehicle_nearby"] == "True":
            b["vehicle_nearby"] += 1
            if (r["source_video"], r["track_id"]) not in suspect_keys:
                a["vehicle_nearby"] += 1

    adj_path = OUT / "jaywalk_crosswalk_risk_summary_adjusted.csv"
    with adj_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["crosswalk", "near_crosswalk_jaywalkers", "vehicle_nearby", "vehicle_nearby_pct"]
        )
        w.writeheader()
        for name in sorted(after, key=lambda k: -after[k]["vehicle_nearby"]):
            s = after[name]
            pct = s["vehicle_nearby"] / s["near_crosswalk_jaywalkers"] * 100 if s["near_crosswalk_jaywalkers"] else 0.0
            w.writerow({"crosswalk": name, **s, "vehicle_nearby_pct": round(pct, 1)})

    print(f"vehicle_nearby flagged: {len(flagged)}, self-collision suspect: {len(suspect_keys)}")
    print("--- 횡단보도별 차량 근접 위험 비율: 조정 전 -> 후 (자기충돌 의심 제외) ---")
    for name in sorted(before, key=lambda k: -before[k]["vehicle_nearby"]):
        b, a = before[name], after[name]
        b_pct = b["vehicle_nearby"] / b["near_crosswalk_jaywalkers"] * 100 if b["near_crosswalk_jaywalkers"] else 0.0
        a_pct = a["vehicle_nearby"] / a["near_crosswalk_jaywalkers"] * 100 if a["near_crosswalk_jaywalkers"] else 0.0
        print(
            f"{name}: {b['vehicle_nearby']}/{b['near_crosswalk_jaywalkers']} ({b_pct:.1f}%)"
            f" -> {a['vehicle_nearby']}/{a['near_crosswalk_jaywalkers']} ({a_pct:.1f}%)"
        )
    print("자기충돌 의심 건 상세:")
    for row in audit_rows:
        if row["self_collision_suspect"]:
            print(
                f"  {row['source_video']} ped#{row['jaywalker_track_id']}"
                f" <-> veh#{row['nearest_vehicle_track_id']}"
                f" (dist={row['recomputed_min_distance_px']}px, gap={row['vehicle_track_time_gap_sec']}s)"
            )
    print(f"saved -> {audit_path}")
    print(f"saved -> {adj_path}")


if __name__ == "__main__":
    main()
