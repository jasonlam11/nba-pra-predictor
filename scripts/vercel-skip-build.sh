#!/usr/bin/env bash
#
# Vercel "Ignored Build Step".
#
# Usage:  vercel-skip-build.sh [<path> ...]
#
# With no arguments it uses WATCHED below. The list lives here rather than in
# the Vercel setting because that field caps at 256 characters, and because a
# versioned list with comments is easier to keep correct than a dashboard
# string.
#
# Exits 0 when NONE of the given paths changed, telling Vercel to SKIP the
# build. Exits 1 to build. That inversion is Vercel's convention, not a
# mistake -- the command answers "should this be ignored?".
#
# Why this exists: the data refresh job commits to main twice a day, touching
# only backend/data/. Nothing either service ships changes -- the frontend does
# not read those files and the API downloads its snapshot at runtime rather
# than baking it in -- so rebuilding produces an identical deployment.
#
# NOTE: this must be configured as the PROJECT-level Ignored Build Step.
# `ignoreCommand` inside a `services` entry is documented but was observed to
# have no effect (Services is in beta): a data-only commit still triggered a
# full build with no trace of this script in the logs.

set -u

# Everything either service actually ships. Deliberately excludes
# backend/data/ -- that is what the twice-daily refresh writes, and neither
# service reads it at build time: the API fetches its snapshot at runtime.
WATCHED=(
  src public package.json package-lock.json
  next.config.ts tsconfig.json postcss.config.js tailwind.config.js
  eslint.config.mjs .env.production vercel.json
  backend/app backend/vercel_app.py backend/requirements.txt
  backend/.python-version scripts/vercel-skip-build.sh
)
[ "$#" -gt 0 ] && WATCHED=("$@")

echo "[vercel-skip-build] evaluating ${#WATCHED[@]} paths"

root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "[vercel-skip-build] not a git checkout -> build"
  exit 1
}
cd "$root" || exit 1

# Diff against the commit of the PREVIOUS DEPLOYMENT, not HEAD^.
#
# A push can contain several commits. Comparing only the last one against its
# parent means a push whose final commit is data-only would skip the build even
# though earlier commits in the same push changed real code. VERCEL_GIT_PREVIOUS_SHA
# is the commit that was last deployed, so it covers the whole range.
base="${VERCEL_GIT_PREVIOUS_SHA:-}"

if [ -n "$base" ] && ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
  # Vercel clones shallowly, so that commit may be absent. Try to fetch it.
  git fetch --depth=50 origin "$base" >/dev/null 2>&1 \
    || git fetch --unshallow >/dev/null 2>&1 || true
fi

if [ -z "$base" ] || ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
  # First deployment, or the previous commit is unreachable. Fall back to the
  # parent, and if even that is missing, build rather than guess.
  if git rev-parse --verify --quiet HEAD^ >/dev/null; then
    base=$(git rev-parse HEAD^)
    echo "[vercel-skip-build] no usable VERCEL_GIT_PREVIOUS_SHA; comparing against HEAD^"
  else
    echo "[vercel-skip-build] no comparable base -> build"
    exit 1
  fi
fi

if git diff --quiet "$base" HEAD -- "${WATCHED[@]}"; then
  echo "[vercel-skip-build] no changes in watched paths since ${base:0:7} -> SKIP"
  exit 0
fi

echo "[vercel-skip-build] changed: $(git diff --name-only "$base" HEAD -- "${WATCHED[@]}" | head -5 | tr '\n' ' ') -> BUILD"
exit 1
