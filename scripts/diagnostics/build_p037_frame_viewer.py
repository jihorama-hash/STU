from __future__ import annotations

import base64
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[2]
VIDEO_PATH = ROOT / "data/raw/before/DJI_0482.MP4"
MANIFEST_PATH = ROOT / "manifests/raw_videos.csv"
OUTPUT_PATH = ROOT / "outputs/diagnostics/P037_visibility_review_20261102.html"
START_FRAME = 5820
END_FRAME = 5994
CROP = {"left": 1700, "top": 1350, "width": 1500, "height": 800}
SOURCE_FPS_NUMERATOR = 30000
SOURCE_FPS_DENOMINATOR = 1001


def _video_sha256_from_manifest() -> str:
    with MANIFEST_PATH.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["video_id"] == "DJI_0482":
                return row["sha256"]
    raise ValueError("DJI_0482 is absent from the raw-video manifest")


def _read_frames() -> list[dict[str, object]]:
    capture = cv2.VideoCapture(str(VIDEO_PATH))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {VIDEO_PATH}")
    if not capture.set(cv2.CAP_PROP_POS_FRAMES, START_FRAME):
        capture.release()
        raise RuntimeError(f"cannot seek to source frame {START_FRAME}")

    frames: list[dict[str, object]] = []
    try:
        for frame_index in range(START_FRAME, END_FRAME + 1):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"cannot read source frame {frame_index}")
            left, top = CROP["left"], CROP["top"]
            right, bottom = left + CROP["width"], top + CROP["height"]
            crop = frame[top:bottom, left:right]
            ok, encoded = cv2.imencode(
                ".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 82]
            )
            if not ok:
                raise RuntimeError(f"cannot encode source frame {frame_index}")
            data = base64.b64encode(encoded).decode("ascii")
            frames.append({"frame": frame_index, "jpg": data})
    finally:
        capture.release()
    return frames


def _page(frames: list[dict[str, object]]) -> str:
    frames_json = json.dumps(frames, separators=(",", ":"))
    page = r"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>P037 visibility frame review</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#11151b;color:#f0f3f8;font:16px system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:18px}h1{font-size:1.3rem;margin:0 0 8px}.meta{color:#b8c2cf;margin-bottom:14px}
img{display:block;width:min(100%,1200px);height:auto;margin:auto;background:#000}
.controls{display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;margin:14px auto}
button,input{font:inherit;color:inherit;background:#252d39;border:1px solid #526071;border-radius:6px;padding:8px 12px}
input[type=range]{width:min(60vw,700px);padding:0}#frameLabel{font-variant-numeric:tabular-nums;min-width:220px;text-align:center}
.hint{text-align:center;color:#b8c2cf;font-size:.92rem}
</style><main>
<h1>P037 · DJI_0482 원본 프레임 검토</h1>
<div class="meta">source frame 5820–5994 · 30,000/1,001 fps · source-pixel crop x=1700–3199, y=1350–2149</div>
<img id="frame" alt="P037 후보 구간의 원본 프레임 crop">
<div class="controls"><button id="prev">← 이전 프레임</button><input id="slider" type="range" min="0" value="0"><button id="next">다음 프레임 →</button></div>
<div id="frameLabel"></div><div class="hint">← / → 한 프레임 이동 · Space 자동재생/일시정지 · 재생은 초당 5프레임</div>
</main><script>
const frames=__FRAMES__,img=document.getElementById("frame"),slider=document.getElementById("slider"),label=document.getElementById("frameLabel");
let index=0,timer=null;slider.max=String(frames.length-1);
function show(i){index=Math.max(0,Math.min(frames.length-1,i));const f=frames[index];img.src="data:image/jpeg;base64,"+f.jpg;slider.value=String(index);label.textContent=`Frame ${f.frame} · ${(f.frame*1001/30000).toFixed(3)} s · ${index+1}/${frames.length}`}
function play(){if(timer){clearInterval(timer);timer=null;return}timer=setInterval(()=>{if(index>=frames.length-1){clearInterval(timer);timer=null;return}show(index+1)},200)}
document.getElementById("prev").onclick=()=>show(index-1);document.getElementById("next").onclick=()=>show(index+1);slider.oninput=()=>show(+slider.value);
document.addEventListener("keydown",e=>{if(e.key==="ArrowLeft")show(index-1);else if(e.key==="ArrowRight")show(index+1);else if(e.code==="Space"){e.preventDefault();play()}});show(0);
</script></html>"""
    return page.replace("__FRAMES__", frames_json)


def main() -> None:
    frames = _read_frames()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(_page(frames), encoding="utf-8")
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": "worktree",
        "source_file": str(VIDEO_PATH.relative_to(ROOT)),
        "source_sha256": _video_sha256_from_manifest(),
        "source_frame_range_inclusive": [START_FRAME, END_FRAME],
        "source_fps": f"{SOURCE_FPS_NUMERATOR}/{SOURCE_FPS_DENOMINATOR}",
        "coordinate_system": "source_px",
        "crop_xywh_source_px": CROP,
        "unit": "px",
        "review_status": "visual_review_aid_only",
        "gt_modified": False,
    }
    OUTPUT_PATH.with_suffix(".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(OUTPUT_PATH)
    print(f"frames={len(frames)} bytes={OUTPUT_PATH.stat().st_size}")


if __name__ == "__main__":
    main()
