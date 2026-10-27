#!/usr/bin/env bash
# runs/before_l_mt09/의 8개 annotated mp4를 촬영 순서(0481~0488)로 이어붙여
# runs/before_l_mt09/combined_annotated.mp4로 만든다. 모두 동일 코덱(mp4v)/해상도
# (3840x2160)/fps(~14.985)로 인코딩돼 있어 재인코딩 없이 concat demuxer로 붙인다.
set -euo pipefail

cd "$(dirname "$0")/.."

OUT_DIR="runs/before_l_mt09"
LIST_FILE="$OUT_DIR/concat_list.txt"
OUTPUT="$OUT_DIR/combined_annotated.mp4"

stems=(DJI_0481 DJI_0482 DJI_0483_Cut DJI_0484 DJI_0485 DJI_0486 DJI_0487 DJI_0488)

: > "$LIST_FILE"
for stem in "${stems[@]}"; do
    f="$OUT_DIR/$stem/${stem}_annotated.mp4"
    if [ ! -f "$f" ]; then
        echo "ERROR: missing $f" >&2
        exit 1
    fi
    echo "file '$(pwd)/$f'" >> "$LIST_FILE"
done

ffmpeg -y -f concat -safe 0 -i "$LIST_FILE" -c copy "$OUTPUT"
echo "Saved: $OUTPUT"
