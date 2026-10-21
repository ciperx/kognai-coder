#!/bin/bash
# WURK product film — headless render on the VPS.
# Two 450-frame halves render in parallel, are concatenated, then muxed with the
# procedurally generated soundtrack.
set -uo pipefail
cd /home/agentuser/wurk-video || exit 1

ENC="-c:v libx264 -preset medium -crf 17 -pix_fmt yuv420p -profile:v high -level 4.1 -g 60 -threads 2"

echo "[$(date -Is)] audio"
python3 gen_audio.py soundtrack.wav || exit 1

echo "[$(date -Is)] render half 0"
( python3 render_wurk.py --frames 450 --start 0.0 --out - 2>half0.log \
  | ffmpeg -y -hide_banner -loglevel warning -f rawvideo -pix_fmt rgb24 -s 1920x1080 -r 30 -i - $ENC -an seg0.mp4 ) &
P0=$!
echo "[$(date -Is)] render half 1"
( python3 render_wurk.py --frames 450 --start 15.0 --out - 2>half1.log \
  | ffmpeg -y -hide_banner -loglevel warning -f rawvideo -pix_fmt rgb24 -s 1920x1080 -r 30 -i - $ENC -an seg1.mp4 ) &
P1=$!
wait $P0; R0=$?
wait $P1; R1=$?
echo "[$(date -Is)] halves done rc=$R0/$R1"
[ $R0 -eq 0 ] && [ $R1 -eq 0 ] || { echo "RENDER FAILED"; exit 1; }

printf "file 'seg0.mp4'\nfile 'seg1.mp4'\n" > list.txt
echo "[$(date -Is)] concat"
ffmpeg -y -hide_banner -loglevel warning -f concat -safe 0 -i list.txt -c copy -an body.mp4 || exit 1

echo "[$(date -Is)] mux audio"
ffmpeg -y -hide_banner -loglevel warning -i body.mp4 -i soundtrack.wav \
  -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart wurk-product.mp4 || exit 1

ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate \
  -of default=nw=1 wurk-product.mp4
echo "[$(date -Is)] DONE $(stat -c%s wurk-product.mp4) bytes"
