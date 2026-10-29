#!/bin/bash
# wt-attached-helper.sh — 2026-10-29 Phase 3 remediation.
#
# Convenience wrapper to create a new git worktree on the attached
# volume instead of /home/autobot/tradingbot-wt/ (which is on the root
# filesystem and currently holds 114 worktrees totalling 6.3 GB).
#
# Existing /home/autobot/tradingbot-wt/* worktrees are UNCHANGED by
# this helper. It only affects NEW worktrees created via this wrapper.
#
# Usage:
#   wt-attached-helper.sh <branch-or-ref> <worktree-name>
#     e.g. wt-attached-helper.sh origin/main scenario-v2-c5-20261101
#
# Equivalent to:
#   git -C /opt/tradingbot worktree add -b feat/<name> \
#     /mnt/volume_lon1_1778405456698/worktrees/<name> <ref>
#
# Operator-side workflow for Claude Code sessions:
#
#   1. For a session that would normally run EnterWorktree in
#      /opt/tradingbot/.claude/worktrees/, instead:
#        $ ./wt-attached-helper.sh origin/main my-work
#        $ cd /mnt/volume_lon1_1778405456698/worktrees/my-work
#        $ claude    # launches Claude Code with CWD on the attached vol
#
#   2. The resulting worktree is a normal git worktree registered to
#      /opt/tradingbot/.git/worktrees/<name>. git worktree list will
#      show it alongside the existing ones. git worktree remove works
#      normally.
#
#   3. Future Phase 3+ refinement: a `worktree.basePath` entry in
#      ~/.claude/settings.json or a project CLAUDE.md directive can
#      make EnterWorktree default to this location — subject to the
#      Claude Code harness supporting the setting. See the Phase 3
#      remediation report for the open question.

set -euo pipefail

REF=${1:-}
NAME=${2:-}
BASE=/mnt/volume_lon1_1778405456698/worktrees
REPO=/opt/tradingbot

if [[ -z "$REF" || -z "$NAME" ]]; then
    echo "usage: $0 <ref> <worktree-name>" >&2
    exit 1
fi

mkdir -p "$BASE"

# Branch naming convention: "feat/<name>" per operator convention,
# but allow explicit branch name via a leading "@" prefix in NAME.
if [[ "$NAME" == @* ]]; then
    BRANCH="${NAME#@}"
    DIR="$BASE/${BRANCH//\//-}"
else
    BRANCH="feat/$NAME"
    DIR="$BASE/$NAME"
fi

if [[ -e "$DIR" ]]; then
    echo "ERROR: $DIR already exists" >&2
    exit 1
fi

echo "Creating worktree:"
echo "  repo:   $REPO"
echo "  ref:    $REF"
echo "  branch: $BRANCH"
echo "  dir:    $DIR"
echo

git -C "$REPO" worktree add -b "$BRANCH" "$DIR" "$REF"

echo
echo "Done. Enter the worktree with:"
echo "  cd $DIR"
