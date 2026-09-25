# Skipped-Execution Exit Code and Stale-Lock Release — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `hop-run` exit 1 (with an explicit `SKIPPED: …` log message) when the template skips an execution because of the single-instance lock or a paused process (#26), and add a manual tool to release a lock left set by a killed execution (#27).

**Architecture:** #26 is an in-place change of `main.hwf`: the two existing skip-marking `SET_VARIABLES` actions also set `v_skip_message`, and the end of the success path goes through a `SIMPLE_EVAL` (`${v_terminated_successfully}` matches `^[23]$`, i.e. locked or paused) to an `Abort` instead of straight to `Terminated Successfully`. #27 adds one workflow, `src/template/commons/tools/locks/release_lock.hwf` (parameter check, log, one `SQL` action), and points the existing lock warning to it. Both are verified live against a real `integrations_db` on PostgreSQL.

**Tech Stack:** Apache Hop 2.19.0 workflows (XML), PostgreSQL 16 (`integrations_db` created with the template's Liquibase changelog), Docker (Hop runtime from the lab image `serasoft-lab/ssh-target:2.19.0`, which ships Hop 2.19.0 + JRE 21 in `/opt/hop`).

**Spec:** `docs/superpowers/specs/2026-09-25-skipped-exit-and-stale-lock-release-design.md`. Issues: #26, #27 (follow-up #28 is out of scope).

---

## Context the engineer needs

- Repo: `/home/enrico/repositories/serasoft/hop-process-template`, branch `issue_026_027` (checked out, from `main`). Commit messages English, **no `Co-Authored-By`**, do **not** push (the controller pushes and opens the PR).
- **Do not apply** the `apache-hop-development` skill's `STANDARDS.md` to this repo (user decision): change existing files in place, follow the template's existing style, don't add notepads or rename actions.
- Hop files are XML; always check well-formedness after an edit: `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1]); print('xml ok')" <file>`.
- `hop-run` exit codes: 0 success, 1 error (also `Abort`), 2 general error, 9 parameter error. A workflow cannot return other codes.
- **Test harness (outside the repo, already prepared, in the lab's local `lab/` folder — not in git):** `H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test`
  - `$H/make_copy.sh` — makes a fresh throwaway copy of the repo working tree in `$H/copy` (runs write `logs/`, `temp/`, `project-config.json`, `hoprun.log` there — never run against the repo itself) and adds a test-only process `slowtest` whose `start.hwf` runs `SELECT pg_sleep(60)`.
  - `$H/run.sh <copy> <workflow> [params]` — runs `hop-run -e lab -r local -f /project/<workflow> -p '<params>'` in a throwaway container named `hoptest-run` on network `airflow-lab_default`, with project `tpl` = `<copy>` and environment `lab` = `$H/lab-env.json` (the template's variables, DB host `postgres:5432`, all feedback emails disabled). Prints `RC=<exit code>`; the Hop log is `<copy>/hoprun.log`. Default params: `p_base_process_name=default`.
  - `$H/q.sh "<sql>"` — runs one statement on the lab `integrations_db` (tuples only).
  - The lab `integrations_db` exists (created from `db/liquibase/master-postgresql.xml` with `liquibase/liquibase:4.33.0`); `config.integrations_processes` holds `default` and `slowtest` (`project='hop-process-template'`).
- Reset the process rows before each scenario: `$H/q.sh "update config.integrations_processes set is_active='Y', is_running='N'"`.
- Process statuses in `logs.integrations_logs.proc_status`: `R` running, `T` terminated, `X` terminated with application errors, `E` error, `L` skipped because locked, `K` (new, #27) lock released manually. A paused run creates **no** log row (the `is_active` check runs before the instance is created).

## File structure

| File | Change |
|---|---|
| `main.hwf` | #26: `v_skip_message` in the two skip `SET_VARIABLES`; new `Execution skipped?` (`SIMPLE_EVAL`) + `Skipped` (`ABORT`); rewired end of the success path. #27: lock warning text points to `release_lock.hwf` |
| `src/template/commons/tools/locks/release_lock.hwf` | **new** (#27) |
| `README.md` | #26: "Exit codes" section; #27: "Process statuses and stale locks" section (incl. future #28) |

---

### Task 1: Non-zero exit on skipped executions (#26)

**Files:** Modify `main.hwf`, `README.md`.

- [ ] **Step 1: Baseline (red) on the current code**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/make_copy.sh
$H/q.sh "update config.integrations_processes set is_active='Y', is_running='Y' where id='default'"
$H/run.sh $H/copy main.hwf
grep -c "IS LOCKED" $H/copy/hoprun.log
$H/q.sh "update config.integrations_processes set is_active='Y', is_running='N'"
```
Expected: `RC=0` although the process was skipped (log contains `IS LOCKED`). This is the bug.

- [ ] **Step 2: Patch `main.hwf`** — run this script from the repo root (it asserts each anchor is found exactly once):

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
python3 - main.hwf <<'PYEOF'
import sys
p=sys.argv[1]; s=open(p).read()
def rep(a,b):
    global s
    assert s.count(a)==1, a[:70]; s=s.replace(a,b)
rep("""          <variable_value>${serasoft.email.lock.feedback.enabled}</variable_value>
        </field>
""","""          <variable_value>${serasoft.email.lock.feedback.enabled}</variable_value>
        </field>
        <field>
          <variable_name>v_skip_message</variable_name>
          <variable_type>ROOT_WORKFLOW</variable_type>
          <variable_value>SKIPPED: process '${p_base_process_name}' is locked by an instance started at ${v_last_instance_start_timestamp}</variable_value>
        </field>
""")
rep("""          <variable_value>${serasoft.email.notactive.feedback.enabled}</variable_value>
        </field>
""","""          <variable_value>${serasoft.email.notactive.feedback.enabled}</variable_value>
        </field>
        <field>
          <variable_name>v_skip_message</variable_name>
          <variable_type>ROOT_WORKFLOW</variable_type>
          <variable_value>SKIPPED: process '${p_base_process_name}' is not active</variable_value>
        </field>
""")
rep("""      <name>Terminated Successfully</name>
      <description/>
      <type>SUCCESS</type>
      <attributes/>
      <parallel>N</parallel>
      <xloc>1200</xloc>
      <yloc>192</yloc>
      <attributes_hac/>
    </action>
""","""      <name>Terminated Successfully</name>
      <description/>
      <type>SUCCESS</type>
      <attributes/>
      <parallel>N</parallel>
      <xloc>1376</xloc>
      <yloc>192</yloc>
      <attributes_hac/>
    </action>
    <action>
      <name>Execution skipped?</name>
      <description/>
      <type>SIMPLE_EVAL</type>
      <attributes/>
      <comparevalue>^[23]$</comparevalue>
      <fieldtype>string</fieldtype>
      <successbooleancondition>false</successbooleancondition>
      <successcondition>regexp</successcondition>
      <successnumbercondition>equal</successnumbercondition>
      <successwhenvarset>N</successwhenvarset>
      <valuetype>variable</valuetype>
      <variablename>${v_terminated_successfully}</variablename>
      <parallel>N</parallel>
      <xloc>1200</xloc>
      <yloc>192</yloc>
      <attributes_hac/>
    </action>
    <action>
      <name>Skipped</name>
      <description/>
      <type>ABORT</type>
      <attributes/>
      <always_log_rows>N</always_log_rows>
      <message>${v_skip_message}</message>
      <parallel>N</parallel>
      <xloc>1200</xloc>
      <yloc>320</yloc>
      <attributes_hac/>
    </action>
""")
rep("""      <from>Dummy 2</from>
      <to>Terminated Successfully</to>
      <enabled>Y</enabled>
      <evaluation>Y</evaluation>
      <unconditional>Y</unconditional>
    </hop>
""","""      <from>Dummy 2</from>
      <to>Execution skipped?</to>
      <enabled>Y</enabled>
      <evaluation>Y</evaluation>
      <unconditional>Y</unconditional>
    </hop>
    <hop>
      <from>Execution skipped?</from>
      <to>Skipped</to>
      <enabled>Y</enabled>
      <evaluation>Y</evaluation>
      <unconditional>N</unconditional>
    </hop>
    <hop>
      <from>Execution skipped?</from>
      <to>Terminated Successfully</to>
      <enabled>Y</enabled>
      <evaluation>N</evaluation>
      <unconditional>N</unconditional>
    </hop>
""")
open(p,"w").write(s); print("patched")
PYEOF
python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1]); print('xml ok')" main.hwf
git diff --stat
```
Expected: `patched`, `xml ok`, `main.hwf | 43 +++++-` (about +42/-1).

- [ ] **Step 3: README "Exit codes"** — insert this section right before the final `---` of `README.md` (after the environment-variables table). The exact text is prepared in `$H/readme_exit_codes.md`:

````markdown
## Exit codes

`hop-run` ends a template-based execution with:

| Exit code | Meaning |
|---|---|
| `0` | The process ran and terminated successfully (possibly with application errors recorded in `integrations_log_details`, status `X`). |
| `1` | The process failed, **or it was skipped**: another instance holds the single-instance lock, or the process is paused (`is_active` not `Y`). A skipped execution logs an explicit `SKIPPED: …` error message and still runs the post phase and the feedback email, if enabled for that case. |
| `2`, `9` | General `hop-run` error / invalid parameters (Hop Run, *Possible exit codes*). |

A skipped execution is reported as a failure on purpose: an orchestrator (cron, Apache Airflow) must not treat "nothing was processed" as success.
````

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
python3 - README.md $H/readme_exit_codes.md <<'PYEOF'
import sys
p, sec = sys.argv[1], open(sys.argv[2]).read()
s = open(p).read().rstrip("\n")
assert s.endswith("---")
s = s[:-3].rstrip("\n") + "\n\n" + sec.strip("\n") + "\n\n---\n"
open(p, "w").write(s); print("inserted")
PYEOF
tail -5 README.md
```
Expected: `inserted`; README ends with the new section followed by `---`.

- [ ] **Step 4: Verify (green) on a fresh copy**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/make_copy.sh
$H/q.sh "update config.integrations_processes set is_active='Y', is_running='N'"
echo "== normal"; $H/run.sh $H/copy main.hwf; grep -E "Execution skipped\?\] \(result|Terminated Successfully\] \(result" $H/copy/hoprun.log
echo "   flag=$($H/q.sh "select is_running from config.integrations_processes where id='default'") last=$($H/q.sh "select proc_status from logs.integrations_logs where integrations_processes_id='default' order by date_started desc limit 1")"
echo "== lock"; $H/q.sh "update config.integrations_processes set is_running='Y' where id='default'"; $H/run.sh $H/copy main.hwf; grep -o "ERROR: SKIPPED[^\"]*" $H/copy/hoprun.log
echo "   flag=$($H/q.sh "select is_running from config.integrations_processes where id='default'") last=$($H/q.sh "select proc_status from logs.integrations_logs where integrations_processes_id='default' order by date_started desc limit 1")"
echo "== paused"; $H/q.sh "update config.integrations_processes set is_running='N', is_active='N' where id='default'"; $H/run.sh $H/copy main.hwf; grep -o "ERROR: SKIPPED[^\"]*" $H/copy/hoprun.log
$H/q.sh "update config.integrations_processes set is_active='Y', is_running='N'"
```
Expected:
- normal: `RC=0`, `Execution skipped?] (result=[false])`, `Terminated Successfully] (result=[true])`, `flag=N last=T`;
- lock: `RC=1`, `ERROR: SKIPPED: process 'default' is locked by an instance started at …` (timestamp empty here, because the lock was set by hand without a running row), `flag=Y last=L` (the other instance's lock is untouched);
- paused: `RC=1`, `ERROR: SKIPPED: process 'default' is not active`.

- [ ] **Step 5: Commit**

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
git add main.hwf README.md
git commit -m "Exit 1 with a SKIPPED message when an execution is skipped (lock present or process paused)

hop-run exited 0 when the single-instance lock or a paused process made
the template skip the run, so orchestrators reported success although
nothing was processed. The end of the success path now aborts with the
reason when v_skip_message is set; post phase and feedback are unchanged.

Refs #26"
```

---

### Task 2: Manual release of stale locks (#27)

**Files:** Create `src/template/commons/tools/locks/release_lock.hwf`; modify `main.hwf` (lock warning text), `README.md`.

- [ ] **Step 1: Baseline (red): a killed run leaves the lock set and there is no release tool**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/make_copy.sh
$H/q.sh "update config.integrations_processes set is_active='Y', is_running='N'"
( $H/run.sh $H/copy main.hwf p_base_process_name=slowtest > $H/slow.out 2>&1 & )
for i in $(seq 1 30); do st=$($H/q.sh "select proc_status from logs.integrations_logs where integrations_processes_id='slowtest' order by date_started desc limit 1"); [ "$st" = "R" ] && break; sleep 2; done
docker kill -s KILL hoptest-run >/dev/null; sleep 3
echo "flag=$($H/q.sh "select is_running from config.integrations_processes where id='slowtest'") last=$($H/q.sh "select proc_status from logs.integrations_logs where integrations_processes_id='slowtest' order by date_started desc limit 1")"
ls $H/copy/src/template/commons/tools/locks/
```
Expected: `flag=Y last=R` (stale lock); only `check_status_and_lock.hpl` in `locks/`. Leave this stale state in place for Step 5.

- [ ] **Step 2: Create `src/template/commons/tools/locks/release_lock.hwf`** — copy the prototype verified in the lab:

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
cp /home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test/release_lock.hwf src/template/commons/tools/locks/release_lock.hwf
python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1]); print('xml ok')" src/template/commons/tools/locks/release_lock.hwf
grep -E "<name>|<type>" src/template/commons/tools/locks/release_lock.hwf
```
Expected: `xml ok`; workflow `Release lock` with parameter `p_base_process_name` and actions `START` → `Check p_base_process_name exists` (SIMPLE_EVAL, regexp) → `Log lock release` (WRITE_TO_LOG) → `Release lock` (SQL, two statements, `sendOneStatement=N`: logs rows `R` → `K`, then `is_running='N'`) → `Lock released` (SUCCESS); failures to `Missing p_base_process_name` / `Release failed` (ABORT). Read the file once fully to confirm this.

- [ ] **Step 3: Point the lock warning to the tool** — in `main.hwf`:

```bash
python3 - main.hwf <<'PYEOF'
import sys
p=sys.argv[1]; s=open(p).read()
old="""However, maybe previous instance exited abnormally and lock wasn't cleared.
Please check integration_processes table and eventually uncleand lock."""
new="""However, maybe previous instance exited abnormally and lock wasn't cleared.
If no instance is really running, release the lock with
src/template/commons/tools/locks/release_lock.hwf (parameter p_base_process_name, see README, "Stale locks")."""
assert s.count(old)==1; open(p,"w").write(s.replace(old,new)); print("patched")
PYEOF
python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1]); print('xml ok')" main.hwf
```

- [ ] **Step 4: README "Process statuses and stale locks"** — insert this section after "Exit codes", before the final `---`. The exact text is prepared in `$H/readme_stale_locks.md`:

````markdown
## Process statuses and stale locks

Each execution writes a row in `logs.integrations_logs` whose `proc_status` is:

| Status | Meaning |
|---|---|
| `R` | Running |
| `T` | Terminated successfully |
| `X` | Terminated successfully, with application errors in `integrations_log_details` |
| `E` | Terminated in error |
| `L` | Skipped: another instance held the lock |
| `K` | Interrupted execution whose lock was released manually (see below) |

A paused process (`is_active` not `Y`) is skipped before any row is written.

### Stale locks

The single-instance lock is `config.integrations_processes.is_running`: set to `Y` when an execution starts, reset to `N` by the post phase. If an execution is **killed** (timeout of an orchestrator, container or service removed, host restart), the post phase never runs: `is_running` stays `Y` and the execution's row stays `R`. Every later execution is then skipped (exit code `1`, `SKIPPED: process '…' is locked …`).

After checking that **no instance of the process is really running**, release the lock:

```
hop-run -j <project> -e <environment> -r local \
  -f ${PROJECT_HOME}/src/template/commons/tools/locks/release_lock.hwf \
  -p p_base_process_name=<process short name>
```

The workflow sets `is_running` to `N` and marks the process's rows still in `R` as `K`. It cannot tell a stale lock from a legitimate one: running it while an instance is executing allows a second, parallel execution.

**Future improvement** (#28): an optional lock max-age parameter; an orchestrator that enforces its own execution timeout could pass it so that locks older than that timeout, which are necessarily stale, are released automatically.
````

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
python3 - README.md $H/readme_stale_locks.md <<'PYEOF'
import sys
p, sec = sys.argv[1], open(sys.argv[2]).read()
s = open(p).read().rstrip("\n")
assert s.endswith("---")
s = s[:-3].rstrip("\n") + "\n\n" + sec.strip("\n") + "\n\n---\n"
open(p, "w").write(s); print("inserted")
PYEOF
grep -n "^## " README.md
```
Expected: `inserted`; headings end with `## Exit codes`, `## Process statuses and stale locks`.

- [ ] **Step 5: Verify (green): stale lock → skipped → release → next run succeeds** (the stale state from Step 1 is still in the DB; refresh the copy so it contains the new workflow)

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/make_copy.sh
echo "== run while stale"; $H/run.sh $H/copy main.hwf p_base_process_name=slowtest; grep -o "ERROR: SKIPPED[^\"]*" $H/copy/hoprun.log; grep -c "release_lock.hwf" $H/copy/hoprun.log
echo "== release without parameter"; $H/run.sh $H/copy src/template/commons/tools/locks/release_lock.hwf p_base_process_name=; grep -o "Parameter p_base_process_name is required[^\"]*" $H/copy/hoprun.log
echo "== release"; $H/run.sh $H/copy src/template/commons/tools/locks/release_lock.hwf p_base_process_name=slowtest
echo "   flag=$($H/q.sh "select is_running from config.integrations_processes where id='slowtest'") rows=$($H/q.sh "select string_agg(proc_status,',' order by date_started) from logs.integrations_logs where integrations_processes_id='slowtest'")"
echo "== next run (about 60 s)"; $H/run.sh $H/copy main.hwf p_base_process_name=slowtest
echo "   flag=$($H/q.sh "select is_running from config.integrations_processes where id='slowtest'") last=$($H/q.sh "select proc_status from logs.integrations_logs where integrations_processes_id='slowtest' order by date_started desc limit 1")"
```
Expected:
- run while stale: `RC=1`, `ERROR: SKIPPED: process 'slowtest' is locked by an instance started at <dd/MM/yyyy HH:mm:ss>`, and the lock warning mentions `release_lock.hwf` (count ≥ 1);
- release without parameter: `RC=1`, `Parameter p_base_process_name is required…`;
- release: `RC=0`; the killed run's row is now `K` (the list ends with `…,K,L` or contains `K` where the `R` was), `flag=N`;
- next run: `RC=0`, `flag=N last=T`.
Also re-run the three Task 1 scenarios (Task 1 Step 4) to confirm no regression.

- [ ] **Step 6: Commit**

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
git add src/template/commons/tools/locks/release_lock.hwf main.hwf README.md
git commit -m "Add release_lock.hwf to release stale locks left by killed executions

A killed execution never runs the post phase, so is_running stayed 'Y'
and its log row 'R' forever, blocking every later run. The new workflow
resets the flag and marks the interrupted rows with the new status K;
the lock warning and the README explain when and how to use it.
Automatic expiry is left to #28.

Refs #27"
```

---

## After the tasks (controller)

- Push `issue_026_027` once, open one PR to `main` with `Closes #26`, `Closes #27`, the verification table and a note that Hop-native tests will follow #25.
- The lab `integrations_db` is kept (it will be reused for SeraSoft/airflow-dags#10).
