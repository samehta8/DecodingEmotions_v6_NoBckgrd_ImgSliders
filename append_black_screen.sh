#!/bin/bash

# Script to prepend a 0.5-second black screen and append a 1-second black screen to each video

# ===== CONFIGURATION PATHS =====
# Input directory containing videos to process
INPUT_DIR="../data_saumya/data_study4-c/Study-4c-video-set-2/"

# Output directory for processed videos
OUTPUT_DIR="../data_saumya/data_study4-c/processed-videos/videos-set-2/"
# ===============================

if ! command -v ffmpeg &> /dev/null; then
    echo "Error: ffmpeg is not installed. Please install it first."
    exit 1
fi

if [ ! -d "$INPUT_DIR" ]; then
    echo "Error: Input directory not found: $INPUT_DIR"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
count=0

for video in "$INPUT_DIR"/*.{mp4,MP4,avi,AVI,mov,MOV,mkv,MKV}; do
    [ -e "$video" ] || continue

    filename=$(basename "$video")
    filename_no_ext="${filename%.*}"
    extension="${filename##*.}"
    output="$OUTPUT_DIR/${filename_no_ext}.${extension}"

    echo "Processing: $filename"

    width=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$video")
    height=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$video")
    fps=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$video")
    has_audio=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "$video")

    # Use the concat filter (not the concat demuxer) so all inputs are decoded first.
    # This avoids frozen-frame and black-screen artifacts caused by codec/format
    # mismatches between the source video and the independently-generated black clips.
    if [ -n "$has_audio" ]; then
        ffmpeg -y \
            -f lavfi -i "color=c=black:s=${width}x${height}:r=${fps}:d=0.5" \
            -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
            -i "$video" \
            -f lavfi -i "color=c=black:s=${width}x${height}:r=${fps}:d=1" \
            -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
            -filter_complex \
"[0:v]format=yuv420p,setpts=PTS-STARTPTS[v0];\
[1:a]atrim=duration=0.5,aformat=sample_rates=44100:channel_layouts=stereo,asetpts=PTS-STARTPTS[a0];\
[2:v]scale=${width}:${height},format=yuv420p,setpts=PTS-STARTPTS[v1];\
[2:a]aformat=sample_rates=44100:channel_layouts=stereo,asetpts=PTS-STARTPTS[a1];\
[3:v]format=yuv420p,setpts=PTS-STARTPTS[v2];\
[4:a]atrim=duration=1,aformat=sample_rates=44100:channel_layouts=stereo,asetpts=PTS-STARTPTS[a2];\
[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]" \
            -map "[outv]" -map "[outa]" \
            -c:v libx264 -pix_fmt yuv420p -c:a aac \
            "$output"
    else
        ffmpeg -y \
            -f lavfi -i "color=c=black:s=${width}x${height}:r=${fps}:d=0.5" \
            -i "$video" \
            -f lavfi -i "color=c=black:s=${width}x${height}:r=${fps}:d=1" \
            -filter_complex \
"[0:v]format=yuv420p,setpts=PTS-STARTPTS[v0];\
[1:v]scale=${width}:${height},format=yuv420p,setpts=PTS-STARTPTS[v1];\
[2:v]format=yuv420p,setpts=PTS-STARTPTS[v2];\
[v0][v1][v2]concat=n=3:v=1:a=0[outv]" \
            -map "[outv]" \
            -c:v libx264 -pix_fmt yuv420p -an \
            "$output"
    fi

    if [ $? -eq 0 ]; then
        echo "✓ Saved to: $output"
        ((count++))
    else
        echo "✗ Failed: $filename"
    fi
done

echo ""
echo "Processed $count video(s)"
echo "Output files are in: $OUTPUT_DIR"
