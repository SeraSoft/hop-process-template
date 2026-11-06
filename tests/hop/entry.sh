#!/usr/bin/env bash
# Runs inside an apache/hop container (see tests/hop/lab.sh run): registers the
# project "tpl" (/project) and the environment "lab" (template files + lab
# overrides), then runs hop-run. Exit code: the one of hop-run, 2 if the
# registration fails.
# Usage: entry.sh <file relative to /project> <params or ""> <variables or "">
set -uo pipefail
file="$1" params="${2:-}" vars="${3:-}"
mkdir -p "$HOP_CONFIG_FOLDER" "$HOP_AUDIT_FOLDER"
/opt/hop/hop-conf.sh -pc -p tpl -ph /project >/dev/null || exit 2
/opt/hop/hop-conf.sh -ec -e lab -ep tpl \
  -eg /project/config/template-env.json,/project/config/template-postgresql.json,/tests/lab-env.json \
  >/dev/null || exit 2
args=(-j tpl -e lab -r local -f "/project/$file")
[[ -n "$params" ]] && args+=(-p "$params")
[[ -n "$vars" ]] && args+=(-s "$vars")
/opt/hop/hop-run.sh "${args[@]}"
