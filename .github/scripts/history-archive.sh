#!/usr/bin/env bash
# The completed-draw archive (data/history.json) lives on the brackets-history Release, and
# two workflows read and write it: the hourly deploy and the manual backfill. This script is
# the only way either one touches it.
#
#   fetch    Download the archive into data/history.json.
#            Exit 0: downloaded. Exit 3: the Release doesn't exist yet (a first run).
#            Exit 1: anything else. A failed download is never read as "no archive yet",
#            because a run that starts from an empty archive uploads an empty archive.
#
#   persist  Merge data/history.json into the archive as it stands on the Release now, then
#            upload the result. The re-read means a run can't overwrite an archive that
#            another workflow uploaded while it was working.
#
# `gh release upload --clobber` deletes the old asset before uploading the new one, so a run
# cancelled or failing in between would leave no archive at all. Every upload therefore goes
# to two assets in turn, history.json and history.prev.json. One of them is always whole, and
# fetch falls back to the second when the first is missing.
set -euo pipefail

TAG=brackets-history
ASSET=history.json
BACKUP=history.prev.json
LOCAL=data/history.json

fetch() {
  mkdir -p data
  local err
  if ! err=$(gh release view "$TAG" --json tagName 2>&1 >/dev/null); then
    if [[ "$err" == *"release not found"* ]]; then
      echo "no $TAG release yet"
      return 3
    fi
    echo "::error::could not read the $TAG release: $err"
    return 1
  fi
  if gh release download "$TAG" --pattern "$ASSET" --output "$LOCAL" --clobber; then
    echo "archive: $(wc -c < "$LOCAL") bytes"
    return 0
  fi
  if gh release download "$TAG" --pattern "$BACKUP" --output "$LOCAL" --clobber; then
    echo "::warning::$ASSET missing from the $TAG release; restored from $BACKUP"
    return 0
  fi
  echo "::error::the $TAG release exists but neither $ASSET nor $BACKUP could be downloaded"
  return 1
}

persist() {
  local ours="${RUNNER_TEMP:-/tmp}/history.ours.json"
  mv "$LOCAL" "$ours"
  local rc=0
  fetch || rc=$?
  if [[ $rc -ne 0 && $rc -ne 3 ]]; then
    mv "$ours" "$LOCAL"
    return 1
  fi
  uv run match-charting-project history merge --from "$ours"

  gh release create "$TAG" --title "Draw history" \
    --notes "Completed draws, accumulated as events finish" 2>/dev/null || true
  local backup="${RUNNER_TEMP:-/tmp}/$BACKUP"
  cp "$LOCAL" "$backup"
  gh release upload "$TAG" "$LOCAL" --clobber
  gh release upload "$TAG" "$backup" --clobber
}

case "${1:-}" in
  fetch) fetch ;;
  persist) persist ;;
  *) echo "usage: $0 fetch|persist" >&2; exit 2 ;;
esac
