#!/usr/bin/env bash
# Scenario checks of the template workflows on one Hop version (spec "Testing").
# Prerequisite: tests/hop/lab.sh up. Makes a fresh copy of the working tree first.
# Usage: tests/hop/scenarios.sh <hop version>   (exit 1 if a check failed)
set -uo pipefail
unset CDPATH
HERE="$(cd "$(dirname "$0")" && pwd -P)"
LAB="$HERE/lab.sh"
LOG="$HERE/work/hoprun.log"
COPY="$HERE/work/copy"
VER="${1:?usage: tests/hop/scenarios.sh <hop version>}"
failed=0

check() { # check <description> <command...>
  if "${@:2}"; then echo "  ok   $1"; else echo "  FAIL $1"; failed=1; fi
}
run() { RC="$("$LAB" run "$VER" "$@" | sed -n 's/^RC=//p')"; }
rc_is() { [[ "$RC" == "$1" ]]; }
log_has() { grep -qF -- "$1" "$LOG"; }
log_lacks() { ! grep -qF -- "$1" "$LOG"; }
sql_is() { [[ "$("$LAB" sql "$1")" == "$2" ]]; }
marker_is() { [[ "$(cat "$COPY/temp/result" 2>/dev/null)" == "$1" ]]; }
reset() {
  "$LAB" sql "UPDATE config.integrations_processes SET is_running='N', is_active='Y'" >/dev/null
  rm -f "$COPY"/config/*.properties "$COPY/temp/result"
}

s_default() {
  echo "default process"
  reset
  run main.hwf "p_base_process_name=default"
  check "exit code 0" rc_is 0
  check "last run of default is T" sql_is \
    "SELECT proc_status FROM logs.integrations_logs WHERE integrations_processes_id='default' ORDER BY date_started DESC LIMIT 1" T
  check "lock released" sql_is "SELECT is_running FROM config.integrations_processes WHERE short_name='default'" N
}

s_regression() {
  echo "regression: paused, locked, result marker"
  reset
  "$LAB" sql "UPDATE config.integrations_processes SET is_active='N' WHERE short_name='default'" >/dev/null
  run main.hwf "p_base_process_name=default" "SERASOFT_RESULT_FILE=/project/temp/result"
  check "paused: exit code 1" rc_is 1
  check "paused: marker skipped_paused" marker_is skipped_paused
  reset
  "$LAB" sql "UPDATE config.integrations_processes SET is_running='Y' WHERE short_name='default'" >/dev/null
  run main.hwf "p_base_process_name=default" "SERASOFT_RESULT_FILE=/project/temp/result"
  check "locked: exit code 1" rc_is 1
  check "locked: marker skipped_locked" marker_is skipped_locked
  check "locked: SKIPPED message" log_has "SKIPPED: process 'default' is locked"
  reset
}

s_short_name() {
  echo "process whose id differs from short_name"
  local id=6f1c2a8e-0d4b-4c39-9a57-3b2f0e5d7c11
  reset
  run main.hwf "p_base_process_name=uuidtest"
  check "exit code 0" rc_is 0
  check "process started" log_has "VARTEST"
  check "log row references the internal id" sql_is \
    "SELECT proc_status FROM logs.integrations_logs WHERE integrations_processes_id='$id' ORDER BY date_started DESC LIMIT 1" T
  check "lock released" sql_is "SELECT is_running FROM config.integrations_processes WHERE short_name='uuidtest'" N
  run src/template/commons/tools/check_state.hwf "p_base_process_name=uuidtest"
  check "check_state: can run" rc_is 0
  "$LAB" sql "UPDATE config.integrations_processes SET is_running='Y' WHERE short_name='uuidtest'" >/dev/null
  run src/template/commons/tools/check_state.hwf "p_base_process_name=uuidtest"
  check "check_state: locked, exit code 1" rc_is 1
  check "check_state: locked message" log_has "SKIPPED: process 'uuidtest' is locked"
  run src/template/commons/tools/locks/release_lock.hwf "p_base_process_name=uuidtest"
  check "release_lock: exit code 0" rc_is 0
  check "release_lock: flag N" sql_is "SELECT is_running FROM config.integrations_processes WHERE short_name='uuidtest'" N
  reset
}

SCENARIOS=(s_default s_regression s_short_name)

"$LAB" copy >/dev/null
for s in "${SCENARIOS[@]}"; do "$s"; done
if [[ $failed -eq 0 ]]; then echo "OK scenarios hop=$VER"; else echo "FAILED scenarios hop=$VER"; exit 1; fi
