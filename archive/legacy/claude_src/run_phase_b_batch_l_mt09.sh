#!/usr/bin/env bash
# 개선 전 8편을 yolo11l + matching-threshold 0.9로 재처리한다 (분절 최소화 설정,
# PHASE_B_DAY2_PLAN.md 2.1절 결과 채택). 09_사이핀라인과 동일하나 모델/임계값만 다름.
# annotated mp4도 함께 생성한다. 이미 <stem>_annotated.mp4가 있는 영상은 건너뛴다.
set -uo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG_DIR="runs/before_l_mt09"
mkdir -p "$LOG_DIR"
BATCH_LOG="$LOG_DIR/batch_log.txt"

videos=(record/before/*.MP4 record/before/*.mp4)

echo "=== Phase B (yolo11l, mt=0.9) 배치 시작: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$BATCH_LOG"

for video in "${videos[@]}"; do
    [ -e "$video" ] || continue
    stem=$(basename "$video")
    stem="${stem%.*}"
    out_dir="runs/before_l_mt09/$stem"
    annotated_video="$out_dir/${stem}_annotated.mp4"

    if [ -f "$annotated_video" ]; then
        echo "[SKIP] $stem - 이미 완료됨 ($annotated_video 존재)" | tee -a "$BATCH_LOG"
        continue
    fi

    echo "[START] $stem - $(date '+%H:%M:%S')" | tee -a "$BATCH_LOG"
    start_ts=$(date +%s)

    python src/29_sahi_bytetrack_pipeline.py --video "$video" --output-dir "$out_dir" \
        --model models/yolo11l.pt --matching-threshold 0.9 --save-video \
        >> "$LOG_DIR/${stem}_run.log" 2>&1
    status=$?

    end_ts=$(date +%s)
    elapsed=$((end_ts - start_ts))

    if [ $status -eq 0 ]; then
        echo "[DONE] $stem - ${elapsed}s 소요" | tee -a "$BATCH_LOG"
    else
        echo "[FAIL] $stem - exit code $status, 로그: $LOG_DIR/${stem}_run.log" | tee -a "$BATCH_LOG"
    fi
done

echo "=== Phase B (yolo11l, mt=0.9) 배치 종료: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$BATCH_LOG"
