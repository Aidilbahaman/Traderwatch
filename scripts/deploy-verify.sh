#!/usr/bin/env bash
# deploy-verify.sh — prove GitHub Pages is serving the bytes you just pushed.
#
# A successful `git push` says nothing about the CDN. This script re-fetches the
# live file with a cache-busting query until the new markers appear, then reports
# PASS/FAIL with the attempt count.
#
# Usage:
#   ./scripts/deploy-verify.sh members.html --marker 'range: "12M"' --marker 'height:600px'
#   ./scripts/deploy-verify.sh assets/js/tw-fundamental-news.js --marker importanceFilter
#   ./scripts/deploy-verify.sh members.html --marker 'newThing' --absent 'oldThing'
#   ./scripts/deploy-verify.sh members.html --marker x --attempts 12 --delay 15
#   ./scripts/deploy-verify.sh --git          # only check HEAD is on origin/main
#
# Exit codes: 0 = verified, 1 = markers missing, 2 = usage/config error.
set -uo pipefail

SITE="${SITE:-https://aidilbahaman.github.io/Traderwatch}"
ATTEMPTS="${ATTEMPTS:-10}"
DELAY="${DELAY:-12}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

path=""
declare -a markers=()
declare -a absents=()
git_only=0
quiet=0

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --marker)  markers+=("${2:-}"); shift 2 ;;
    --absent)  absents+=("${2:-}"); shift 2 ;;
    --attempts) ATTEMPTS="${2:-}"; shift 2 ;;
    --delay)   DELAY="${2:-}"; shift 2 ;;
    --git)     git_only=1; shift ;;
    --quiet)   quiet=1; shift ;;
    -h|--help) usage ;;
    -*)        echo "unknown flag: $1" >&2; exit 2 ;;
    *)         path="$1"; shift ;;
  esac
done

# ---------- git check ----------
git_check() {
  cd "$REPO" || return 1
  local branch head remote
  branch="$(git rev-parse --abbrev-ref HEAD)"
  head="$(git rev-parse HEAD)"
  remote="$(git ls-remote origin "refs/heads/$branch" | awk '{print $1}')"
  echo "branch: $branch"
  echo "local : ${head:0:7}"
  echo "remote: ${remote:0:7}"
  if [ "$head" = "$remote" ]; then
    echo "GIT: PASS (HEAD is pushed)"
    return 0
  fi
  echo "GIT: FAIL (local HEAD is not on origin/$branch)" >&2
  return 1
}

if [ "$git_only" = "1" ]; then
  git_check
  exit $?
fi

# ---------- validation ----------
if [ -z "$path" ]; then
  echo "error: no path given" >&2
  usage
fi
if [ "${#markers[@]}" -eq 0 ]; then
  echo "error: give at least one --marker" >&2
  usage
fi
if ! [[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || [ "$ATTEMPTS" -lt 1 ]; then
  echo "error: --attempts must be a positive integer" >&2
  exit 2
fi
if ! [[ "$DELAY" =~ ^[0-9]+$ ]]; then
  echo "error: --delay must be an integer (seconds)" >&2
  exit 2
fi

url="${SITE%/}/${path#/}"
echo "target: $url"
echo "checks: ${#markers[@]} marker(s), ${#absents[@]} absent(s), up to $ATTEMPTS attempt(s)"
echo

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT

attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
  # unique query per attempt so no cache layer can answer from the previous one
  cb="$(date +%s%N)"
  case "$url" in
    *\?*) fetch="${url}&cb=${cb}" ;;
    *)    fetch="${url}?cb=${cb}" ;;
  esac

  http="$(curl -sS -o "$body_file" -w '%{http_code}' --max-time 25 "$fetch" 2>/dev/null || echo 000)"
  missing=0
  present=0

  for m in "${markers[@]}"; do
    if grep -qF -- "$m" "$body_file"; then
      present=$((present + 1))
    else
      missing=$((missing + 1))
    fi
  done
  leaked=0
  for a in "${absents[@]}"; do
    if grep -qF -- "$a" "$body_file"; then leaked=$((leaked + 1)); fi
  done

  if [ "$http" = "200" ] && [ "$missing" -eq 0 ] && [ "$leaked" -eq 0 ]; then
    echo "attempt $attempt: HTTP $http, all markers present"
    if [ "$quiet" = "0" ]; then
      for m in "${markers[@]}"; do echo "  found: $m"; done
      for a in "${absents[@]}"; do echo "  gone : $a"; done
    fi
    echo
    echo "DEPLOY: PASS (after $attempt attempt(s))"
    exit 0
  fi

  echo "attempt $attempt: HTTP $http, ${present}/${#markers[@]} markers, ${leaked} stale"
  attempt=$((attempt + 1))
  [ "$attempt" -le "$ATTEMPTS" ] && sleep "$DELAY"
done

echo
echo "DEPLOY: FAIL — markers never appeared after $ATTEMPTS attempts" >&2
for m in "${markers[@]}"; do
  grep -qF -- "$m" "$body_file" || echo "  missing: $m" >&2
done
for a in "${absents[@]}"; do
  grep -qF -- "$a" "$body_file" && echo "  still present: $a" >&2
done
echo "last response saved for inspection: $body_file" >&2
trap - EXIT
exit 1
