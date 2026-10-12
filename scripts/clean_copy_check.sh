#!/usr/bin/env bash
# Reproduce GlucoTwin from a clean copy: only Git-publishable files (tracked + untracked-but-not-ignored), no dataset,
# no artifacts, no local state. Runs the documented commands and logs exit code and duration of each step.
#
#   scripts/clean_copy_check.sh <empty-target-dir> [--cgmacros-from <dir>] [--salt-from <file>]
#
#   --cgmacros-from  copy already-downloaded CGMacros 1.0.0 files instead of `make data-download` (657 MB); they are
#                    still verified against the published SHA256SUMS.txt by `make data`
#   --salt-from      copy a pseudonym salt; needed only to reproduce the team's exact research numbers (fold membership
#                    and row order of gt-nested-2026-10-12-v1 depend on the installation's salted pseudonyms)
# Without --cgmacros-from the recorded-data steps are skipped and the synthetic-only path is checked.
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:?target directory}"; shift
CGM=""; SALT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cgmacros-from) CGM="$2"; shift 2 ;;
    --salt-from) SALT="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ] && { echo "$DEST is not empty" >&2; exit 2; }
mkdir -p "$DEST"
LOG="$DEST/clean_copy_check.log"
(cd "$SRC" && git ls-files -z --cached --others --exclude-standard) | (cd "$SRC" && rsync -a --from0 --files-from=- ./ "$DEST/")
echo "copied $(cd "$DEST" && find . -type f | wc -l | tr -d ' ') files from $SRC" | tee "$LOG"

step() {
  local name="$1"; shift
  local t0=$SECONDS
  (cd "$DEST" && "$@") > "$DEST/step_${name}.out" 2>&1
  local rc=$?
  printf '%-22s exit %s  %4ss  %s\n' "$name" "$rc" "$((SECONDS - t0))" "$(tail -n 1 "$DEST/step_${name}.out" | cut -c1-110)" | tee -a "$LOG"
  return $rc
}

# the salt must be in place before ANY import (ShanghaiT2DM pseudonyms use it too)
if [ -n "$SALT" ]; then mkdir -p "$DEST/data/private" && cp "$SALT" "$DEST/data/private/pseudonym_salt.txt"; fi

step setup make setup
step synthetic make synthetic
step test make test
step test-web make test-web
step e2e make e2e
step data-shanghai make data-shanghai
if [ -n "$CGM" ]; then
  mkdir -p "$DEST/data/raw/cgmacros/1.0.0" && cp "$CGM"/* "$DEST/data/raw/cgmacros/1.0.0/" 2>/dev/null
  step data make data
  step experiment make experiment
  step manifest make manifest
  step research make research
fi
echo "done; per-step output in $DEST/step_*.out" | tee -a "$LOG"
