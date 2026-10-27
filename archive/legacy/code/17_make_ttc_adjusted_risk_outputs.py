from __future__ import annotations

from _paths import BASE

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = BASE


OUTPUT_FIELDS = [
    "source_video",
    "source_event_id",
    "event_id",
    "roi_id",
    "roi_name",
    "first_track_id",
    "first_class_name",
    "first_class_kind",
    "first_entry_sec",
    "first_exit_sec",
    "second_track_id",
    "second_class_name",
    "second_class_kind",
    "second_entry_sec",
    "second_exit_sec",
    "pet_sec",
    "event_scope",
    "conflict_type",
    "pet_score",
    "conflict_weight",
    "risk_score",
    "risk_level",
    "event_x",
    "event_y",
    "severity",
    "ttc_sec",
    "ttc_status",
    "approaching",
    "relative_speed_px_s",
    "distance_px",
    "pet_component",
    "ttc_component",
    "total_risk_score",
    "total_risk_level",
    "critical_event",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute TTC-adjusted risk and combined heatmap.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--background-video", type=Path, default=BASE_DIR / "record" / "DJI_0481.MP4")
    parser.add_argument("--pet-threshold", type=float, default=1.5)
    parser.add_argument("--ttc-threshold", type=float, default=3.0)
    parser.add_argument("--w-pet", type=float, default=0.6)
    parser.add_argument("--w-ttc", type=float, default=0.4)
    parser.add_argument("--critical-threshold", type=float, default=60.0)
    parser.add_argument("--radius", type=int, default=80)
    parser.add_argument("--alpha", type=float, default=0.18)
    parser.add_argument("--mask-threshold", type=int, default=4)
    parser.add_argument("--cell-size", type=int, default=160)
    parser.add_argument("pairs", nargs="+", help="source_video=events_csv=tracks_csv")
    return parser.parse_args()


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else BASE_DIR / path


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_pair(value: str) -> tuple[str, Path, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3:
        raise ValueError(f"Expected source_video=events_csv=tracks_csv, got: {value}")
    return parts[0], resolve(parts[1]), resolve(parts[2])


def read_tracks(path: Path) -> dict[int, list[dict]]:
    tracks: dict[int, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            track_id = int(parse_float(row.get("track_id", "")))
            tracks[track_id].append(
                {
                    "time_sec": parse_float(row.get("time_sec", "")),
                    "x": parse_float(row.get("anchor_x", row.get("foot_x", row.get("cx", "")))),
                    "y": parse_float(row.get("anchor_y", row.get("foot_y", row.get("cy", "")))),
                }
            )
    for rows in tracks.values():
        rows.sort(key=lambda item: item["time_sec"])
    return tracks


def nearest_index(rows: list[dict], time_sec: float) -> int:
    return min(range(len(rows)), key=lambda idx: abs(rows[idx]["time_sec"] - time_sec))


def estimate_state(rows: list[dict], time_sec: float) -> tuple[float, float, float, float] | None:
    if len(rows) < 2:
        return None
    idx = nearest_index(rows, time_sec)
    if idx == 0:
        a, b = rows[0], rows[1]
    elif idx == len(rows) - 1:
        a, b = rows[-2], rows[-1]
    else:
        before = rows[idx - 1]
        current = rows[idx]
        after = rows[idx + 1]
        if abs(after["time_sec"] - time_sec) < abs(time_sec - before["time_sec"]):
            a, b = current, after
        else:
            a, b = before, current
    dt = b["time_sec"] - a["time_sec"]
    if abs(dt) < 1e-6:
        return None
    vx = (b["x"] - a["x"]) / dt
    vy = (b["y"] - a["y"]) / dt
    base = rows[idx]
    px = base["x"] + vx * (time_sec - base["time_sec"])
    py = base["y"] + vy * (time_sec - base["time_sec"])
    return px, py, vx, vy


def compute_ttc(event: dict, tracks: dict[int, list[dict]]) -> dict:
    first_track_id = int(parse_float(event.get("first_track_id", "")))
    second_track_id = int(parse_float(event.get("second_track_id", "")))
    first_rows = tracks.get(first_track_id, [])
    second_rows = tracks.get(second_track_id, [])
    if len(first_rows) < 2 or len(second_rows) < 2:
        return {
            "ttc_sec": "",
            "ttc_status": "insufficient_track_points",
            "approaching": "false",
            "relative_speed_px_s": "",
            "distance_px": "",
        }

    first_exit = parse_float(event.get("first_exit_sec", ""))
    second_entry = parse_float(event.get("second_entry_sec", ""))
    state1 = estimate_state(first_rows, first_exit)
    state2 = estimate_state(second_rows, second_entry)
    if state1 is None or state2 is None:
        return {
            "ttc_sec": "",
            "ttc_status": "insufficient_velocity",
            "approaching": "false",
            "relative_speed_px_s": "",
            "distance_px": "",
        }

    x1, y1, vx1, vy1 = state1
    x2, y2, vx2, vy2 = state2
    dt = second_entry - first_exit
    x1 += vx1 * dt
    y1 += vy1 * dt

    rx = x2 - x1
    ry = y2 - y1
    rvx = vx2 - vx1
    rvy = vy2 - vy1
    relative_speed = math.hypot(rvx, rvy)
    distance = math.hypot(rx, ry)
    rv2 = rvx * rvx + rvy * rvy
    closing_dot = rx * rvx + ry * rvy
    if rv2 < 1e-6:
        return {
            "ttc_sec": "",
            "ttc_status": "zero_relative_speed",
            "approaching": "false",
            "relative_speed_px_s": round(relative_speed, 3),
            "distance_px": round(distance, 3),
        }
    if closing_dot >= 0:
        return {
            "ttc_sec": "",
            "ttc_status": "not_approaching",
            "approaching": "false",
            "relative_speed_px_s": round(relative_speed, 3),
            "distance_px": round(distance, 3),
        }
    ttc = -closing_dot / rv2
    return {
        "ttc_sec": round(ttc, 3),
        "ttc_status": "computed",
        "approaching": "true",
        "relative_speed_px_s": round(relative_speed, 3),
        "distance_px": round(distance, 3),
    }


def risk_level(score: float) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def enrich_events(
    source_video: str,
    events_path: Path,
    tracks_path: Path,
    pet_threshold: float,
    ttc_threshold: float,
    w_pet: float,
    w_ttc: float,
    critical_threshold: float,
) -> list[dict]:
    tracks = read_tracks(tracks_path)
    rows: list[dict] = []
    with events_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            out = dict(row)
            out["source_video"] = source_video
            out["source_event_id"] = row.get("event_id", "")
            ttc = compute_ttc(row, tracks)
            out.update(ttc)

            pet_sec = parse_float(row.get("pet_sec", ""))
            ttc_sec = parse_float(ttc["ttc_sec"], default=math.inf)
            pet_component = max(0.0, (pet_threshold - pet_sec) / pet_threshold)
            ttc_component = (
                max(0.0, (ttc_threshold - ttc_sec) / ttc_threshold)
                if ttc["approaching"] == "true" and math.isfinite(ttc_sec)
                else 0.0
            )
            total = 100.0 * (w_pet * pet_component + w_ttc * ttc_component)
            critical = (
                total >= critical_threshold
                and ttc["approaching"] == "true"
                and math.isfinite(ttc_sec)
                and ttc_sec <= ttc_threshold
            )
            out["pet_component"] = round(pet_component, 4)
            out["ttc_component"] = round(ttc_component, 4)
            out["total_risk_score"] = round(total, 3)
            out["total_risk_level"] = risk_level(total)
            out["critical_event"] = "true" if critical else "false"
            rows.append(out)
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_background(path: Path) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open background video: {path}")
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read background frame: {path}")
    return frame


def add_heat(heat: np.ndarray, x: float, y: float, value: float, radius: int) -> None:
    height, width = heat.shape
    cx = int(round(x))
    cy = int(round(y))
    x1 = max(0, cx - radius)
    y1 = max(0, cy - radius)
    x2 = min(width, cx + radius + 1)
    y2 = min(height, cy + radius + 1)
    if x1 >= x2 or y1 >= y2:
        return
    yy, xx = np.ogrid[y1:y2, x1:x2]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    sigma2 = (radius / 2.0) ** 2
    kernel = np.exp(-dist2 / (2.0 * sigma2)) * value
    heat[y1:y2, x1:x2] += np.where(dist2 <= radius**2, kernel, 0.0)


def draw_heatmap(
    background: np.ndarray,
    events: list[dict],
    output_path: Path,
    radius: int,
    alpha: float,
    mask_threshold: int,
) -> None:
    heat = np.zeros(background.shape[:2], dtype=np.float32)
    for event in events:
        score = parse_float(event.get("total_risk_score", ""))
        if score <= 0:
            continue
        add_heat(
            heat,
            parse_float(event.get("event_x", "")),
            parse_float(event.get("event_y", "")),
            score,
            radius,
        )
    if heat.max() > 0:
        heat_norm = np.clip(heat / heat.max() * 255.0, 0, 255).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        mask = heat_norm >= max(1, mask_threshold)
        blended = cv2.addWeighted(background, 1.0 - alpha, heat_color, alpha, 0)
        overlay = background.copy()
        overlay[mask] = blended[mask]
    else:
        overlay = background.copy()

    for event in events:
        if parse_float(event.get("total_risk_score", "")) <= 0:
            continue
        x = int(round(parse_float(event.get("event_x", ""))))
        y = int(round(parse_float(event.get("event_y", ""))))
        color = (255, 255, 255) if event.get("critical_event") == "true" else (190, 190, 190)
        cv2.circle(overlay, (x, y), 8, color, -1, lineType=cv2.LINE_AA)
        cv2.circle(overlay, (x, y), 11, (0, 0, 0), 2, lineType=cv2.LINE_AA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), overlay):
        raise RuntimeError(f"Could not write heatmap: {output_path}")


def summarize_by_video(events: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["source_video"]].append(event)
    rows = []
    for source_video, items in sorted(grouped.items()):
        rows.append(
            {
                "source_video": source_video,
                "event_count": len(items),
                "old_final_event_count": sum(1 for item in items if item.get("event_scope") == "final"),
                "critical_event_count": sum(1 for item in items if item.get("critical_event") == "true"),
                "ttc_computed_count": sum(1 for item in items if item.get("ttc_status") == "computed"),
                "total_risk_score_sum": round(
                    sum(parse_float(item.get("total_risk_score", "")) for item in items), 3
                ),
                "avg_total_risk_score": round(
                    sum(parse_float(item.get("total_risk_score", "")) for item in items) / len(items),
                    3,
                ),
            }
        )
    return rows


def summarize_by_roi(events: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event.get("roi_id", "")].append(event)
    rows = []
    for roi_id, items in sorted(grouped.items()):
        rows.append(
            {
                "roi_id": roi_id,
                "roi_name": items[0].get("roi_name", roi_id),
                "event_count": len(items),
                "old_final_event_count": sum(1 for item in items if item.get("event_scope") == "final"),
                "critical_event_count": sum(1 for item in items if item.get("critical_event") == "true"),
                "ttc_computed_count": sum(1 for item in items if item.get("ttc_status") == "computed"),
                "total_risk_score_sum": round(
                    sum(parse_float(item.get("total_risk_score", "")) for item in items), 3
                ),
            }
        )
    rows.sort(key=lambda item: item["total_risk_score_sum"], reverse=True)
    return rows


def main() -> None:
    args = parse_args()
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_events: list[dict] = []
    sources = []
    for pair in args.pairs:
        source_video, events_path, tracks_path = parse_pair(pair)
        if not events_path.exists():
            raise FileNotFoundError(events_path)
        if not tracks_path.exists():
            raise FileNotFoundError(tracks_path)
        events = enrich_events(
            source_video,
            events_path,
            tracks_path,
            args.pet_threshold,
            args.ttc_threshold,
            args.w_pet,
            args.w_ttc,
            args.critical_threshold,
        )
        all_events.extend(events)
        sources.append({"source_video": source_video, "events": str(events_path), "tracks": str(tracks_path)})

    final_events = [event for event in all_events if event.get("event_scope") == "final"]
    critical_events = [event for event in all_events if event.get("critical_event") == "true"]
    write_csv(output_dir / "combined_step10_pet_ttc_risk_all.csv", all_events, OUTPUT_FIELDS)
    write_csv(output_dir / "combined_step10_pet_ttc_risk_final.csv", final_events, OUTPUT_FIELDS)
    write_csv(output_dir / "combined_step10_pet_ttc_risk_critical.csv", critical_events, OUTPUT_FIELDS)
    write_csv(
        output_dir / "combined_step10_pet_ttc_summary_by_video.csv",
        summarize_by_video(all_events),
        [
            "source_video",
            "event_count",
            "old_final_event_count",
            "critical_event_count",
            "ttc_computed_count",
            "total_risk_score_sum",
            "avg_total_risk_score",
        ],
    )
    write_csv(
        output_dir / "combined_step10_pet_ttc_summary_by_roi.csv",
        summarize_by_roi(all_events),
        [
            "roi_id",
            "roi_name",
            "event_count",
            "old_final_event_count",
            "critical_event_count",
            "ttc_computed_count",
            "total_risk_score_sum",
        ],
    )

    background = read_background(resolve(args.background_video))
    draw_heatmap(
        background,
        final_events,
        output_dir / "combined_step10_pet_ttc_heatmap_final_light_alpha018.png",
        args.radius,
        args.alpha,
        args.mask_threshold,
    )
    draw_heatmap(
        background,
        critical_events,
        output_dir / "combined_step10_pet_ttc_heatmap_critical_light_alpha018.png",
        args.radius,
        args.alpha,
        args.mask_threshold,
    )
    (output_dir / "combined_step10_pet_ttc_metadata.json").write_text(
        json.dumps(
            {
                "risk_formula": "total_risk_score = 100 * (w_pet * max(0, (pet_threshold - pet_sec) / pet_threshold) + w_ttc * max(0, (ttc_threshold - ttc_sec) / ttc_threshold))",
                "critical_rule": "total_risk_score >= critical_threshold and approaching == true and ttc_sec <= ttc_threshold",
                "ttc_note": "TTC is an image-plane approximation using track anchor points in pixel coordinates.",
                "pet_threshold": args.pet_threshold,
                "ttc_threshold": args.ttc_threshold,
                "w_pet": args.w_pet,
                "w_ttc": args.w_ttc,
                "critical_threshold": args.critical_threshold,
                "source_count": len(sources),
                "event_count": len(all_events),
                "old_final_event_count": len(final_events),
                "critical_event_count": len(critical_events),
                "sources": sources,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Events: {len(all_events)}")
    print(f"Old final events: {len(final_events)}")
    print(f"TTC critical events: {len(critical_events)}")
    print(f"Saved: {output_dir}")


if __name__ == "__main__":
    main()
