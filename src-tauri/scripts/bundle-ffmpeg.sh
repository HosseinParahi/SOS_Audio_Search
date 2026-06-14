#!/usr/bin/env bash
# Bundle the system (Homebrew) ffmpeg + ffprobe and all their non-system dylibs into
# src-tauri/resources/bin, rewriting load paths to @executable_path/libs so the binaries run
# from inside the .app with nothing from the host. Keeps everything arm64 from the user's own
# trusted ffmpeg — no third-party static download.
#
# Requires: dylibbundler (brew install dylibbundler).
# Run from anywhere:  src-tauri/scripts/bundle-ffmpeg.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$REPO/src-tauri/resources/bin"

FFMPEG="$(command -v ffmpeg)"
FFPROBE="$(command -v ffprobe)"
echo "==> source: $FFMPEG / $FFPROBE"

for b in "$FFMPEG" "$FFPROBE"; do
  if [ "$(lipo -archs "$b" 2>/dev/null)" != "arm64" ] && ! lipo -archs "$b" 2>/dev/null | grep -q arm64; then
    echo "ERROR: $b is not arm64"; exit 1
  fi
done

echo "==> staging copies in $BIN"
rm -rf "$BIN"
mkdir -p "$BIN"
cp "$FFMPEG" "$BIN/ffmpeg"
cp "$FFPROBE" "$BIN/ffprobe"
chmod u+w "$BIN/ffmpeg" "$BIN/ffprobe"

echo "==> gathering + rewriting dylibs with dylibbundler"
# -p @executable_path/libs/ works for both executables AND lib->lib references, since
# @executable_path always resolves to the running ffmpeg/ffprobe's dir (=resources/bin).
dylibbundler -of -b -cd \
  -x "$BIN/ffmpeg" \
  -x "$BIN/ffprobe" \
  -d "$BIN/libs" \
  -p @executable_path/libs/

echo "==> ad-hoc re-signing (install_name_tool invalidated the signatures)"
while IFS= read -r f; do codesign -f -s - "$f"; done < <(printf '%s\n' "$BIN/ffmpeg" "$BIN/ffprobe"; find "$BIN/libs" -name '*.dylib')

echo "==> verifying no host paths leak"
if otool -L "$BIN/ffmpeg" "$BIN/ffprobe" | grep -E "/homebrew/|/opt/|Cellar"; then
  echo "ERROR: host dylib path still referenced"; exit 1
fi

echo "==> functional smoke test"
"$BIN/ffmpeg" -hide_banner -version | head -1
"$BIN/ffprobe" -hide_banner -version | head -1

echo "==> done. size:"
du -sh "$BIN"
