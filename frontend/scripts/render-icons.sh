#!/usr/bin/env bash
# v65: renders the installed app's icons (static/icons/) from v45.1's favicon art
# (src/lib/assets/favicon.svg). Run it again after changing that art; needs rsvg-convert.
#   icon-<n>.png      the art as is, transparent around the disc ("any")
#   maskable-<n>.png  the art at 75% on the page's own ground (#0a0c0e, --bg-0), so a launcher's
#                     mask (a circle, a squircle) only ever trims the ground: the disc stays
#                     inside the 40%-radius safe zone
#   apple-touch-icon.png  the maskable one at 180px: iOS fills transparency with black
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=src/lib/assets/favicon.svg
OUT=static/icons
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
art=$(sed -e '1d' -e '$d' "$SRC")
cat > "$TMP/maskable.svg" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" fill="#0a0c0e"/>
  <g transform="translate(32 32) scale(0.75) translate(-32 -32)">
$art
  </g>
</svg>
SVG
for n in 192 512; do
	rsvg-convert -w "$n" -h "$n" "$SRC" -o "$OUT/icon-$n.png"
	rsvg-convert -w "$n" -h "$n" "$TMP/maskable.svg" -o "$OUT/maskable-$n.png"
done
rsvg-convert -w 180 -h 180 "$TMP/maskable.svg" -o "$OUT/apple-touch-icon.png"
