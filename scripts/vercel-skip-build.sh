#!/usr/bin/env bash
#
# Vercel "Ignored Build Step" for one service.
#
# Usage:  vercel-skip-build.sh <path> [<path> ...]
#
# Exits 0 when NONE of the given paths changed in the last commit, which tells
# Vercel to SKIP the build. Exits 1 to build. That inversion is Vercel's
# convention, not a mistake -- the command answers "should this be ignored?".
#
# Why this exists: the data refresh job commits to main twice a day, touching
# only backend/data/. Nothing the frontend or the API bundle contains changes,
# and the API downloads its snapshot at runtime rather than baking it in, so
# rebuilding on those commits produces a byte-identical deployment.

set -u

root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "not a git checkout; building to be safe"
  exit 1
}
cd "$root" || exit 1

# Vercel clones shallowly, so the parent commit may be absent. Fetch just enough
# to diff against it; if that fails, build rather than risk skipping a real change.
if ! git rev-parse --verify --quiet HEAD^ >/dev/null; then
  git fetch --depth=2 origin "$VERCEL_GIT_COMMIT_REF" >/dev/null 2>&1 || true
fi
if ! git rev-parse --verify --quiet HEAD^ >/dev/null; then
  echo "no parent commit available; building to be safe"
  exit 1
fi

if git diff --quiet HEAD^ HEAD -- "$@"; then
  echo "skip: last commit touched none of: $*"
  exit 0
fi

echo "build: changes under $(git diff --name-only HEAD^ HEAD -- "$@" | head -5 | tr '\n' ' ')"
exit 1
