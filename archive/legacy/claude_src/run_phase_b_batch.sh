#!/usr/bin/env bash
# 개선 전 8편을 29_sahi_bytetrack_pipeline.py로 순차 처리한다.
# 이미 tracks_pixel.csv가 있는 영상은 건너뛴다(중단 후 재실행 시 이어서 진행).
set -uo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

LOG_DIR="runs/before"
mkdir -p "$LOG_DIR"
BATCH_LOG="$LOG_DIR/batch_log.txt"

videos=(record/before/*.MP4 record/before/*.mp4)

echo "=== Phase B 배치 시작: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$BATCH_LOG"

for video in "${videos[@]}"; do
    [ -e "$video" ] || continue
    stem=$(basename "$video")
    stem="${stem%.*}"
    out_dir="runs/before/$stem"
    tracks_csv="$out_dir/tracks_pixel.csv"

    if [ -f "$tracks_csv" ]; then
        echo "[SKIP] $stem - 이미 완료됨 ($tracks_csv 존재)" | tee -a "$BATCH_LOG"
        continue
    fi

    echo "[START] $stem - $(date '+%H:%M:%S')" | tee -a "$BATCH_LOG"
    start_ts=$(date +%s)

    python src/29_sahi_bytetrack_pipeline.py --video "$video" --output-dir "$out_dir" \
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

echo "=== Phase B 배치 종료: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$BATCH_LOG"
