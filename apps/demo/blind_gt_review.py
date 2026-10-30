"""Stateful browser viewer for the DJI_0482 blind manual GT pilot."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2


REPOSITORY_ROOT = Path(__file__).parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.blind_gt_review_viewer import (  # noqa: E402
    DEFAULT_OBJECTS_WORKSHEET,
    DEFAULT_VIDEO,
    DEFAULT_VISIBILITY_WORKSHEET,
    EvaluationGrid,
    FrameReader,
    print_validation,
    validate_worksheets,
)


PLAYBACK_WIDTH = 1280
PLAYBACK_JPEG_QUALITY = 88
PAUSED_JPEG_QUALITY = 94


PAGE_HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DJI_0482 Blind GT Review</title>
  <style>
    :root {
      color-scheme: dark;
      --panel: #171a20;
      --panel-2: #222733;
      --border: #394150;
      --text: #f4f6fa;
      --muted: #aeb6c5;
      --accent: #62b0ff;
      --danger: #ff8080;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #0d0f13;
      color: var(--text);
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    main {
      width: min(1500px, calc(100vw - 32px));
      margin: 16px auto 32px;
    }
    h1 { margin: 0 0 4px; font-size: 1.55rem; }
    .blind-note { color: var(--muted); margin-bottom: 12px; }
    #metadata {
      height: 42px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 14px;
      border: 1px solid var(--border);
      border-bottom: 0;
      border-radius: 8px 8px 0 0;
      background: var(--panel);
      font-variant-numeric: tabular-nums;
    }
    #frameLabel { font-weight: 700; }
    #playbackState { color: var(--accent); }
    #viewport {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      overflow: hidden;
      background: #000;
      border: 1px solid var(--border);
      contain: layout paint;
      touch-action: none;
      cursor: grab;
    }
    #viewport.dragging { cursor: grabbing; }
    #frameImage {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: contain;
      user-select: none;
      -webkit-user-drag: none;
      transform-origin: 50% 50%;
      will-change: transform;
    }
    #loading {
      position: absolute;
      right: 12px;
      bottom: 10px;
      min-width: 94px;
      padding: 5px 9px;
      border-radius: 5px;
      background: rgba(0, 0, 0, 0.72);
      color: var(--muted);
      text-align: center;
      visibility: hidden;
    }
    #loading.visible { visibility: visible; }
    .controls {
      min-height: 116px;
      padding: 10px;
      border: 1px solid var(--border);
      border-top: 0;
      border-radius: 0 0 8px 8px;
      background: var(--panel);
    }
    .row {
      display: grid;
      grid-template-columns: repeat(8, minmax(80px, 1fr));
      gap: 8px;
      margin-bottom: 8px;
    }
    .row:last-child { margin-bottom: 0; }
    button, input {
      height: 40px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel-2);
      color: var(--text);
      font: inherit;
      font-variant-numeric: tabular-nums;
    }
    button { cursor: pointer; padding: 0 10px; }
    button:hover { border-color: var(--accent); }
    button.primary { background: #155b92; border-color: #338bd0; font-weight: 700; }
    input { width: 100%; padding: 0 10px; }
    .jump-group { display: grid; grid-template-columns: 1fr 72px; gap: 6px; }
    #statusLine {
      min-height: 24px;
      margin-top: 10px;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    #statusLine.error { color: var(--danger); }
    .help {
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.9rem;
    }
    @media (max-width: 900px) {
      main { width: calc(100vw - 16px); margin-top: 8px; }
      .row { grid-template-columns: repeat(4, 1fr); }
      .controls { min-height: 212px; }
      #metadata { font-size: 0.88rem; }
    }
  </style>
</head>
<body>
<main>
  <h1>DJI_0482 Blind GT Review</h1>
  <div class="blind-note">
    원본 프레임 메타데이터 전용 · 자동 검출, track ID, confidence, ROI 및 interaction 후보 미표시
  </div>

  <section id="metadata">
    <span id="frameLabel">source frame 4196 · PTS 140.006533 s</span>
    <span id="playbackState">일시정지 · 고해상도</span>
  </section>
  <section id="viewport">
    <img id="frameImage" alt="Blind GT source frame">
    <div id="loading">불러오는 중</div>
  </section>
  <section class="controls">
    <div class="row">
      <button id="playPause" class="primary">▶ 재생</button>
      <button data-move="-150">−5초</button>
      <button data-move="-30">−1초</button>
      <button data-move="-2">← 이전</button>
      <button data-move="2">다음 →</button>
      <button data-move="30">+1초</button>
      <button data-move="150">+5초</button>
      <button id="goStart">처음으로</button>
    </div>
    <div class="row">
      <div class="jump-group">
        <input id="jumpInput" type="number" min="4196" max="5994" step="2" value="4196">
        <button id="jumpButton">이동</button>
      </div>
      <button id="zoomOut">축소 −</button>
      <button id="zoomIn">확대 +</button>
      <button id="zoomReset">화면 맞춤</button>
      <button id="reloadFull">현재 프레임 재로드</button>
      <span></span><span></span><span></span>
    </div>
  </section>
  <div id="statusLine">evaluation grid 4196..5994 step 2 · evaluation FPS 14.985015</div>
  <div class="help">
    Space 재생/일시정지 · ←/→ 한 evaluation frame · Shift+←/→ 약 1초 · PageUp/PageDown 약 5초 ·
    마우스 드래그로 확대 화면 이동. 일시정지 후 재생하면 현재 프레임 다음부터 이어집니다.
  </div>
</main>

<script>
  "use strict";
  const START = 4196;
  const END = 5994;
  const STEP = 2;
  const SOURCE_FPS = 30000 / 1001;
  const EVALUATION_FPS = SOURCE_FPS / STEP;
  const FRAME_INTERVAL_MS = 1000 / EVALUATION_FPS;

  const frameImage = document.getElementById("frameImage");
  const viewport = document.getElementById("viewport");
  const frameLabel = document.getElementById("frameLabel");
  const playbackState = document.getElementById("playbackState");
  const loading = document.getElementById("loading");
  const statusLine = document.getElementById("statusLine");
  const playPause = document.getElementById("playPause");
  const jumpInput = document.getElementById("jumpInput");

  let currentFrame = START;
  let playing = false;
  let playbackGeneration = 0;
  let requestSerial = 0;
  let currentObjectUrl = null;
  let zoom = 1;
  let panX = 0;
  let panY = 0;
  let dragging = false;
  let dragStartX = 0;
  let dragStartY = 0;

  function validFrame(frame) {
    return Number.isInteger(frame) && frame >= START && frame <= END
      && (frame - START) % STEP === 0;
  }

  function clampFrame(frame) {
    const clamped = Math.min(END, Math.max(START, frame));
    return START + Math.round((clamped - START) / STEP) * STEP;
  }

  function ptsSeconds(frame) {
    return frame / SOURCE_FPS;
  }

  function updateMetadata() {
    frameLabel.textContent = `source frame ${currentFrame} · PTS ${ptsSeconds(currentFrame).toFixed(6)} s`;
    jumpInput.value = currentFrame;
    playbackState.textContent = playing ? "재생 중 · 표시용 1280px" : "일시정지 · 고해상도";
    playPause.textContent = playing ? "Ⅱ 일시정지" : "▶ 이어서 재생";
  }

  function setStatus(message, isError = false) {
    statusLine.textContent = message;
    statusLine.classList.toggle("error", isError);
  }

  function applyTransform() {
    frameImage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  }

  function resetTransform() {
    zoom = 1;
    panX = 0;
    panY = 0;
    applyTransform();
  }

  function sleep(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, milliseconds));
  }

  async function displayFrame(frame, quality, generation = null) {
    if (!validFrame(frame)) {
      setStatus(`${frame}은 evaluation grid에 없습니다.`, true);
      return false;
    }
    const serial = ++requestSerial;
    loading.classList.add("visible");
    let response;
    try {
      response = await fetch(`/api/frame/${frame}?quality=${quality}`, {cache: "no-store"});
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const blob = await response.blob();
      const nextUrl = URL.createObjectURL(blob);
      await new Promise((resolve, reject) => {
        const preload = new Image();
        preload.onload = resolve;
        preload.onerror = reject;
        preload.src = nextUrl;
      });
      if (serial !== requestSerial || (generation !== null && generation !== playbackGeneration)) {
        URL.revokeObjectURL(nextUrl);
        return false;
      }
      const previousUrl = currentObjectUrl;
      frameImage.src = nextUrl;
      currentObjectUrl = nextUrl;
      currentFrame = frame;
      updateMetadata();
      if (previousUrl) {
        URL.revokeObjectURL(previousUrl);
      }
      setStatus(
        `정확한 source frame ${currentFrame} · PTS ${ptsSeconds(currentFrame).toFixed(6)} s · `
        + `zoom ${zoom.toFixed(1)}×`
      );
      return true;
    } catch (error) {
      if (serial === requestSerial) {
        setStatus(`프레임 로드 실패: ${error}`, true);
      }
      return false;
    } finally {
      if (serial === requestSerial) {
        loading.classList.remove("visible");
      }
    }
  }

  async function pausePlayback(loadHighResolution = true) {
    playing = false;
    playbackGeneration += 1;
    updateMetadata();
    if (loadHighResolution) {
      await displayFrame(currentFrame, "full");
    }
  }

  async function startPlayback() {
    if (playing) return;
    if (currentFrame >= END) {
      setStatus("마지막 프레임입니다. 다시 보려면 '처음으로'를 누르세요.", true);
      return;
    }
    playing = true;
    const generation = ++playbackGeneration;
    updateMetadata();
    let deadline = performance.now() + FRAME_INTERVAL_MS;

    while (playing && generation === playbackGeneration && currentFrame < END) {
      const wait = deadline - performance.now();
      if (wait > 0) await sleep(wait);
      if (!playing || generation !== playbackGeneration) return;

      const nextFrame = Math.min(END, currentFrame + STEP);
      const displayed = await displayFrame(nextFrame, "play", generation);
      if (!displayed || !playing || generation !== playbackGeneration) return;
      deadline += FRAME_INTERVAL_MS;
    }

    if (generation === playbackGeneration && currentFrame >= END) {
      playing = false;
      playbackGeneration += 1;
      updateMetadata();
      await displayFrame(currentFrame, "full");
      setStatus("평가구간의 마지막 프레임입니다.");
    }
  }

  async function togglePlayback() {
    if (playing) {
      await pausePlayback(true);
    } else {
      await startPlayback();
    }
  }

  async function navigateTo(frame) {
    await pausePlayback(false);
    await displayFrame(clampFrame(frame), "full");
  }

  playPause.addEventListener("click", togglePlayback);
  document.getElementById("goStart").addEventListener("click", async () => {
    await navigateTo(START);
    resetTransform();
  });
  for (const button of document.querySelectorAll("button[data-move]")) {
    button.addEventListener("click", () => {
      navigateTo(currentFrame + Number(button.dataset.move));
    });
  }
  document.getElementById("jumpButton").addEventListener("click", () => {
    const target = Number(jumpInput.value);
    if (!validFrame(target)) {
      setStatus(`${jumpInput.value}은 4196..5994 범위의 짝수 evaluation frame이어야 합니다.`, true);
      return;
    }
    navigateTo(target);
  });
  jumpInput.addEventListener("keydown", event => {
    if (event.key === "Enter") document.getElementById("jumpButton").click();
  });
  document.getElementById("reloadFull").addEventListener("click", () => {
    pausePlayback(false).then(() => displayFrame(currentFrame, "full"));
  });
  document.getElementById("zoomIn").addEventListener("click", () => {
    zoom = Math.min(8, zoom * 1.5);
    applyTransform();
    setStatus(`zoom ${zoom.toFixed(1)}× · 드래그로 화면 이동`);
  });
  document.getElementById("zoomOut").addEventListener("click", () => {
    zoom = Math.max(1, zoom / 1.5);
    if (zoom === 1) { panX = 0; panY = 0; }
    applyTransform();
    setStatus(`zoom ${zoom.toFixed(1)}×`);
  });
  document.getElementById("zoomReset").addEventListener("click", () => {
    resetTransform();
    setStatus("화면 맞춤 · zoom 1.0×");
  });

  viewport.addEventListener("pointerdown", event => {
    if (zoom <= 1) return;
    dragging = true;
    dragStartX = event.clientX - panX;
    dragStartY = event.clientY - panY;
    viewport.classList.add("dragging");
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener("pointermove", event => {
    if (!dragging) return;
    panX = event.clientX - dragStartX;
    panY = event.clientY - dragStartY;
    applyTransform();
  });
  viewport.addEventListener("pointerup", event => {
    dragging = false;
    viewport.classList.remove("dragging");
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
  });

  document.addEventListener("keydown", event => {
    if (event.target === jumpInput) return;
    if (event.code === "Space") {
      event.preventDefault();
      togglePlayback();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      navigateTo(currentFrame - (event.shiftKey ? 30 : STEP));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      navigateTo(currentFrame + (event.shiftKey ? 30 : STEP));
    } else if (event.key === "PageUp") {
      event.preventDefault();
      navigateTo(currentFrame - 150);
    } else if (event.key === "PageDown") {
      event.preventDefault();
      navigateTo(currentFrame + 150);
    }
  });

  updateMetadata();
  displayFrame(START, "full");
</script>
</body>
</html>
"""


