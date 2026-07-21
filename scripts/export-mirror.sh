#!/usr/bin/env bash
#
# export-mirror.sh — export the open-source tree to the public mirror repo.
#
# The monorepo stays private (its history contains the hub and its security
# design); the public repo only ever receives filtered TREES, never history.
# This script materializes that filter:
#
#   1. Stage an ALLOWLIST of tracked paths from a commit (`git archive` — so
#      untracked files, .venv/, dist/, target/ can never leak by construction).
#   2. Remove the closed/blocked paths inside allowed directories (EXCLUDES).
#   3. Hard-fail if any staged PATH still matches a forbidden pattern.
#   4. Write a content-mention report (informational — the public docs
#      legitimately describe the closed hub companion).
#   5. Secret-scan the staged tree with gitleaks, when installed.
#   6. rsync the staging into the mirror working copy (its .git is preserved)
#      and, with --commit, record the export as a single commit there.
#
# The mirror repo has no remote configured by this script; pushing is always a
# manual, reviewed step.
#
# Usage:
#   scripts/export-mirror.sh                       # stage + sync to ../conecsa-object-detection-public
#   scripts/export-mirror.sh --ref v2026.2 --commit
#   scripts/export-mirror.sh --out /tmp/mirror-check   # dry destination for inspection
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REF="HEAD"
OUT="$REPO_ROOT/../conecsa-object-detection-public"
DO_COMMIT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)    REF="$2"; shift 2 ;;
    --out)    OUT="$2"; shift 2 ;;
    --commit) DO_COMMIT=1; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# ── What is public ────────────────────────────────────────────────────────────
# Everything NOT listed here stays private. Deliberately absent:
#   hub-vision/          — the closed fleet hub (code, icons, tauri config)
#   Cargo.toml/Cargo.lock (root) — workspace whose only member is hub-vision;
#                          system-vision and webcam-server are standalone
#   .github/             — CI runs the hub suites; public CI is authored separately
ALLOWLIST=(
  proto
  i18n
  os-base
  system-vision
  webcam-server
  api-gateway
  inference-service
  training-service
  flow
  scripts
  docs
  yocto
  styles
  docker-compose.yml
  docker-compose.dev.yml
  requirements-dev.txt
  pyrightconfig.json
  README.md
  TRADEMARKS.md
  .gitignore
  .dockerignore
)

# Blocked paths inside allowed directories.
#   Good Times Rg.otf — commercial Typodermic font; its EULA does not allow
#   public redistribution (the @font-face falls back silently). Inter is OFL.
EXCLUDES=(
  "i18n/hub-vision"
  "scripts/build-hub.sh"
  "scripts/build-hub-jetson.sh"
  "system-vision/public/Good Times Rg.otf"
  # Hub deployment glue (weston kiosk wrapper): no hub source, but reveals the
  # closed hub's runtime/KEK details and depends on the excluded
  # build-hub-jetson.sh. conecsa-image.bb installs it conditionally, only when
  # this recipe directory is present in the layer.
  "yocto/meta-conecsa/recipes-conecsa/conecsa-hub-kiosk"
)

# Any staged PATH matching one of these regexes aborts the export. Note that
# docs/services/hub-vision.md is intentionally public (prose describing the
# companion product) and matches none of them.
FORBIDDEN_PATH_PATTERNS=(
  '^hub-vision(/|$)'
  '^i18n/hub-vision(/|$)'
  'src-tauri'
  'build-hub'
  'hub-kiosk'
  'Good Times'
)

# Content mentions worth eyeballing before a push (informational only).
REPORT_TOKENS=(
  'hub-vision'
  'src-tauri'
  'secrets\.bin'
  'Good Times'
)

SHORTSHA="$(git rev-parse --short "$REF")"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/mirror-export.XXXXXX")"
REPORT="$STAGING.report.txt"
echo "==> Exporting $REF ($SHORTSHA) — staging in $STAGING"

# ── 1. Stage the allowlist ──────────────────────────────────────────────────────
# Only pathspecs that exist in the ref are passed to git archive (it errors on
# missing ones); warn about the rest so allowlist drift is visible.
PRESENT=()
for path in "${ALLOWLIST[@]}"; do
  if [[ -n "$(git ls-tree --name-only "$REF" -- "$path")" ]]; then
    PRESENT+=("$path")
  else
    echo "!! allowlist entry not in $REF, skipping: $path"
  fi
done
git archive "$REF" -- "${PRESENT[@]}" | tar -x -C "$STAGING"

# ── 2. Excludes inside allowed directories ─────────────────────────────────────
for path in "${EXCLUDES[@]}"; do
  if [[ -e "$STAGING/$path" ]]; then
    rm -rf "$STAGING/${path:?}"
  else
    echo "!! exclude entry not present (already gone?): $path"
  fi
done

# ── 3. Path gate (hard fail) ───────────────────────────────────────────────────
VIOLATIONS=""
for pattern in "${FORBIDDEN_PATH_PATTERNS[@]}"; do
  matches="$(cd "$STAGING" && find . -mindepth 1 | sed 's|^\./||' | grep -E "$pattern" || true)"
  if [[ -n "$matches" ]]; then
    VIOLATIONS+="${matches}"$'\n'
  fi
done
if [[ -n "$VIOLATIONS" ]]; then
  echo "XX forbidden paths staged — aborting (staging kept for inspection: $STAGING)" >&2
  printf '%s' "$VIOLATIONS" >&2
  exit 1
fi

# ── 4. Content-mention report (informational) ──────────────────────────────────
TOKEN_RE="$(IFS='|'; echo "${REPORT_TOKENS[*]}")"
grep -rInE "$TOKEN_RE" "$STAGING" 2>/dev/null | sed "s|^$STAGING/||" > "$REPORT" || true
MENTIONS="$(wc -l < "$REPORT")"
echo "==> Content mentions of ${REPORT_TOKENS[*]}: $MENTIONS line(s) — review $REPORT"

# ── 5. Secret scan ─────────────────────────────────────────────────────────────
if command -v gitleaks >/dev/null 2>&1; then
  echo "==> gitleaks: scanning staged tree"
  gitleaks detect --no-git --source "$STAGING" --exit-code 1
elif command -v trufflehog >/dev/null 2>&1; then
  echo "==> trufflehog: scanning staged tree"
  trufflehog filesystem --fail "$STAGING" >/dev/null
else
  echo "!! no secret scanner found (gitleaks/trufflehog) — install one before the"
  echo "   first public push; the export itself proceeds."
fi

# ── 6. Sync into the mirror working copy ───────────────────────────────────────
mkdir -p "$OUT"
rsync -a --delete --exclude=/.git "$STAGING"/ "$OUT"/
echo "==> Synced to $OUT"

if [[ "$DO_COMMIT" == "1" ]]; then
  if [[ ! -d "$OUT/.git" ]]; then
    git -C "$OUT" init -b main
    git -C "$OUT" add -A
    git -C "$OUT" commit -m "Initial open-source release (exported from private monorepo @$SHORTSHA)"
    echo "==> Mirror repo initialized with baseline commit"
  elif [[ -n "$(git -C "$OUT" status --porcelain)" ]]; then
    git -C "$OUT" add -A
    git -C "$OUT" commit -m "chore(mirror): export from $SHORTSHA"
    echo "==> Export committed"
  else
    echo "!! mirror is already up to date with $SHORTSHA — nothing to commit"
  fi
fi

rm -rf "$STAGING"
echo ""
echo "Export complete. Push to the public remote is always manual — review first."
