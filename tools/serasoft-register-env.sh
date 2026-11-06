#!/usr/bin/env bash
# Registers this project and one of its environments in the local Hop
# installation (hop-config.json), from config/env/<env>.list, for executions
# started by cron/hop_runner.sh instead of the Serasoft Airflow platform.
# Lines /run/secrets/<name> of the manifest are mapped to <secrets-dir>/<name>.
# Safe to re-run: an existing environment gets the current file list.
# See README.md (src/template/README.md in projects), "Running with cron".
#
# Usage: tools/serasoft-register-env.sh --env <env> [--project <name>] [--hop-env <name>] [--secrets-dir <dir>]
set -uo pipefail

usage() {
  echo "usage: tools/serasoft-register-env.sh --env <env> [--project <name>] [--hop-env <name>] [--secrets-dir <dir>]" >&2
  exit 64
}
die() { echo "ERROR: $*" >&2; exit 1; }

env_name="" project="" hop_env="" secrets_dir="/etc/serasoft/secrets"
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --env)         env_name="$2" ;;
    --project)     project="$2" ;;
    --hop-env)     hop_env="$2" ;;
    --secrets-dir) secrets_dir="$2" ;;
    *)             usage ;;
  esac
  shift 2
done
[[ -n "$env_name" ]] || usage
# hop-conf/Hop run from another working directory: make the secrets dir absolute
[[ "$secrets_dir" == /* ]] || secrets_dir="$PWD/$secrets_dir"

unset CDPATH
home="$(cd "$(dirname "$0")/.." && pwd -P)"
project="${project:-$(basename "$home")}"
hop_env="${hop_env:-$project-$env_name}"
for n in "$env_name" "$project" "$hop_env"; do
  [[ "$n" =~ ^[A-Za-z0-9_.-]+$ ]] \
    || { echo "ERROR: invalid name '$n' (letters, digits, '_', '.', '-' only)" >&2; exit 64; }
done

[[ -n "${HOP_HOME:-}" ]] || die "HOP_HOME environment variable is not set"
hop_conf="$HOP_HOME/hop-conf.sh"
[[ -x "$hop_conf" ]] || die "$hop_conf not found or not executable"

# --- manifest: every line is checked before hop-config.json is touched ---
manifest="$home/config/env/$env_name.list"
[[ -f "$manifest" ]] || die "manifest $manifest not found"
files=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  case "$line" in ''|'#'*) continue ;; esac
  if [[ "$line" == /run/secrets/* ]]; then
    name="${line#/run/secrets/}"
    [[ -n "$name" && "$name" != */* ]] || die "$manifest: invalid secret path: $line"
    path="$secrets_dir/$name"
  elif [[ "$line" == /* ]]; then
    die "$manifest: absolute paths are allowed only under /run/secrets/: $line"
  else
    path="$home/$line"
  fi
  [[ "$path" != *,* ]] || die "$manifest: the path of '$line' contains a comma: $path"
  [[ -f "$path" && -r "$path" ]] || die "$manifest: $path (from '$line') is missing or not readable"
  files+=("$path")
done < "$manifest"
[[ ${#files[@]} -gt 0 ]] || die "$manifest lists no file"

# --- project ---
project_config="$home/config/project-config.json"
[[ -f "$project_config" ]] || die "$project_config not found"
listing="$("$hop_conf" -pl)" || die "hop-conf.sh -pl failed"
registered_home="$(awk -v p="$project" '/^  [^ ]/ && $1 == p && $2 == ":" { sub(/^  [^ ]+ : /, ""); print; exit }' <<<"$listing")"
if [[ -z "$registered_home" ]]; then
  backup="$(mktemp)"
  trap 'rm -f "$backup"' EXIT
  cp "$project_config" "$backup"
  pc_rc=0
  pc_out="$("$hop_conf" -pc -p "$project" -ph "$home" -pf config/project-config.json 2>&1)" || pc_rc=$?
  if ! cmp -s "$backup" "$project_config"; then
    cat "$backup" > "$project_config"
    echo "WARNING: hop-conf.sh rewrote config/project-config.json: original content restored" >&2
  fi
  [[ $pc_rc -eq 0 ]] || die "hop-conf.sh: cannot register project $project"$'\n'"$pc_out"
elif [[ "$registered_home" != "$home" ]]; then
  die "project $project is already registered with home $registered_home, not $home (use --project <name>)"
fi

# --- environment ---
envs="$("$hop_conf" -el)" || die "hop-conf.sh -el failed"
joined="$(IFS=,; printf '%s' "${files[*]}")"
if awk -v e="$hop_env" '/^  [^ ]/ && NF == 1 && $1 == e { found = 1 } END { exit !found }' <<<"$envs"; then
  action=-em
else
  action=-ec
fi
em_out="$("$hop_conf" "$action" -e "$hop_env" -ep "$project" -eu "$env_name" -eg "$joined" 2>&1)" \
  || die "hop-conf.sh $action: cannot register environment $hop_env"$'\n'"$em_out"

echo "OK serasoft-register-env project=$project hop-env=$hop_env files=${#files[@]}"
echo "  hop_runner.sh main.hwf -prj:$project -env:$hop_env -param:p_base_process_name=<process>"
