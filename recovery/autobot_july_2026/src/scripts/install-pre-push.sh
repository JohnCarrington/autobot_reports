#!/usr/bin/env bash
# Install the pre-push static-analysis hook into .git/hooks/pre-push.
# Run once after a fresh clone:  ./scripts/install-pre-push.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_SRC="$REPO_ROOT/scripts/pre-push.hook"
HOOK_DST="$REPO_ROOT/.git/hooks/pre-push"

if [[ ! -f "$HOOK_SRC" ]]; then
    echo "install-pre-push: missing $HOOK_SRC" >&2
    exit 1
fi

mkdir -p "$(dirname "$HOOK_DST")"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "Installed pre-push hook → $HOOK_DST"
echo "It will now block git push on pyflakes undefined names / unbound locals"
echo "and on any pylint -E error in files changed by the push."
