from __future__ import annotations

from _paths import BASE

"""중간분석 통합 산출물 생성.

1. 영상별 첫 프레임 → 0481 기준틀 정합 homography 산출 (calib/alignment_homographies.json)
2. 차도 마스크: 8개 영상 차량 궤적 점(기준틀 보정)을 팽창시켜 생성 (calib/roadway_mask.png)
3. 무단횡단 보행자: 차도 위 & 횡단보도(버퍼) 밖에서 1초 이상 체류한 보행자 궤적
4. ROI(분할)별 통과 차량·보행자 집계 + 상충 발생율
5. 정합 보정 점밀도 히트맵 (보행자-차량 / 차량-차량 분리)
"""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


CALIB = BASE / "calib"
INTERIM = BASE / "runs" / "interim"
OUT = INTERIM / "combined"

REFERENCE_ID = "DJI_0481"

VIDEOS = [
    ("DJI_0481", BASE / "record/DJI_0481.MP4", BASE / "runs/DJI_0481_sahi_step10/tracks_pixel.csv"),
    ("DJI_0482", BASE / "record/DJI_0482.MP4", BASE / "runs/DJI_0482_sahi_step3_final/tracks_pixel.csv"),
    ("DJI_0483_Cut", BASE / "record/DJI_0483_Cut.mp4", BASE / "runs/DJI_0483_Cut_sahi_step10/m0615_pet_deduped/tracks_pixel_m0615.csv"),
    ("DJI_0484", BASE / "record/DJI_0484.MP4", BASE / "runs/DJI_0484_sahi_step10/m0617_pet_deduped/tracks_pixel_m0615.csv"),
    ("DJI_0485", BASE / "record/DJI_0485.MP4", BASE / "runs/DJI_0485_sahi_step10/m0617_pet_deduped/tracks_pixel_m0615.csv"),
    ("DJI_0486", BASE / "record/DJI_0486.MP4", BASE / "runs/DJI_0486_sahi_step10/m0617_pet_deduped/tracks_pixel_m0615.csv"),
    ("DJI_0487", BASE / "record/DJI_0487.MP4", BASE / "runs/DJI_0487_sahi_step10/m0618_pet_deduped/tracks_pixel_m0615.csv"),
    ("DJI_0488", BASE / "record/DJI_0488.MP4", BASE / "runs/DJI_0488_sahi_step10/m0618_pet_deduped/tracks_pixel_m0615.csv"),
]

VEHICLE_CLASSES = {"car", "bus", "truck", "motorcycle", "bicycle"}
# 차도 마스크 정의용: 이륜차·자전거는 남측 산책로를 통행하므로 제외 (산책로가 차도로 오인됨)
ROADWAY_DEFINING_CLASSES = {"car", "bus", "truck"}
ROADWAY_MIN_TRACK_MOVE_PX = 150.0  # 정지·유령 차량 궤적 배제
ROADWAY_DILATE_PX = 50
ROADWAY_ERODE_FOR_JAY_PX = 35  # 무단횡단 판정은 차도 '안쪽'에서만 (연석 인접 보행 배제)
CROSSWALK_BUFFER_PX = 40
JAYWALK_MIN_SEC = 1.0
JAYWALK_MIN_MOVE_PX = 120.0  # 차도 내 실이동 요구 — 수목 그늘 유령(제자리 깜빡임) 배제
HEAT_RADIUS = 80


def parse_float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def first_frame(path):
    cap = cv2.VideoCapture(str(path))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"frame read failed: {path}")
    return frame


