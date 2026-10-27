from __future__ import annotations

from _paths import BASE

"""횡단보도 ROI를 진입측/진출측으로 분할하고 차량 궤적 방향으로 자동 라벨링한다.

- 입력: runs/DJI_0481_sahi_step10/conflict_zones.json (8개 영상 공통 ROI)
        runs/DJI_0482_sahi_step3_final/tracks_pixel.csv (라벨 판별용 차량 궤적, 10fps)
- 출력: calib/rois_split.json (분할 ROI, git 추적 대상)
        calib/rois_split_preview.jpg (확인용 미리보기)
"""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


ZONES_PATH = BASE / "runs" / "DJI_0481_sahi_step10" / "conflict_zones.json"
# 구 Phase A 산출물(DJI_0482_sahi_step3_final)은 새 GPU 워크스테이션에 이관되지 않아
# 현재 채택된 yolo11l+mt0.9 데이터셋으로 대체.
TRACKS_PATH = BASE / "runs" / "before_l_mt09" / "DJI_0482" / "tracks_pixel_filtered.csv"
BACKGROUND_VIDEO = BASE / "record" / "before" / "DJI_0481.MP4"
OUT_DIR = BASE / "calib"

SPLIT_TARGETS = ["crosswalk_northwest", "crosswalk_southwest", "crosswalk_east"]

# 자동 라벨 수동 보정: 통과 차량 표본이 부족해 다수결이 불안정한 횡단보도.
# NW는 0482에서 통과 차량 1대뿐 → 순환방향(반시계)·우측통행 기하로 판정: 진입측=남서쪽 절반.
MANUAL_SWAP = {"crosswalk_northwest"}

# 진입/진출 경계 기준점: 안전지대(보행자 대기 공간, 줄무늬 끊김 구간) 중앙 (0481 픽셀).
# 미지정 시 폴리곤 중간(0.5)에서 절단. East는 기존 중간 절단이 안전지대와 일치.
BOUNDARY_POINTS = {
    "crosswalk_northwest": (1215.0, 550.0),
    "crosswalk_southwest": (1075.0, 1460.0),
}
# 회전부 중앙섬 중심 (0481 기준 픽셀) — 진입/진출 판별 기준점
ROUNDABOUT_CENTER = (1870.0, 960.0)

VEHICLE_CLASSES = {"car", "bus", "truck", "motorcycle", "bicycle"}


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


def centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def split_quad(poly, boundary_point=None):
    """사각형 밴드를 긴 축 방향으로 둘로 나눈다.

    긴 변 쌍(횡단보도가 도로를 가로지르는 방향의 두 변)을 절단 지점 t에서 잘라 잇는다.
    boundary_point가 주어지면(안전지대 중앙) 그 점을 긴 변에 투영한 위치에서,
    없으면 중간(t=0.5)에서 절단한다.
    """
    if len(poly) != 4:
        raise ValueError(f"4각형만 지원 (꼭짓점 {len(poly)}개)")
    p = [np.array(v, dtype=float) for v in poly]
    edges = [(p[i], p[(i + 1) % 4]) for i in range(4)]
    lengths = [float(np.linalg.norm(b - a)) for a, b in edges]
    if lengths[0] + lengths[2] >= lengths[1] + lengths[3]:
        idx_a, idx_b = 0, 2  # p0p1, p2p3 (서로 반대 방향 순회)
    else:
        idx_a, idx_b = 1, 3

    def cut_t(edge, point):
        a, b = edge
        ab = b - a
        return float(np.clip(np.dot(np.array(point) - a, ab) / (np.dot(ab, ab) + 1e-9), 0.15, 0.85))

    if boundary_point is not None:
        t_a = cut_t(edges[idx_a], boundary_point)
        t_b = cut_t(edges[idx_b], boundary_point)
    else:
        t_a = t_b = 0.5
    a1, b1 = edges[idx_a]
    a2, b2 = edges[idx_b]
    m1 = a1 + (b1 - a1) * t_a
    m2 = a2 + (b2 - a2) * t_b
    if idx_a == 0:
        half1 = [p[0].tolist(), m1.tolist(), m2.tolist(), p[3].tolist()]
        half2 = [m1.tolist(), p[1].tolist(), p[2].tolist(), m2.tolist()]
    else:
        half1 = [p[0].tolist(), p[1].tolist(), m1.tolist(), m2.tolist()]
        half2 = [m2.tolist(), m1.tolist(), p[2].tolist(), p[3].tolist()]
    return half1, half2


def load_vehicle_tracks(path):
    tracks = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("class_name") or "").strip() not in VEHICLE_CLASSES:
                continue
            tracks[row["track_id"]].append(
                (
                    parse_float(row.get("time_sec")),
                    parse_float(row.get("anchor_x") or row.get("foot_x") or row.get("cx")),
                    parse_float(row.get("anchor_y") or row.get("foot_y") or row.get("cy")),
                )
            )
    for rows in tracks.values():
        rows.sort()
    return tracks


