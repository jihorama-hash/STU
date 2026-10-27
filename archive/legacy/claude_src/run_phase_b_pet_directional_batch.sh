#!/usr/bin/env bash
# 25_compute_pet_directional.py(ROI+방향벡터 교차각+차도마스크)를 8편 전체
# (yolo11l+mt0.9+ghost필터 tracks_pixel_filtered.csv)에 적용한다.
# 이미 pet_events_directional.csv가 있는 영상은 건너뛴다.
set -uo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

BASE_DIR="runs/before_l_mt09"
BATCH_LOG="$BASE_DIR/pet_directional_batch_log.txt"

stems=(DJI_0481 DJI_0482 DJI_0483_Cut DJI_0484 DJI_0485 DJI_0486 DJI_0487 DJI_0488)

echo "=== 방향성 PET 배치 시작: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$BATCH_LOG"

for stem in "${stems[@]}"; do
    tracks_csv="$BASE_DIR/$stem/tracks_pixel_filtered.csv"
    out_dir="$BASE_DIR/$stem/pet_directional"
    events_csv="$out_dir/pet_events_directional.csv"

    if [ -f "$events_csv" ]; then
        echo "[SKIP] $stem - 이미 완료됨 ($events_csv 존재)" | tee -a "$BATCH_LOG"
        continue
    fi
    if [ ! -f "$tracks_csv" ]; then
        echo "[FAIL] $stem - tracks not found: $tracks_csv" | tee -a "$BATCH_LOG"
        continue
    fi

    echo "[START] $stem - $(date '+%H:%M:%S')" | tee -a "$BATCH_LOG"
    python src/25_compute_pet_directional.py \
        --tracks "$tracks_csv" --output-dir "$out_dir" --video-id "$stem" \
        >> "$BASE_DIR/${stem}_pet_directional_run.log" 2>&1
    status=$?

    if [ $status -eq 0 ]; then
        echo "[DONE] $stem" | tee -a "$BATCH_LOG"
    else
        echo "[FAIL] $stem - exit code $status, 로그: $BASE_DIR/${stem}_pet_directional_run.log" | tee -a "$BATCH_LOG"
    fi
done

echo "=== 방향성 PET 배치 종료: $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$BATCH_LOG"