def parse_frame_request(path: str, grid: EvaluationGrid) -> tuple[int, str]:
    """Parse and validate a frame API request."""

    parsed = urlparse(path)
    prefix = "/api/frame/"
    if not parsed.path.startswith(prefix):
        raise ValueError("not a frame request")
    raw_frame = parsed.path[len(prefix):]
    try:
        frame_index = int(raw_frame)
    except ValueError as exc:
        raise ValueError("frame index must be an integer") from exc
    if not grid.contains(frame_index):
        raise ValueError(
            f"frame {frame_index} is outside evaluation grid "
            f"{grid.start_frame}..{grid.end_frame} step {grid.frame_step}"
        )
    quality = parse_qs(parsed.query).get("quality", ["full"])[0]
    if quality not in {"play", "full"}:
        raise ValueError("quality must be play or full")
    return frame_index, quality


class BlindGtReviewServer(ThreadingHTTPServer):
    """HTTP server holding one synchronized exact-frame reader."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        reader: FrameReader,
        grid: EvaluationGrid,
    ) -> None:
        super().__init__(server_address, BlindGtReviewHandler)
        self.reader = reader
        self.grid = grid


class BlindGtReviewHandler(BaseHTTPRequestHandler):
    """Serve the fixed review page, health check, and exact source frames."""

    server: BlindGtReviewServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_bytes(
                HTTPStatus.OK,
                PAGE_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        if parsed.path == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "start_frame": self.server.grid.start_frame,
                    "end_frame": self.server.grid.end_frame,
                    "frame_step": self.server.grid.frame_step,
                },
            )
            return
        if parsed.path.startswith("/api/frame/"):
            self._serve_frame()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _serve_frame(self) -> None:
        try:
            frame_index, quality = parse_frame_request(self.path, self.server.grid)
            frame = self.server.reader.read(frame_index)
            if quality == "play":
                height, width = frame.shape[:2]
                display_height = max(1, round(height * PLAYBACK_WIDTH / width))
                frame = cv2.resize(
                    frame,
                    (PLAYBACK_WIDTH, display_height),
                    interpolation=cv2.INTER_AREA,
                )
                jpeg_quality = PLAYBACK_JPEG_QUALITY
            else:
                jpeg_quality = PAUSED_JPEG_QUALITY
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality],
            )
            if not ok:
                raise RuntimeError(f"cannot encode source frame {frame_index}")
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Source-Frame", str(frame_index))
        self.send_header(
            "X-PTS-Seconds",
            f"{self.server.grid.timestamp_seconds(frame_index):.6f}",
        )
        self.end_headers()
        self.wfile.write(encoded.tobytes())

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        self._send_bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_bytes(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, message: str, *args: object) -> None:
        print(f"browser review: {self.address_string()} {message % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the blind GT browser viewer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the local reviewer URL in the default browser",
    )
    parser.add_argument(
        "--box-input",
        action="store_true",
        help="open the manual GT observation box-entry mode",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate canonical GT and observation work files without opening video",
    )
    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="validate work files and summarize skips by object and reason",
    )
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument(
        "--objects-worksheet",
        type=Path,
        default=DEFAULT_OBJECTS_WORKSHEET,
    )
    parser.add_argument(
        "--visibility-worksheet",
        type=Path,
        default=DEFAULT_VISIBILITY_WORKSHEET,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.box_input or args.validate_only or args.skip_summary:
        from apps.demo.gt_box_annotation import run_box_mode

        run_box_mode(args)
        return
    grid = EvaluationGrid()
    warnings = validate_worksheets(
        args.objects_worksheet,
        args.visibility_worksheet,
        grid,
    )
    print_validation(warnings)

    reader = FrameReader(args.video, cache_size=4)
    if (reader.width, reader.height) != (3840, 2160):
        raise SystemExit(
            "blind pilot requires 3840x2160 source frames; got "
            f"{reader.width}x{reader.height}"
        )
    if reader.frame_count <= grid.end_frame:
        raise SystemExit(
            f"video has {reader.frame_count} frames; grid ends at {grid.end_frame}"
        )
    if abs(reader.fps - grid.source_fps) > 1e-3:
        raise SystemExit(
            f"video FPS {reader.fps} does not match expected {grid.source_fps}"
        )

    server = BlindGtReviewServer((args.host, args.port), reader, grid)
    browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    reviewer_url = f"http://{browser_host}:{args.port}"
    print(f"blind GT browser viewer: {reviewer_url}", flush=True)
    if args.open_browser:
        timer = threading.Timer(0.5, webbrowser.open, args=(reviewer_url,))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        reader.close()


if __name__ == "__main__":
    main()
