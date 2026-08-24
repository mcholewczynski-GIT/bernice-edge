#!/bin/bash
INPUT_PATH="$1"
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --output_dir) OUTPUT_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

TMPFILE=$(mktemp /tmp/stt-XXXXXX.wav)
ffmpeg -y -i "$INPUT_PATH" -ar 48000 -ac 1 -f wav "$TMPFILE" -loglevel quiet 2>/dev/null
RESULT=$(/home/admin/nemo-env/bin/python3 /home/admin/bernice-stt-cmd-client.py "$TMPFILE")
rm -f "$TMPFILE"

if [ -n "$OUTPUT_DIR" ]; then
    BASENAME=$(basename "$INPUT_PATH" | sed 's/\.[^.]*$//')
    echo "$RESULT" > "$OUTPUT_DIR/${BASENAME}.txt"
fi
echo "$RESULT"
