#!/usr/bin/env bash
# Obfuscate client-facing JS into dist/ so the shipped bundle is hard to read.
# Source files in the repo stay readable for us; only dist/ is served publicly.
# Usage: bash scripts/build-obfuscated.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="dist"
mkdir -p "$OUT"

OBF="javascript-obfuscator"
command -v "$OBF" >/dev/null 2>&1 || { echo "javascript-obfuscator not installed"; exit 1; }

# Balanced settings: strong enough to deter reading, safe for browser JS.
# (controlFlowFlattening is heavy; keep it off for performance on mobile.)
OBF_ARGS=(
  --compact true
  --identifier-names-generator hexadecimal
  --string-array true
  --string-array-rotate true
  --string-array-shuffle true
  --string-array-threshold 0.75
  --split-strings true
  --split-strings-chunk-length 8
  --string-array-encoding base64
  --self-defending true
  --disable-console-output false
  --target browser
)

for f in pwa.js common.js sound.js bridge-banner.js; do
  [ -f "$f" ] || continue
  "$OBF" "$f" --output "$OUT/$f" "${OBF_ARGS[@]}" \
    && echo "obfuscated $f ($(wc -c < "$f") -> $(wc -c < "$OUT/$f") bytes)"
done

# config.js holds no secrets (public keys only) but keep it readable for the
# owner to edit; copy as-is.
[ -f config.js ] && cp config.js "$OUT/config.js" && echo "copied config.js"

# member/app.js is the heaviest logic; obfuscate it too.
if [ -f member/app.js ]; then
  mkdir -p "$OUT/member"
  "$OBF" member/app.js --output "$OUT/member/app.js" "${OBF_ARGS[@]}" \
    && echo "obfuscated member/app.js"
fi
[ -f member/auth.js ] && cp member/auth.js "$OUT/member/auth.js" && echo "copied member/auth.js"

echo ""
echo "Done. dist/ contents:"
find "$OUT" -type f -name "*.js" -printf "  %p (%s bytes)\n"
