#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input_video="${project_root}/data/raw/before/DJI_0482.MP4"
output_dir="${project_root}/data/clips/validation"
output_video="${output_dir}/DJI_0482_150_210_proxy_720p.mp4"

mkdir -p "${output_dir}"

ffmpeg -hide_banner -loglevel error -y \
  -ss 150 -i "${input_video}" -t 60 \
  -vf "scale=-2:720" -c:v libx264 -preset medium -crf 20 -an \
  -movflags +faststart "${output_video}"

ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,duration \
  -of json "${output_video}"