def estimate_h_to_ref(video_gray, ref_gray):
    orb = cv2.ORB_create(nfeatures=6000)
    kp1, des1 = orb.detectAndCompute(video_gray, None)
    kp2, des2 = orb.detectAndCompute(ref_gray, None)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = sorted(matcher.match(des1, des2), key=lambda m: m.distance)
    matches = matches[: max(200, len(matches) // 3)]
    src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return h, int(mask.sum())


def apply_h(h, x, y):
    pt = cv2.perspectiveTransform(np.float32([[[x, y]]]), h)[0][0]
    return float(pt[0]), float(pt[1])


def read_tracks(path):
    tracks = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tid = (row.get("track_id") or "").strip()
            cls = (row.get("class_name") or "").strip()
            if not tid or not cls:
                continue
            tracks[tid].append(
                (
                    parse_float(row.get("time_sec")),
                    parse_float(row.get("anchor_x") or row.get("foot_x") or row.get("cx")),
                    parse_float(row.get("anchor_y") or row.get("foot_y") or row.get("cy")),
                    cls,
                )
            )
    for rows in tracks.values():
        rows.sort()
    return tracks


def add_heat(heat, x, y, value, radius):
    h_, w_ = heat.shape
    cx, cy = int(round(x)), int(round(y))
    x1, y1 = max(0, cx - radius), max(0, cy - radius)
    x2, y2 = min(w_, cx + radius + 1), min(h_, cy + radius + 1)
    if x1 >= x2 or y1 >= y2:
        return
    yy, xx = np.ogrid[y1:y2, x1:x2]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    sigma2 = (radius / 2.0) ** 2
    heat[y1:y2, x1:x2] += np.where(d2 <= radius**2, np.exp(-d2 / (2 * sigma2)) * value, 0.0)


def draw_heatmap(background, heat, out_path, zones):
    overlay = background.copy()
    if heat.max() > 0:
        norm = np.clip(heat / heat.max() * 255, 0, 255).astype(np.uint8)
        color = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        mask = norm >= 8
        blend = cv2.addWeighted(background, 0.45, color, 0.55, 0)
        overlay[mask] = blend[mask]
    for z in zones:
        pts = np.array(z["polygon"], dtype=np.int32)
        col = {"entry": (255, 160, 0), "exit": (0, 90, 255)}.get(z.get("side"), (200, 200, 200))
        cv2.polylines(overlay, [pts], True, col, 3, cv2.LINE_AA)
    cv2.imwrite(str(out_path), overlay, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    zones = json.load((CALIB / "rois_split.json").open(encoding="utf-8"))["zones"]

    # ── 1. 정합 homography ──
    ref_frame = first_frame(dict((v[0], v[1]) for v in VIDEOS)[REFERENCE_ID])
    ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
    hmap = {}
    h_json = {}
    for vid, vpath, _ in VIDEOS:
        if vid == REFERENCE_ID:
            hmap[vid] = np.eye(3)
            h_json[vid] = {"h": np.eye(3).tolist(), "inliers": None}
            continue
        gray = cv2.cvtColor(first_frame(vpath), cv2.COLOR_BGR2GRAY)
        h, inl = estimate_h_to_ref(gray, ref_gray)
        hmap[vid] = h
        h_json[vid] = {"h": h.tolist(), "inliers": inl}
        print(f"H {vid} -> ref: inliers={inl}")
    (CALIB / "alignment_homographies.json").write_text(
        json.dumps({"reference": REFERENCE_ID, "videos": h_json}, indent=2), encoding="utf-8"
    )

    # ── 2. 차도 마스크 (기준틀) ──
    H_img, W_img = ref_frame.shape[:2]
    road = np.zeros((H_img, W_img), dtype=np.uint8)
    all_tracks = {}
    dt_by_video = {}
    duration_by_video = {}
    for vid, _, tpath in VIDEOS:
        tracks = read_tracks(tpath)
        all_tracks[vid] = tracks
        dts = [
            rows[i + 1][0] - rows[i][0]
            for rows in tracks.values()
            for i in range(min(len(rows) - 1, 5))
            if rows[i + 1][0] > rows[i][0]
        ]
        dt_by_video[vid] = float(np.median(dts)) if dts else 0.33
        duration_by_video[vid] = max((rows[-1][0] for rows in tracks.values()), default=0.0)
        h = hmap[vid]
        for rows in tracks.values():
            cls_names = [r[3] for r in rows]
            if max(set(cls_names), key=cls_names.count) not in ROADWAY_DEFINING_CLASSES:
                continue
            move = math.hypot(rows[-1][1] - rows[0][1], rows[-1][2] - rows[0][2])
            if move < ROADWAY_MIN_TRACK_MOVE_PX:
                continue
            for t, x, y, _ in rows:
                rx, ry = apply_h(h, x, y)
                if 0 <= rx < W_img and 0 <= ry < H_img:
                    cv2.circle(road, (int(rx), int(ry)), 6, 255, -1)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (ROADWAY_DILATE_PX * 2 + 1, ROADWAY_DILATE_PX * 2 + 1)
    )
    road = cv2.dilate(road, kernel)
    road = cv2.morphologyEx(road, cv2.MORPH_CLOSE, kernel)
    cv2.imwrite(str(CALIB / "roadway_mask.png"), road)
    prev = ref_frame.copy()
    prev[road > 0] = (prev[road > 0] * 0.55 + np.array([0, 140, 255]) * 0.45).astype(np.uint8)
    cv2.imwrite(str(CALIB / "roadway_mask_preview.jpg"), prev, [cv2.IMWRITE_JPEG_QUALITY, 85])

    # 횡단보도(분할 6개) 버퍼 마스크
    cw_mask = np.zeros_like(road)
    for z in zones:
        if z.get("side"):
            cv2.fillPoly(cw_mask, [np.array(z["polygon"], dtype=np.int32)], 255)
    cw_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (CROSSWALK_BUFFER_PX * 2 + 1, CROSSWALK_BUFFER_PX * 2 + 1)
    )
    cw_mask = cv2.dilate(cw_mask, cw_kernel)
    erode_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (ROADWAY_ERODE_FOR_JAY_PX * 2 + 1, ROADWAY_ERODE_FOR_JAY_PX * 2 + 1)
    )
    road_inner = cv2.erode(road, erode_kernel)
    jay_area = (road_inner > 0) & (cw_mask == 0)
    jay_prev = ref_frame.copy()
    jay_prev[jay_area] = (jay_prev[jay_area] * 0.55 + np.array([60, 60, 230]) * 0.45).astype(np.uint8)
    cv2.imwrite(str(CALIB / "jaywalk_area_preview.jpg"), jay_prev, [cv2.IMWRITE_JPEG_QUALITY, 85])

    # ── 3. 무단횡단 보행자 ──
    jay_rows = []
    jay_count_by_video = {}
    for vid, _, _ in VIDEOS:
        h = hmap[vid]
        dt = dt_by_video[vid]
        count = 0
        for tid, rows in all_tracks[vid].items():
            cls_names = [r[3] for r in rows]
            if max(set(cls_names), key=cls_names.count) != "person":
                continue
            if len(rows) < 2 or rows[-1][0] - rows[0][0] < 0.3:
                continue
            pts_in = []
            for t, x, y, _ in rows:
                rx, ry = apply_h(h, x, y)
                if 0 <= rx < W_img and 0 <= ry < H_img and jay_area[int(ry), int(rx)]:
                    pts_in.append((t, rx, ry))
            move_in = (
                math.hypot(pts_in[-1][1] - pts_in[0][1], pts_in[-1][2] - pts_in[0][2])
                if len(pts_in) >= 2
                else 0.0
            )
            if len(pts_in) * dt >= JAYWALK_MIN_SEC and move_in >= JAYWALK_MIN_MOVE_PX:
                count += 1
                jay_rows.append(
                    {
                        "source_video": vid,
                        "track_id": tid,
                        "first_sec": round(pts_in[0][0], 1),
                        "duration_in_roadway_sec": round(len(pts_in) * dt, 1),
                        "x_ref": round(pts_in[0][1], 0),
                        "y_ref": round(pts_in[0][2], 0),
                    }
                )
        jay_count_by_video[vid] = count
        print(f"jaywalkers {vid}: {count}")
    with (OUT / "jaywalkers.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source_video", "track_id", "first_sec", "duration_in_roadway_sec", "x_ref", "y_ref"])
        w.writeheader()
        w.writerows(jay_rows)

    # 무단횡단 궤적도 (차도 내 구간만, 기준틀 보정)
    jay_map = ref_frame.copy()
    for z in zones:
        pts = np.array(z["polygon"], dtype=np.int32)
        cv2.polylines(jay_map, [pts], True, (190, 190, 190), 2, cv2.LINE_AA)
    for vid, _, _ in VIDEOS:
        h = hmap[vid]
        dt = dt_by_video[vid]
        for tid, rows in all_tracks[vid].items():
            cls_names = [r[3] for r in rows]
            if max(set(cls_names), key=cls_names.count) != "person":
                continue
            pts_in = []
            for t, x, y, _ in rows:
                rx, ry = apply_h(h, x, y)
                if 0 <= rx < W_img and 0 <= ry < H_img and jay_area[int(ry), int(rx)]:
                    pts_in.append((rx, ry))
            if len(pts_in) >= 2 and len(pts_in) * dt >= JAYWALK_MIN_SEC:
                move_in = math.hypot(pts_in[-1][0] - pts_in[0][0], pts_in[-1][1] - pts_in[0][1])
                if move_in >= JAYWALK_MIN_MOVE_PX:
                    arr = np.array(pts_in, dtype=np.int32)
                    cv2.polylines(jay_map, [arr], False, (0, 0, 230), 3, cv2.LINE_AA)
                    cv2.circle(jay_map, tuple(arr[0]), 8, (0, 230, 0), -1, cv2.LINE_AA)
    cv2.imwrite(str(OUT / "jaywalk_trajectories.jpg"), jay_map, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # ── 4. ROI별 집계 + 상충 발생율 ──
    entries_sum = defaultdict(lambda: {"ped": 0, "veh": 0})
    zone_meta = {}
    for vid, _, _ in VIDEOS:
        with (INTERIM / vid / "roi_entries.csv").open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                entries_sum[r["roi_id"]]["ped"] += int(r["pedestrian_entries"])
                entries_sum[r["roi_id"]]["veh"] += int(r["vehicle_entries"])
                zone_meta[r["roi_id"]] = (r["roi_parent"], r["roi_side"])

    conflicts = defaultdict(lambda: {"pv": 0, "vv": 0, "pv_final": 0, "vv_final": 0})
    all_events = []
    for vid, _, _ in VIDEOS:
        with (INTERIM / vid / "pet_events_directional.csv").open(encoding="utf-8-sig", newline="") as f:
            for e in csv.DictReader(f):
                e["source_video"] = vid
                rx, ry = apply_h(hmap[vid], parse_float(e["event_x"]), parse_float(e["event_y"]))
                e["event_x_ref"], e["event_y_ref"] = round(rx, 1), round(ry, 1)
                all_events.append(e)
                key = "pv" if e["conflict_type"] == "pedestrian_vehicle" else "vv"
                conflicts[e["roi_id"]][key] += 1
                if e["event_scope"] == "final":
                    conflicts[e["roi_id"]][key + "_final"] += 1
    with (OUT / "combined_events.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["source_video"] + [k for k in all_events[0] if k != "source_video"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_events)

    total_hours = sum(duration_by_video.values()) / 3600.0
    table = []
    for roi_id in sorted(entries_sum):
        parent, side = zone_meta[roi_id]
        ent = entries_sum[roi_id]
        con = conflicts[roi_id]
        pv_rate = con["pv"] / ent["ped"] * 100 if ent["ped"] else 0.0
        vv_rate = con["vv"] / ent["veh"] * 100 if ent["veh"] else 0.0
        table.append(
            {
                "roi_id": roi_id,
                "parent": parent,
                "side": side or "-",
                "pedestrian_entries": ent["ped"],
                "vehicle_entries": ent["veh"],
                "pv_conflicts": con["pv"],
                "pv_conflicts_final": con["pv_final"],
                "vv_conflicts": con["vv"],
                "vv_conflicts_final": con["vv_final"],
                "pv_per_100_ped_entries": round(pv_rate, 2),
                "vv_per_100_veh_entries": round(vv_rate, 2),
                "pv_per_hour": round(con["pv"] / total_hours, 2),
                "vv_per_hour": round(con["vv"] / total_hours, 2),
            }
        )
    table.sort(key=lambda r: r["pv_per_100_ped_entries"], reverse=True)
    with (OUT / "risk_table_by_roi.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)

    # ── 5. 히트맵 ──
    for ctype, fname in [("pedestrian_vehicle", "heatmap_pedestrian_vehicle.jpg"), ("vehicle_vehicle", "heatmap_vehicle_vehicle.jpg")]:
        heat = np.zeros((H_img, W_img), dtype=np.float32)
        for e in all_events:
            if e["conflict_type"] != ctype:
                continue
            weight = 1.0 if e["event_scope"] == "final" else 0.5
            add_heat(heat, parse_float(e["event_x_ref"]), parse_float(e["event_y_ref"]), weight, HEAT_RADIUS)
        draw_heatmap(ref_frame, heat, OUT / fname, zones)

    # ── 메타 ──
    (OUT / "combined_metadata.json").write_text(
        json.dumps(
            {
                "videos": [v[0] for v in VIDEOS],
                "sampling_note": "DJI_0482=10fps(step3), 나머지=3fps(step10)",
                "duration_sec_by_video": {k: round(v, 1) for k, v in duration_by_video.items()},
                "total_hours": round(total_hours, 3),
                "jaywalkers_by_video": jay_count_by_video,
                "jaywalkers_total": sum(jay_count_by_video.values()),
                "events_total": len(all_events),
                "roadway_dilate_px": ROADWAY_DILATE_PX,
                "crosswalk_buffer_px": CROSSWALK_BUFFER_PX,
                "jaywalk_min_sec": JAYWALK_MIN_SEC,
                "heat_radius_px": HEAT_RADIUS,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"events={len(all_events)} jaywalkers={sum(jay_count_by_video.values())} hours={total_hours:.2f}")
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
