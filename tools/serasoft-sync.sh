#!/usr/bin/env bash
# Copies the template-owned files of hop-process-template, as of an annotated
# release tag, into a Hop project repository, and rewrites SERASOFT_VERSION and
# SERASOFT_MANIFEST.sha256 there. Run from a checkout of hop-process-template
# that has the tag. It does not commit: review the diff, commit, open the PR/MR
# (README.md, "Template updates").
#
# Usage: tools/serasoft-sync.sh --tag <X.Y.Z> --dest <project repository>
set -euo pipefail

MANIFEST=SERASOFT_MANIFEST.sha256
SEEDS=(db/sqlite/data/integrations_db db/sqlite/data/integrations_db.config db/sqlite/data/integrations_db.logs)
LIQUIBASE=db/liquibase/master.xml

usage() {
  echo "usage: tools/serasoft-sync.sh --tag <X.Y.Z> --dest <project repository>" >&2
  exit 64
}
die() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARNING: $*" >&2; }

tag="" dest=""
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --tag)  tag="$2" ;;
    --dest) dest="$2" ;;
    *)      usage ;;
  esac
  shift 2
done
[[ -n "$tag" && -n "$dest" ]] || usage

unset CDPATH
upstream="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
commit="$(git -C "$upstream" rev-parse --verify --quiet "refs/tags/$tag^{commit}")" \
  || die "tag $tag not found in $upstream (git fetch --tags?)"
[[ "$(git -C "$upstream" cat-file -t "refs/tags/$tag")" == tag ]] \
  || die "tag $tag is not annotated (release notes are in the annotated tag message)"

[[ -d "$dest" ]] || die "$dest is not a directory"
dest="$(cd "$dest" && pwd -P)"
[[ "$(git -C "$dest" rev-parse --show-toplevel 2>/dev/null)" == "$dest" ]] \
  || die "$dest is not the root of a Git work tree"
[[ "$dest" != "$(cd "$upstream" && pwd -P)" ]] || die "--dest is the template itself"
[[ -z "$(git -C "$dest" status --porcelain)" ]] || die "$dest has uncommitted changes"

# Template-owned paths, as named in the project (spec A3, "Ownership").
owned_path() {
  [[ "/$1/" != */../* && "$1" != */ ]] || return 1
  case "$1" in
    main.hwf|tools/serasoft-verify.sh) return 0 ;;
    src/template/*|db/liquibase/*) return 0 ;;
    config/template-*.json) [[ "$1" != config/*/* ]] ;;
    metadata/rdbms/integrations_db_*.json) [[ "$1" != metadata/rdbms/*/* ]] ;;
    metadata/workflow-log/workflow_log.json) return 0 ;;
    metadata/pipeline-run-configuration/local.json) return 0 ;;
    metadata/workflow-run-configuration/local.json) return 0 ;;
    *) return 1 ;;
  esac
}
# Before 2.1.0 the environment files were config/default-*.json (#20).
legacy_owned_path() {
  owned_path "$1" || { [[ "$1" == config/default-*.json && "$1" != config/*/* ]]; }
}
is_seed() { local s; for s in "${SEEDS[@]}"; do [[ "$1" == "$s" ]] && return 0; done; return 1; }

# tag_files <commit> <legacy 0|1>: the template-owned and seed files of a commit,
# one line "<path in commit>\t<path in project>" each; the root README.md is
# shipped as src/template/README.md.
tag_files() {
  local f
  while IFS= read -r -d '' f; do
    [[ "$f" != *\\* && "$f" != *$'\n'* && "$f" != *$'\t'* ]] \
      || die "$1 has a file name with a backslash, a tab or a newline: ${f@Q}"
    [[ "$f" != src/template/README.md ]] || die "$1 has src/template/README.md (reserved for the shipped README.md)"
    if [[ "$f" == README.md ]]; then
      printf '%s\t%s\n' "$f" src/template/README.md
    elif is_seed "$f" || { [[ "$2" == 1 ]] && legacy_owned_path "$f"; } || owned_path "$f"; then
      printf '%s\t%s\n' "$f" "$f"
    fi
  done < <(git -C "$upstream" ls-tree -r -z --name-only "$1")
}

