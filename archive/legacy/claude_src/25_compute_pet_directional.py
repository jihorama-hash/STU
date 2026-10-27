from __future__ import annotations

from _paths import BASE

"""분할 ROI + 이동방향 교차각 필터를 적용한 PET 상충 산정 (중간분석용).

파일럿 06번 로직과의 차이:
- ROI: calib/rois_split.json (횡단보도 진입측/진출측 분할)
- 차량-차량 쌍은 두 궤적의 이동방향 교차각이 임계값 미만이면 추종(car-following)으로
  판정해 상충에서 제외 (별도 CSV에 보존)
- 보행자-차량 쌍은 각도로 제외하지 않음
- ROI별 진입 집계(roi_entries.csv)를 함께 산출
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


CLASS_KIND = {
    "person": "pedestrian",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}

EVENT_FIELDS = [
    "event_id", "roi_id", "roi_name", "roi_parent", "roi_side",
    "first_track_id", "first_class_name", "first_class_kind",
    "first_entry_sec", "first_exit_sec", "first_dir_deg",
    "second_track_id", "second_class_name", "second_class_kind",
    "second_entry_sec", "second_exit_sec", "second_dir_deg",
    "pet_sec", "overlap", "cross_angle_deg", "event_scope", "conflict_type",
    "event_x", "event_y",
]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", type=Path, required=True)
    ap.add_argument("--zones", type=Path, default=BASE / "calib" / "rois_split.json")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--max-pet-sec", type=float, default=3.0)
    ap.add_argument(
        "--max-pet-sec-pv",
        type=float,
        default=1.5,
        help="보행자-차량 PET 상한. DJI_0482+DJI_0486 지상검증 24건 그리드서치 결과 "
        "4.0s는 회수율 손실 없이(실제상충 4/4 유지) 오탐만 늘려 1.5s로 조정 "
        "(정탐률 16.7%%->33.3%%, PHASE_B_WORK_PLAN.md 12장 '짝짓기 조건 재조정' 대응).",
    )
    ap.add_argument("--final-pet-sec", type=float, default=1.5)
    ap.add_argument(
        "--min-cross-angle-deg",
        type=float,
        default=40.0,
        help="같은 그리드서치 결과 20도->40도로 상향해도 실제상충 회수율 손실 없음.",
    )
    ap.add_argument("--min-move-px", type=float, default=15.0)
    ap.add_argument("--min-track-points", type=int, default=2)
    ap.add_argument("--min-track-duration-sec", type=float, default=0.3)
    ap.add_argument("--dedupe-window-sec", type=float, default=1.0)
    ap.add_argument("--dedupe-distance-px", type=float, default=200.0)
    ap.add_argument(
        "--video-id",
        default=None,
        help="calib/alignment_homographies.json key for --tracks' source video. "
        "Defaults to --tracks' parent directory name (e.g. runs/.../DJI_0482/... -> DJI_0482).",
    )
    ap.add_argument("--roadway-mask", type=Path, default=BASE / "calib" / "roadway_mask.png")
    ap.add_argument("--homographies", type=Path, default=BASE / "calib" / "alignment_homographies.json")
    ap.add_argument(
        "--no-roadway-filter",
        action="store_true",
        help="Skip the 'conflict location must be on the roadway' constraint.",
    )
    return ap.parse_args()


def parse_float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def point_in_polygon(x, y, polygon):
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def read_tracks(path, min_points, min_duration):
    tracks = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tid = (row.get("track_id") or "").strip()
            cls = (row.get("class_name") or "").strip()
            if not tid or not cls:
                continue
            tracks[tid].append(
                {
                    "t": parse_float(row.get("time_sec")),
                    "cls": cls,
                    "kind": CLASS_KIND.get(cls, "other"),
                    "x": parse_float(row.get("anchor_x") or row.get("foot_x") or row.get("cx")),
                    "y": parse_float(row.get("anchor_y") or row.get("foot_y") or row.get("cy")),
                }
            )
    out = {}
    for tid, rows in tracks.items():
        rows.sort(key=lambda r: r["t"])
        if len(rows) < min_points:
            continue
        if rows[-1]["t"] - rows[0]["t"] < min_duration:
            continue
        out[tid] = rows
    return out


def dominant(rows, key):
    vals = [r[key] for r in rows]
    return max(set(vals), key=vals.count)


def build_intervals(tracks, zones, min_move_px):
    intervals = []
    for zone in zones:
        poly = zone["polygon"]
        for tid, rows in tracks.items():
            inside = [r for r in rows if point_in_polygon(r["x"], r["y"], poly)]
            if not inside:
                continue
            dx = inside[-1]["x"] - inside[0]["x"]
            dy = inside[-1]["y"] - inside[0]["y"]
            if math.hypot(dx, dy) >= min_move_px:
                dir_deg = math.degrees(math.atan2(dy, dx)) % 360.0
            else:
                dir_deg = None  # 사실상 정지
            intervals.append(
                {
                    "roi_id": zone["id"],
                    "roi_name": zone.get("name", zone["id"]),
                    "roi_parent": zone.get("parent") or zone["id"],
                    "roi_side": zone.get("side") or "",
                    "track_id": tid,
                    "class_name": dominant(inside, "cls"),
                    "class_kind": dominant(inside, "kind"),
                    "entry_sec": inside[0]["t"],
                    "exit_sec": inside[-1]["t"],
                    "dir_deg": dir_deg,
                    "event_x": sum(r["x"] for r in inside) / len(inside),
                    "event_y": sum(r["y"] for r in inside) / len(inside),
                }
            )
    intervals.sort(key=lambda i: (i["roi_id"], i["entry_sec"]))
    return intervals


def apply_h(h, x, y):
    pt = cv2.perspectiveTransform(np.float32([[[x, y]]]), h)[0][0]
    return float(pt[0]), float(pt[1])


def load_roadway_checker(video_id, mask_path, homographies_path):
    """calib/roadway_mask.png(DJI_0481 기준틀) + alignment_homographies.json 재사용.

    src/27_make_interim_outputs.py의 무단횡단 판정과 동일한 호모그래피 투영 +
    불리언 배열 조회 패턴 (jay_area[int(ry), int(rx)]).
    """
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(f"Could not read roadway mask: {mask_path}")
    data = json.loads(homographies_path.read_text(encoding="utf-8"))
    if video_id not in data["videos"]:
        raise KeyError(f"{video_id!r} not in {homographies_path} (have: {list(data['videos'])})")
    h = np.array(data["videos"][video_id]["h"], dtype=np.float64)
    height, width = mask.shape[:2]

    def on_roadway(x, y):
        rx, ry = apply_h(h, x, y)
        return 0 <= rx < width and 0 <= ry < height and mask[int(ry), int(rx)] > 0

    return on_roadway


def cross_angle(a_deg, b_deg):
    """두 이동방향 벡터 사이 각(0~180°). 0°=같은 방향(추종), 90°=직교, 180°=대향."""
    if a_deg is None or b_deg is None:
        return None
    d = abs(a_deg - b_deg) % 360.0
    return 360.0 - d if d > 180.0 else d


def conflict_type(k1, k2):
    kinds = {k1, k2}
    if kinds == {"pedestrian", "vehicle"}:
        return "pedestrian_vehicle"
    if k1 == "vehicle" and k2 == "vehicle":
        return "vehicle_vehicle"
    return None


def compute_events(intervals, args, on_roadway=None):
    by_zone = defaultdict(list)
    for iv in intervals:
        by_zone[iv["roi_id"]].append(iv)
    events, excluded = [], []
    eid = 1
    for roi_id, ivs in sorted(by_zone.items()):
        ivs.sort(key=lambda i: (i["entry_sec"], i["exit_sec"]))
        for ci, cur in enumerate(ivs):
            for prev in ivs[:ci]:
                if prev["track_id"] == cur["track_id"]:
                    continue
                ctype = conflict_type(prev["class_kind"], cur["class_kind"])
                if ctype is None:
                    continue
                pet = cur["entry_sec"] - prev["exit_sec"]
                pet_limit = args.max_pet_sec_pv if ctype == "pedestrian_vehicle" else args.max_pet_sec
                overlap = pet < 0
                if overlap and ctype == "pedestrian_vehicle":
                    # 보행자-차량 동시 체류: 보행자가 있는 절반을 차량이 통과한 침범.
                    # PET 정의상 음수이므로 0으로 두고 overlap 플래그로 구분한다.
                    pet = 0.0
                elif pet < 0 or pet > pet_limit:
                    # 차량-차량 동시 체류는 정체 대기열에서 흔한 정상 상황이라 제외.
                    continue
                ang = cross_angle(prev["dir_deg"], cur["dir_deg"])
                row = {
                    "event_id": eid,
                    "roi_id": roi_id,
                    "roi_name": cur["roi_name"],
                    "roi_parent": cur["roi_parent"],
                    "roi_side": cur["roi_side"],
                    "first_track_id": prev["track_id"],
                    "first_class_name": prev["class_name"],
                    "first_class_kind": prev["class_kind"],
                    "first_entry_sec": round(prev["entry_sec"], 3),
                    "first_exit_sec": round(prev["exit_sec"], 3),
                    "first_dir_deg": round(prev["dir_deg"], 1) if prev["dir_deg"] is not None else "",
                    "second_track_id": cur["track_id"],
                    "second_class_name": cur["class_name"],
                    "second_class_kind": cur["class_kind"],
                    "second_entry_sec": round(cur["entry_sec"], 3),
                    "second_exit_sec": round(cur["exit_sec"], 3),
                    "second_dir_deg": round(cur["dir_deg"], 1) if cur["dir_deg"] is not None else "",
                    "pet_sec": round(pet, 3),
                    "overlap": "true" if overlap else "false",
                    "cross_angle_deg": round(ang, 1) if ang is not None else "",
                    "event_scope": "final" if pet <= args.final_pet_sec else "reference",
                    "conflict_type": ctype,
                    "event_x": round((prev["event_x"] + cur["event_x"]) / 2, 1),
                    "event_y": round((prev["event_y"] + cur["event_y"]) / 2, 1),
                }
                # 제외 규칙 (지상검증 52건 대조로 도출):
                # 1) 방향 미상(정지·유령 궤적) 당사자는 상충 판정 불가 → 제외
                if ang is None:
                    row["excluded_reason"] = "stationary_or_unknown_direction"
                    excluded.append(row)
                    continue
                # 2) 차량-차량 같은 방향(추종) → 제외 (주의: 추돌형 상충도 함께 배제됨 — 보고서 한계 명시)
                if ctype == "vehicle_vehicle" and ang < args.min_cross_angle_deg:
                    row["excluded_reason"] = "following_same_direction"
                    excluded.append(row)
                    continue
                # 3) 보행자-차량인데 차량과 평행 이동 → 오분류 이륜차/유령 의심 → 제외
                if ctype == "pedestrian_vehicle" and ang < args.min_cross_angle_deg:
                    row["excluded_reason"] = "parallel_movement_suspect"
                    excluded.append(row)
                    continue
                # 4) 차도 밖(인도·중앙분리대 등) 위치의 상충 후보 제외 ("경로 교차는 차도내로 한정")
                if on_roadway is not None and not on_roadway(row["event_x"], row["event_y"]):
                    row["excluded_reason"] = "off_roadway"
                    excluded.append(row)
                    continue
                events.append(row)
                eid += 1
    return events, excluded


def dedupe(events, window_sec, dist_px):
    def t(e):
        return float(e["second_entry_sec"])

    clusters = []
    for e in sorted(events, key=t):
        placed = None
        for cl in clusters:
            if t(e) - max(t(x) for x in cl) > window_sec:
                continue
            if e["conflict_type"] != cl[0]["conflict_type"]:
                continue
            if any(
                math.hypot(float(e["event_x"]) - float(x["event_x"]),
                           float(e["event_y"]) - float(x["event_y"])) <= dist_px
                for x in cl
            ):
                placed = cl
                break
        if placed is None:
            clusters.append([e])
        else:
            placed.append(e)
    result = [min(cl, key=lambda x: float(x["pet_sec"])) for cl in clusters]
    result.sort(key=lambda e: (e["roi_id"], t(e)))
    for i, e in enumerate(result, 1):
        e["event_id"] = i
    return result


def roi_entries(tracks, zones):
    rows = []
    for zone in zones:
        ped = veh = 0
        for rows_t in tracks.values():
            inside = [r for r in rows_t if point_in_polygon(r["x"], r["y"], zone["polygon"])]
            if not inside:
                continue
            kind = dominant(inside, "kind")
            if kind == "pedestrian":
                ped += 1
            elif kind == "vehicle":
                veh += 1
        rows.append(
            {
                "roi_id": zone["id"],
                "roi_parent": zone.get("parent") or zone["id"],
                "roi_side": zone.get("side") or "",
                "pedestrian_entries": ped,
                "vehicle_entries": veh,
            }
        )
    return rows


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    args = parse_args()
    zones = json.load(args.zones.open(encoding="utf-8"))["zones"]
    tracks = read_tracks(args.tracks, args.min_track_points, args.min_track_duration_sec)
    intervals = build_intervals(tracks, zones, args.min_move_px)

    on_roadway = None
    video_id = args.video_id
    if not args.no_roadway_filter:
        video_id = video_id or args.tracks.parent.name
        on_roadway = load_roadway_checker(video_id, args.roadway_mask, args.homographies)

    raw_events, excluded = compute_events(intervals, args, on_roadway)
    events = dedupe(raw_events, args.dedupe_window_sec, args.dedupe_distance_px)
    entries = roi_entries(tracks, zones)

    out = args.output_dir
    write_csv(out / "pet_events_directional.csv", events, EVENT_FIELDS)
    write_csv(out / "pet_excluded_following.csv", excluded, EVENT_FIELDS + ["excluded_reason"])
    write_csv(
        out / "roi_entries.csv",
        entries,
        ["roi_id", "roi_parent", "roi_side", "pedestrian_entries", "vehicle_entries"],
    )
    duration = max((rows[-1]["t"] for rows in tracks.values()), default=0.0)
    excluded_off_roadway = sum(1 for e in excluded if e.get("excluded_reason") == "off_roadway")
    (out / "run_metadata.json").write_text(
        json.dumps(
            {
                "tracks": str(args.tracks),
                "zones": str(args.zones),
                "video_duration_sec_approx": round(duration, 1),
                "params": {
                    "max_pet_sec": args.max_pet_sec,
                    "final_pet_sec": args.final_pet_sec,
                    "min_cross_angle_deg": args.min_cross_angle_deg,
                    "min_move_px": args.min_move_px,
                    "dedupe_window_sec": args.dedupe_window_sec,
                    "dedupe_distance_px": args.dedupe_distance_px,
                },
                "roadway_filter": {
                    "enabled": not args.no_roadway_filter,
                    "video_id": video_id,
                    "roadway_mask": str(args.roadway_mask),
                },
                "tracks_used": len(tracks),
                "events_before_dedupe": len(raw_events),
                "events": len(events),
                "excluded_following": len(excluded),
                "excluded_off_roadway": excluded_off_roadway,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    pv = sum(1 for e in events if e["conflict_type"] == "pedestrian_vehicle")
    print(
        f"tracks={len(tracks)} events={len(events)} (pv={pv}, vv={len(events)-pv}) "
        f"excluded_following={len(excluded)} (off_roadway={excluded_off_roadway}) -> {out}"
    )


if __name__ == "__main__":
    main()