def label_half(half_poly, tracks):
    """이 절반을 지난 차량들의 평균 이동방향이 회전부 중심을 향하면 entry."""
    cen = centroid(half_poly)
    to_center = np.array([ROUNDABOUT_CENTER[0] - cen[0], ROUNDABOUT_CENTER[1] - cen[1]])
    to_center /= np.linalg.norm(to_center) + 1e-9
    votes_toward = votes_away = 0
    for rows in tracks.values():
        inside = [(t, x, y) for t, x, y in rows if point_in_polygon(x, y, half_poly)]
        if len(inside) < 2:
            continue
        d = np.array([inside[-1][1] - inside[0][1], inside[-1][2] - inside[0][2]])
        n = np.linalg.norm(d)
        if n < 5:  # 정지 차량 제외
            continue
        if float(np.dot(d / n, to_center)) > 0:
            votes_toward += 1
        else:
            votes_away += 1
    return ("entry" if votes_toward >= votes_away else "exit"), votes_toward, votes_away


def main():
    OUT_DIR.mkdir(exist_ok=True)
    zones = json.load(ZONES_PATH.open(encoding="utf-8"))["zones"]
    tracks = load_vehicle_tracks(TRACKS_PATH)

    out_zones = []
    for zone in zones:
        if zone["id"] not in SPLIT_TARGETS:
            out_zones.append({**zone, "side": None, "parent": None})
            continue
        half1, half2 = split_quad(zone["polygon"], BOUNDARY_POINTS.get(zone["id"]))
        (label1, t1, a1) = label_half(half1, tracks)
        (label2, t2, a2) = label_half(half2, tracks)
        if label1 == label2:
            # 표가 갈리지 않으면 득표차가 큰 쪽을 우선하고 반대편을 반전
            if (t1 - a1) >= (t2 - a2):
                label2 = "exit" if label1 == "entry" else "entry"
            else:
                label1 = "exit" if label2 == "entry" else "entry"
        if zone["id"] in MANUAL_SWAP:
            label1, label2 = label2, label1
        for half, label, tw, aw in [(half1, label1, t1, a1), (half2, label2, t2, a2)]:
            side_kr = "진입측" if label == "entry" else "진출측"
            out_zones.append(
                {
                    "id": f"{zone['id']}_{label}",
                    "name": f"{zone.get('name', zone['id'])} ({side_kr})",
                    "polygon": [[round(v, 1) for v in pt] for pt in half],
                    "side": label,
                    "parent": zone["id"],
                    "label_votes": {"toward_center": tw, "away_from_center": aw},
                }
            )
        print(f"{zone['id']}: half1={label1}(향{t1}/이{a1})  half2={label2}(향{t2}/이{a2})")

    result = {
        "source": str(ZONES_PATH),
        "roundabout_center_px": ROUNDABOUT_CENTER,
        "note": "entry=회전부로 진입하는 차량측 절반, exit=회전부에서 진출하는 차량측 절반. "
        "라벨은 DJI_0482 10fps 차량 궤적의 이동방향 다수결로 자동 판별.",
        "zones": out_zones,
    }
    out_json = OUT_DIR / "rois_split.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 미리보기 렌더링
    cap = cv2.VideoCapture(str(BACKGROUND_VIDEO))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("배경 프레임 읽기 실패")
    overlay = frame.copy()
    COLOR = {"entry": (255, 160, 0), "exit": (0, 90, 255), None: (160, 160, 160)}
    for z in out_zones:
        pts = np.array(z["polygon"], dtype=np.int32)
        cv2.fillPoly(overlay, [pts], COLOR[z["side"]])
    frame = cv2.addWeighted(overlay, 0.32, frame, 0.68, 0)
    for z in out_zones:
        pts = np.array(z["polygon"], dtype=np.int32)
        cv2.polylines(frame, [pts], True, COLOR[z["side"]], 4, cv2.LINE_AA)
        cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
        label = z["id"]
        (tw_, th_), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        cv2.rectangle(frame, (cx - tw_ // 2 - 6, cy - th_ - 8), (cx + tw_ // 2 + 6, cy + 6), (0, 0, 0), -1)
        cv2.putText(frame, label, (cx - tw_ // 2, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.9, COLOR[z["side"]], 2, cv2.LINE_AA)
    cv2.circle(frame, tuple(map(int, ROUNDABOUT_CENTER)), 12, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.putText(frame, "RB center", (int(ROUNDABOUT_CENTER[0]) + 16, int(ROUNDABOUT_CENTER[1]) + 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    # 범례
    cv2.rectangle(frame, (30, 30), (560, 130), (0, 0, 0), -1)
    cv2.putText(frame, "ENTRY side (to roundabout)", (50, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.0, COLOR["entry"], 2, cv2.LINE_AA)
    cv2.putText(frame, "EXIT side (from roundabout)", (50, 112), cv2.FONT_HERSHEY_SIMPLEX, 1.0, COLOR["exit"], 2, cv2.LINE_AA)
    out_img = OUT_DIR / "rois_split_preview.jpg"
    cv2.imwrite(str(out_img), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"saved: {out_json}")
    print(f"saved: {out_img}")


if __name__ == "__main__":
    main()
