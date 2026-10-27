from __future__ import annotations

from _paths import BASE

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


DEFAULT_TRACKS = BASE / "runs" / "DJI_0482_sahi_step3_final" / "tracks_pixel.csv"
DEFAULT_VIDEO = BASE / "record" / "DJI_0482.MP4"
DEFAULT_OUT = BASE / "survey" / "track_overlays_DJI_0482"

# 시작점이 이 반경 안에서 이 시간창 안에 시작하는 다른 track = 같은 사람이 분절됐을 후보
CONTINUATION_DIST_PX = 250.0
CONTINUATION_TIME_SEC = 3.0


def parse_float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def read_tracks(path):
    tracks = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tid = (row.get("track_id") or "").strip()
            if not tid:
                continue
            tracks[tid].append(
                {
                    "t": parse_float(row.get("time_sec")),
                    "f": int(parse_float(row.get("frame_id"))),
                    "cls": (row.get("class_name") or "").strip(),
                    "x": parse_float(row.get("anchor_x") or row.get("foot_x") or row.get("cx")),
                    "y": parse_float(row.get("anchor_y") or row.get("foot_y") or row.get("cy")),
                }
            )
    for rows in tracks.values():
        rows.sort(key=lambda r: r["t"])
    return tracks


def dominant_class(rows):
    names = [r["cls"] for r in rows]
    return max(set(names), key=names.count)


def mmss(sec):
    return f"{int(sec // 60):02d}:{sec % 60:04.1f}"


def frame_at(video, frame_id):
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def continuation_candidates(target_id, tracks):
    """대상 track의 끝점 근처·직후에 시작하는 다른 track = 분절 후보."""
    t_rows = tracks[target_id]
    ex, ey, et = t_rows[-1]["x"], t_rows[-1]["y"], t_rows[-1]["t"]
    out = []
    for tid, rows in tracks.items():
        if tid == target_id:
            continue
        sx, sy, st = rows[0]["x"], rows[0]["y"], rows[0]["t"]
        gap = st - et
        dist = ((sx - ex) ** 2 + (sy - ey) ** 2) ** 0.5
        if 0 <= gap <= CONTINUATION_TIME_SEC and dist <= CONTINUATION_DIST_PX:
            out.append((tid, round(gap, 2), round(dist, 0)))
    return sorted(out, key=lambda x: (x[1], x[2]))


def draw_overlay(frame, rows, track_id, candidates, tracks, out_path):
    img = frame.copy()
    pts = np.array([(int(r["x"]), int(r["y"])) for r in rows], dtype=np.int32)

    # 분절 후보 궤적을 흐린 노란색으로 먼저
    for cid, gap, dist in candidates:
        cpts = np.array([(int(r["x"]), int(r["y"])) for r in tracks[cid]], dtype=np.int32)
        cv2.polylines(img, [cpts], False, (60, 200, 240), 2, cv2.LINE_AA)
        cx, cy = cpts[0]
        cv2.putText(img, f"ID {cid} (+{gap}s, {int(dist)}px)", (cx + 8, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 200, 240), 2, cv2.LINE_AA)

    # 대상 궤적: 굵은 시안 선 + 진행 방향 점
    cv2.polylines(img, [pts], False, (255, 255, 0), 4, cv2.LINE_AA)
    for p in pts:
        cv2.circle(img, tuple(p), 5, (255, 255, 0), -1, cv2.LINE_AA)
    # 시작(녹)·끝(적)
    cv2.circle(img, tuple(pts[0]), 16, (0, 230, 0), 3, cv2.LINE_AA)
    cv2.circle(img, tuple(pts[-1]), 16, (0, 0, 255), 3, cv2.LINE_AA)

    def label(text, org, color):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        x, y = org
        cv2.rectangle(img, (x - 4, y - th - 6), (x + tw + 4, y + 6), (0, 0, 0), -1)
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)

    label(f"START {mmss(rows[0]['t'])}", (pts[0][0] + 20, pts[0][1]), (0, 230, 0))
    label(f"END {mmss(rows[-1]['t'])}", (pts[-1][0] + 20, pts[-1][1]), (0, 0, 255))
    header = (
        f"track {track_id} | {dominant_class(rows)} | "
        f"{mmss(rows[0]['t'])}~{mmss(rows[-1]['t'])} "
        f"({rows[-1]['t'] - rows[0]['t']:.1f}s, {len(rows)}pts) | "
        f"continuation candidates: {len(candidates)}"
    )
    label(header, (30, 50), (255, 255, 255))
    cv2.imwrite(str(out_path), img, [cv2.IMWRITE_JPEG_QUALITY, 88])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", type=Path, default=DEFAULT_TRACKS)
    ap.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--ids", nargs="*", help="특정 track_id만. 없으면 8초 이상 person 표본 30개")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tracks = read_tracks(args.tracks)
    if args.ids:
        targets = [tid for tid in args.ids if tid in tracks]
    else:
        ped = []
        for tid, rows in tracks.items():
            if dominant_class(rows) != "person":
                continue
            if rows[-1]["t"] - rows[0]["t"] >= 8:
                ped.append((rows[0]["t"], tid))
        ped.sort()
        step = max(len(ped) // 30, 1)
        targets = [tid for _, tid in ped[::step][:30]]

    manifest = []
    for i, tid in enumerate(targets, 1):
        rows = tracks[tid]
        frame = frame_at(args.video, rows[len(rows) // 2]["f"])
        if frame is None:
            print(f"skip {tid}: frame read failed")
            continue
        cands = continuation_candidates(tid, tracks)
        out_path = args.out / f"sample_{i:02d}_track_{tid}.jpg"
        draw_overlay(frame, rows, tid, cands, tracks, out_path)
        manifest.append(
            {
                "sample_no": i,
                "track_id": tid,
                "class": dominant_class(rows),
                "start_sec": round(rows[0]["t"], 2),
                "end_sec": round(rows[-1]["t"], 2),
                "points": len(rows),
                "continuation_candidate_ids": ";".join(c[0] for c in cands),
                "continuation_count": len(cands),
                "image": out_path.name,
            }
        )
        print(f"[{i:02d}] track {tid}: {out_path.name}  후보 {len(cands)}개")

    with (args.out / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sample_no", "track_id", "class", "start_sec", "end_sec",
                "points", "continuation_candidate_ids", "continuation_count", "image",
            ],
        )
        w.writeheader()
        w.writerows(manifest)
    print(f"Saved {len(manifest)} overlays -> {args.out}")


if __name__ == "__main__":
    main()