# extract <commit> <dir>: the files of tag_files <commit> 0, under their project names.
extract() {
  local listing s p
  local -a src=()
  listing="$(tag_files "$1" 0)" || exit 1
  while IFS=$'\t' read -r s p; do [[ -n "$s" ]] && src+=("$s"); done <<<"$listing"
  [[ ${#src[@]} -gt 0 ]] || die "no template file in $1"
  mkdir -p "$2"
  { git -C "$upstream" archive "$1" -- "${src[@]}" | tar -x -C "$2"; } \
    || die "cannot extract the template files from $1"
  if [[ -f "$2/README.md" ]]; then
    mkdir -p "$2/src/template"
    mv "$2/README.md" "$2/src/template/README.md"
  fi
}

remove() {
  rm -f "$dest/$1"
  (cd "$dest" && rmdir -p --ignore-fail-on-non-empty "$(dirname "$1")" 2>/dev/null) || true
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
extract "$commit" "$tmp/new"
new=() seeds=()
while IFS= read -r -d '' f; do
  f="${f#./}"
  if is_seed "$f"; then seeds+=("$f"); else new+=("$f"); fi
done < <(cd "$tmp/new" && find . -type f -print0 | LC_ALL=C sort -z)
declare -A in_new=()
for f in "${new[@]}"; do in_new["$f"]=1; done

# The previous manifest drives the removals: check it before writing anything,
# so that a damaged one can never remove a project file.
old=()
declare -A old_sum=()
if [[ -f "$dest/$MANIFEST" ]]; then
  while IFS= read -r line; do
    line="${line%$'\r'}"
    { [[ "$line" =~ ^([0-9a-f]{64})\ [\ *](.+)$ ]] && owned_path "${BASH_REMATCH[2]}"; } \
      || die "$MANIFEST in $dest: not a template-owned entry: $line"
    old+=("${BASH_REMATCH[2]}")
    old_sum["${BASH_REMATCH[2]}"]="${BASH_REMATCH[1]}"
  done < "$dest/$MANIFEST"
fi
declare -A in_old=()
for f in "${old[@]}"; do in_old["$f"]=1; done

added=0 changed=0 removed=0 adopted=0 forced=0
declare -A adopt_rm=()

# Never overwrite a project file. With a previous manifest, a template file of
# the new version may already exist only if that manifest lists it. On a first
# sync, no template file may exist yet, and the owned directories must be empty.
if [[ -f "$dest/$MANIFEST" ]]; then
  clash=()
  for f in "${new[@]}"; do
    [[ -e "$dest/$f" || -L "$dest/$f" ]] || continue
    [[ -n "${in_old[$f]:-}" ]] || clash+=("$f")
  done
  [[ ${#clash[@]} -eq 0 ]] || die "files of $tag already in $dest and not from the template: ${clash[*]}"
  if [[ -n "${old_sum[$LIQUIBASE]:-}" && -f "$tmp/new/$LIQUIBASE" ]] \
      && [[ "$(sha256sum < "$tmp/new/$LIQUIBASE" | cut -d' ' -f1)" != "${old_sum[$LIQUIBASE]}" ]]; then
    warn "$LIQUIBASE changed: run liquibase update on the project databases (src/template/README.md, \"Support database creation\")"
  fi
else
  clash=()
  for f in "${new[@]}"; do
    [[ -e "$dest/$f" || -L "$dest/$f" ]] && clash+=("$f")
  done
  while IFS= read -r -d '' f; do
    f="${f#./}"
    [[ -n "${in_new[$f]:-}" ]] || clash+=("$f")
  done < <(cd "$dest" && { find ./src/template ./db/liquibase ! -type d -print0 2>/dev/null || true; } | LC_ALL=C sort -z)
  [[ ${#clash[@]} -eq 0 ]] \
    || die "no $MANIFEST in $dest, and template files already there: ${clash[*]} (a project that already holds template files: use --adopt-from <tag|auto>)"
fi

for f in "${new[@]}"; do
  if [[ ! -e "$dest/$f" ]]; then
    added=$((added + 1))
  elif ! cmp -s "$tmp/new/$f" "$dest/$f" \
      || [[ "$(stat -c %a "$tmp/new/$f")" != "$(stat -c %a "$dest/$f")" ]]; then
    changed=$((changed + 1))
  fi
done
for f in "${old[@]}"; do
  if [[ -z "${in_new[$f]:-}" ]] && [[ -e "$dest/$f" || -L "$dest/$f" ]]; then
    remove "$f"
    removed=$((removed + 1))
  fi
done
for f in "${!adopt_rm[@]}"; do
  remove "$f"
  removed=$((removed + 1))
done

# Only the files: a "." entry would give $dest the 0700 mode of $tmp.
(cd "$tmp/new" && tar -cf - -- "${new[@]}") | tar -x -C "$dest"
for f in "${seeds[@]}"; do
  if [[ -e "$dest/$f" ]]; then
    cmp -s "$tmp/new/$f" "$dest/$f" || warn "kept local $f (SQLite seed file: never overwritten)"
  else
    (cd "$tmp/new" && tar -cf - -- "$f") | tar -x -C "$dest"
    added=$((added + 1))
  fi
done
(cd "$dest" && sha256sum -- "${new[@]}") > "$dest/$MANIFEST"
printf '%s %s\n' "$tag" "$commit" > "$dest/SERASOFT_VERSION"

echo "OK serasoft-sync tag=$tag commit=${commit:0:12} added=$added changed=$changed removed=$removed adopted=$adopted forced=$forced"
