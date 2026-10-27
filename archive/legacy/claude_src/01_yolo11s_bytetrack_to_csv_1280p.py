
from _paths import BASE
from ultralytics import YOLO
import cv2
import pandas as pd
from pathlib import Path

# =========================
# 1. 경로 설정
# =========================
BASE_DIR = BASE
# yolo11m.pt가 로컬에 없으면 Ultralytics가 첫 실행 시 자동으로 다운로드합니다.
MODEL_PATH = "yolo11m.pt"
VIDEO_PATH = BASE_DIR / "record" / "DJI_0477_yolo_1280p.mp4"
RUN_NAME = "DJI_0477_yolo11m_1280p"
OUTPUT_CSV = BASE_DIR / "runs" / f"{RUN_NAME}_tracks_pixel.csv"

OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

# =========================
# 2. YOLO 모델 로드
# =========================
model = YOLO(str(MODEL_PATH))

# =========================
# 3. 영상 FPS 확인
# =========================
cap = cv2.VideoCapture(str(VIDEO_PATH))
fps = cap.get(cv2.CAP_PROP_FPS)
cap.release()

print(f"Video FPS: {fps}")

# =========================
# 4. 분석 대상 class 설정
# COCO class 기준
# person=0, bicycle=1, car=2, motorcycle=3, bus=5, truck=7
# =========================
TARGET_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

rows = []

# =========================
# 5. YOLO + ByteTrack 실행
# =========================
results = model.track(
    source=str(VIDEO_PATH),
    tracker="bytetrack.yaml",
    persist=True,
    stream=True,
    conf=0.25,
    iou=0.5,
    classes=list(TARGET_CLASSES.keys()),
    verbose=True,
    show=True,
    save=True,
    project=str(BASE_DIR / "runs" / "detect"),
    name=RUN_NAME,
    exist_ok=False,
)

# =========================
# 6. Frame별 결과 저장
# =========================
for frame_id, r in enumerate(results):
    time_sec = frame_id / fps

    if r.boxes is None:
        continue

    boxes = r.boxes

    if boxes.id is None:
        continue

    xyxy = boxes.xyxy.cpu().numpy()
    ids = boxes.id.cpu().numpy().astype(int)
    cls = boxes.cls.cpu().numpy().astype(int)
    confs = boxes.conf.cpu().numpy()

    for box, track_id, class_id, conf in zip(xyxy, ids, cls, confs):
        if class_id not in TARGET_CLASSES:
            continue

        x1, y1, x2, y2 = box

        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        # Drone footage is usually top-down or high-angle, so use the bbox center
        # as the object's representative image position.
        anchor_x = cx
        anchor_y = cy

        rows.append({
            "frame_id": frame_id,
            "time_sec": time_sec,
            "track_id": track_id,
            "class_id": class_id,
            "class_name": TARGET_CLASSES[class_id],
            "confidence": conf,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "cx": cx,
            "cy": cy,
            "anchor_x": anchor_x,
            "anchor_y": anchor_y,
            "anchor_type": "bbox_center",
            "foot_x": anchor_x,
            "foot_y": anchor_y,
        })

df = pd.DataFrame(rows)
df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

print(f"Saved: {OUTPUT_CSV}")
print(df.head())
print(f"Total rows: {len(df)}")
