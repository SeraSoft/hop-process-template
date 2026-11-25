#!/usr/bin/env bash
# Checks the template-owned files of a Hop project: run from the project root,
# by its CI or by hand. Fails if a file listed in SERASOFT_MANIFEST.sha256 was
# modified or removed, if src/template/ or db/liquibase/ hold a file or symlink
# not listed there (or are themselves symlinks), or if SERASOFT_VERSION is
# missing or empty. The SQLite seed files (db/sqlite/data/) are not checked.
# These files come from SeraSoft/hop-process-template via tools/serasoft-sync.sh:
# change them in the template, never here (README.md, "Template updates").
set -euo pipefail

MANIFEST=SERASOFT_MANIFEST.sha256
OWNED_DIRS=(src/template db/liquibase)

[[ $# -eq 0 ]] || { echo "usage: tools/serasoft-verify.sh (from the project root)" >&2; exit 64; }
[[ -f "$MANIFEST" ]] || { echo "ERROR: $MANIFEST not found: run from the project root" >&2; exit 66; }

failed=0

# --strict: an improperly formatted line fails instead of being skipped.
if ! check="$(sha256sum --check --strict "$MANIFEST" 2>&1)"; then
  echo "ERROR: template files modified or removed:" >&2
  grep -v ': OK$' <<<"$check" >&2 || true
  failed=1
  # A Windows checkout with core.autocrlf=true writes CRLF: say so instead of a list of FAILED
  crlf="$(grep -lU $'\r' "$MANIFEST" 2>/dev/null || true)"
  while IFS= read -r f; do
    if [[ -f "$f" ]] && grep -qU $'\r' "$f"; then crlf+="${crlf:+ }$f"; break; fi
  done < <(sed -E 's/^[0-9a-f]{64} [ *]//; s/\r$//' "$MANIFEST")
  if [[ -n "$crlf" ]]; then
    echo "ERROR: CRLF line endings in the template files (e.g. $crlf): a Windows checkout with core.autocrlf=true; run 'git config core.autocrlf input' (or add a .gitattributes with '* text=auto eol=lf') and check the files out again (README, \"Template updates on Windows: line endings\")" >&2
  fi
fi

for dir in "${OWNED_DIRS[@]}"; do
  if [[ -L "$dir" ]]; then
    echo "ERROR: $dir is a symlink, not the template directory" >&2
    failed=1
  fi
done

# sha256sum accepts CRLF lines: strip the \r here too.
listed="$(sed -E 's/^[0-9a-f]{64} [ *]//; s/\r$//' "$MANIFEST" | LC_ALL=C sort)"
present="$( { find "${OWNED_DIRS[@]}" ! -type d 2>/dev/null || true; } | LC_ALL=C sort)"
extra="$(LC_ALL=C comm -13 <(printf '%s\n' "$listed") <(printf '%s\n' "$present") | sed '/^$/d')"
if [[ -n "$extra" ]]; then
  echo "ERROR: files not from the template in ${OWNED_DIRS[*]}:" >&2
  printf '%s\n' "$extra" >&2
  failed=1
fi

version="$(head -n1 SERASOFT_VERSION 2>/dev/null || true)"
version="${version%$'\r'}"
if [[ -z "${version//[[:space:]]/}" ]]; then
  echo "ERROR: SERASOFT_VERSION missing or empty: run tools/serasoft-sync.sh" >&2
  failed=1
fi

[[ "$failed" -eq 0 ]] || exit 1
echo "OK serasoft-verify version=${version%% *} files=$(grep -c . "$MANIFEST")"
