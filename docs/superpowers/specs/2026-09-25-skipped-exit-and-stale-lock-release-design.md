# Design: non-zero exit on skipped executions, manual release of stale locks

Status: approved, ready for implementation planning
Tracks: [#26](https://github.com/SeraSoft/hop-process-template/issues/26),
[#27](https://github.com/SeraSoft/hop-process-template/issues/27)
(follow-up: [#28](https://github.com/SeraSoft/hop-process-template/issues/28))
Date: 2026-09-25

## Context

Template-based processes are going to be orchestrated by the Serasoft Apache
Airflow platform (SeraSoft/airflow-platform, SeraSoft/airflow-dags), which
runs `hop-run` in Docker containers and judges each run **only by its exit
code**. The platform kills runs on purpose: a remote `timeout` before the
task's `execution_timeout`, removal of the Swarm service, `on_kill` on a
manual clear.

The single-instance lock (#11, #12) is the flag
`config.integrations_processes.is_running`:
`src/template/pre/main_pre_job.hwf` refuses to run when it is `'Y'`, otherwise
sets it; `src/template/post/update_process_reference.hpl` (both post phases)
resets it to `'N'` — except when the run itself was skipped, so a skipped run
never clears the lock held by another instance.

## Problems

1. **Skipped runs exit 0.** When the lock is present
   (`v_terminated_successfully = 2`, log status `L`) or the process is paused
   (`is_active` not `Y`, `v_terminated_successfully = 3`, status `P`),
   `main.hwf` goes through `Post Phase Success` and ends in
   `Terminated Successfully`, so `hop-run` exits **0**. An orchestrator reports
   success although nothing was processed.
2. **Killed runs leave the lock set forever.** A killed run never reaches the
   post phase: `is_running` stays `'Y'` and its `integrations_logs` row stays
   `R`. Every later run is skipped — and, because of problem 1, reported as
   successful. The orphaned `R` row also skews `MAX(date_started)` used for
   `v_last_instance_start_timestamp` (#23/#24).

## Constraint

`hop-run` exits only with **0** (success), **1** (error during execution —
also the effect of an `Abort` action), **2** (general error) or **9**
(parameter error) — Hop user manual, *Hop Run → Possible exit codes*. A
workflow cannot return a custom code such as 75.

## Decision

### #26 — skipped executions exit 1

In `main.hwf` only (the skill's Hop STANDARDS.md are deliberately not applied
to the template for now: in-place change, template style):

- the two existing `SET_VARIABLES` actions that mark the skip
  (`Set terminated because lock set `, `… not active`) also set
  `v_skip_message` (root workflow scope):
  `SKIPPED: process '${p_base_process_name}' is locked by an instance started at ${v_last_instance_start_timestamp}`
  / `SKIPPED: process '${p_base_process_name}' is not active`;
- the end of the success path (after `Post Phase Success` and the optional
  feedback email), currently `Dummy 2 → Terminated Successfully`, becomes
  `Dummy 2 → Execution skipped?` — a `SIMPLE_EVAL` succeeding when
  `${v_terminated_successfully}` matches `^[23]$` (the variable is reset to 1
  by `Init Global Vars` on every run, so a `v_skip_message` inherited from a
  parent workflow or JVM property cannot turn a success into a failure) —
  `→ Skipped` (`Abort`, message `${v_skip_message}`, exit 1) on true,
  `→ Terminated Successfully` on false.

Net +2 actions; no other action or hop changes.

Unchanged: pre and post phases, feedback emails, log statuses `L`/`P`, the
`is_running` handling. Only the final outcome changes, from success to
failure (exit 1).

Rejected alternatives: a machine-readable skip marker translated to a
dedicated exit code by an image entrypoint (possible later, if an
orchestrator needs to tell "skipped" from "failed"); a Hop plugin calling
`System.exit` (bypasses Hop's orderly shutdown).

Consequence for orchestrators: a skip is a failed run. With Airflow retries,
a retry after the other instance ends simply runs; a stale lock becomes
visible (red task) instead of silent green no-ops.

### #27 — manual release of a stale lock

New workflow `src/template/commons/tools/locks/release_lock.hwf` (parameter
check, process check, log, one `SQL` action like `Set is_running flag to Y`
in `main_pre_job.hwf`) plus the check pipeline
`src/template/commons/tools/locks/release_lock_check.hpl`, parameter
`p_base_process_name`, mandatory:

1. stop with an error if no process has that `short_name` (small pipeline
   `release_lock_check.hpl`: `Table input` → `Detect empty stream` →
   `Abort`), so a mistyped name is not reported as a successful release.
   The `EVAL_TABLE_CONTENT` action was rejected: in Hop 2.19 it does not
   resolve a variable connection name at run time ("No database connection
   is defined"), although the GUI resolves it while editing;
2. log a warning with the process name;
3. mark that process's orphaned rows in `logs.integrations_logs`
   (`proc_status = 'R'`) with the new status **`K`** — manually released,
   instance interrupted — so `MAX(date_started)` over `R` rows is correct
   again;
4. `UPDATE config.integrations_processes SET is_running = 'N' WHERE
   short_name = <p_base_process_name>`.

Steps 3 and 4 are two statements of one `SQL` action, each committed on its
own (not one transaction). The order makes the tool idempotent: if it fails
between the two, running it again completes the release.

Run with
`hop-run -j <project> -r local -f ${PROJECT_HOME}/src/template/commons/tools/locks/release_lock.hwf -p p_base_process_name=<name>`.
The operator must first check that no instance is really running: the tool
cannot distinguish a stale lock from a legitimate one. The existing
`Log warning lock is set` message in `main.hwf` ("check integration_processes
table and eventually uncleand lock") is updated to point to this tool. Schemas and connection
come from the same variables as the template (`serasoft.integrations.db.*`).

Automatic expiry (a lock max-age parameter the orchestrator sets to its own
timeout) is **out of scope**: tracked in #28 and documented in the README as a
future improvement.

## Documentation

`README.md`:
- exit codes: 0 success; 1 error **or skipped execution** (`SKIPPED: …` in
  the log); 2/9 as per `hop-run`;
- process statuses (`R`, `T`, `X`, `E`, `L`, new `K`), and that a paused
  process is skipped before any row is written;
- stale locks: how they arise, how to check, how to release them with
  `release_lock.hwf`, and the future automatic expiry (#28).

## Verification

Live, in the Serasoft Airflow lab (the template has no Hop-native test
harness on `main` yet; the one on branch `integration_test`, #25, is work in
progress — Hop-native tests will follow it):

- `integrations_db` as a dedicated database on the lab PostgreSQL, created
  from `db/liquibase/master-postgresql.xml` with `liquibase/liquibase:4.33.0`
  (4.x is Apache 2.0; 5.x moved to FSL);
- Apache Hop 2.19.0 in a throwaway container (the template uses only standard
  Hop plugins), one test process registered in `integrations_processes`.

| Scenario | Expected |
|---|---|
| normal run | exit 0; `is_running = 'N'`; log row `T` |
| lock present (`is_running` set to `'Y'` by hand) | exit 1; `SKIPPED: … is locked` in the log; row `L`; `is_running` still `'Y'` |
| process paused (`is_active` not `Y`) | exit 1; `SKIPPED: … is not active`; no log row (the `is_active` check runs before the instance is created — existing behaviour) |
| run killed with SIGKILL mid-execution | `is_running = 'Y'`, row `R`; after `release_lock.hwf`: `'N'` and row `K`; next run exit 0 |

## Delivery

Branch `issue_026_027` from `main`, one commit per issue (plus this spec and
the plan), one PR `Closes #26`, `Closes #27`. `docs/` is not shipped in the
release ZIP (`.github/workflows/ship-package.yml`).
