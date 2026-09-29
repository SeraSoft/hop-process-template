# Microsoft SQL Server support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a template-based project use Microsoft SQL Server as `integrations_db`, by adding an `MSSQLNATIVE` connection metadata and a SQL Server environment file, verified live on SQL Server 2022 with Apache Hop 2.19.0.

**Architecture:** Same per-database pattern as PostgreSQL and SQLite: `config/template-mssql.json` selects the connection `integrations_db_mssql` (`metadata/rdbms/integrations_db_mssql.json`) through `serasoft.integrations.db.connection.name`. Pipelines and workflows are not changed. Verification uses the lab harness outside the repo, extended for SQL Server.

**Tech Stack:** Apache Hop 2.19.0 (`apache/hop:2.19.0`, plugin `MSSQLNATIVE`, Microsoft `mssql-jdbc` 13.4.0 in `lib/jdbc`, MIT), SQL Server 2022 (`mcr.microsoft.com/mssql/server:2022-latest`, test container only), Liquibase 4.33.0 (`liquibase/liquibase:4.33.0`, Apache 2.0), Mailpit (`axllent/mailpit`, MIT, test SMTP sink), Docker.

**Spec:** `docs/superpowers/specs/2026-09-29-mssql-support-design.md`

---

## Background the implementer needs

- Hop 2.19 source, verified: `DatabaseMeta.getURL` → `MsSqlServerNativeDatabaseMeta.getURL` builds `jdbc:sqlserver://<host>:<port>;databaseName=<db>`; `DatabaseMeta.appendExtraOptions` appends every `EXTRA_OPTION_MSSQLNATIVE.<name>` attribute as `;<name>=<value>` and resolves variables in both name and value (`variables.resolve(value)`). So `${…}` in the extra options is expected to work; Task 2 confirms it live.
- `hop-run` exit codes: 0 success, 1 error (also `Abort` and skipped executions), 2/9 general/parameter errors.
- `v_process_instance_id` (a random UUID) is set with scope `ROOT_WORKFLOW` by `src/template/pre/init/init_process_id.hpl`, so it is visible inside the main process workflow `${serasoft.project.link.ref}/start.hwf`.
- The application-error feedback file (`prepare_feedback_file_based_on_result.hpl`, query "Get logging_details") runs only inside `send_feeback_mail.hwf`, i.e. when `serasoft.email.application.error.feedback.enabled=1`; hence the Mailpit SMTP sink.
- **Lab harness** (outside the repo, not in git): `H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test`
  - `$H/make_copy.sh` — fresh throwaway copy of this repo's working tree in `$H/copy` plus a test-only `slowtest` process (PostgreSQL `pg_sleep`).
  - `$H/run.sh <copy> <workflow> [params]` — runs `hop-run` in a throwaway container `hoptest-run` on network `airflow-lab_default`, environment `lab` = `$H/lab-env.json`; prints `RC=<exit code>`; Hop log in `<copy>/hoprun.log`.
  - `$H/q.sh "<sql>"` — PostgreSQL lab query (not used here).
- **No GPL:** every component above is MIT/Apache 2.0; the SQL Server image is used only as a throwaway test container. Do not use the `MSSQL` (jTDS, LGPL) Hop plugin.
- Commits: English, no co-author lines. Do **not** push; the controller pushes and opens the PR.

## File structure

| File | Responsibility |
|---|---|
| `metadata/rdbms/integrations_db_mssql.json` (create) | Hop connection `integrations_db_mssql`, plugin `MSSQLNATIVE`, all values from environment variables |
| `config/template-mssql.json` (create) | Template environment for SQL Server (8 DB variables + 2 encryption variables) |
| `README.md` (modify) | Environment variables table (connection names, SQL Server port, encryption variables) |
| `$H/lab-env-mssql.json`, `$H/qm.sh`, `$H/make_copy_mssql.sh`, `$H/run.sh` (lab, outside git) | SQL Server test harness |

---

### Task 1: SQL Server lab harness (outside the repo)

**Files (lab only, nothing committed):** create `$H/qm.sh`, `$H/make_copy_mssql.sh`, `$H/lab-env-mssql.json`; modify `$H/run.sh`.

- [x] **Step 1: Start SQL Server 2022 and Mailpit on the lab network**

```bash
docker run -d --name lab-mssql --network airflow-lab_default \
  -e ACCEPT_EULA=Y -e 'MSSQL_SA_PASSWORD=Lab_Mssql_2026!' \
  mcr.microsoft.com/mssql/server:2022-latest
docker run -d --name lab-mailpit --network airflow-lab_default -p 18025:8025 axllent/mailpit
for i in $(seq 1 60); do docker exec lab-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P 'Lab_Mssql_2026!' -Q "SELECT 1" >/dev/null 2>&1 && break; sleep 2; done
docker exec lab-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P 'Lab_Mssql_2026!' -Q "CREATE DATABASE integrations_db"
curl -s http://localhost:18025/api/v1/messages | head -c 80; echo
```
Expected: the `CREATE DATABASE` returns without error; Mailpit answers with JSON (`{"total":0,…`).

- [x] **Step 2: Create `integrations_db` with the repo changelog (Liquibase 4.33.0)**

```bash
docker run --rm --network airflow-lab_default \
  -v /home/enrico/repositories/serasoft/hop-process-template/db/liquibase:/liquibase/changelog:ro \
  liquibase/liquibase:4.33.0 --search-path=/liquibase/changelog --changelog-file=master.xml \
  --url="jdbc:sqlserver://lab-mssql:1433;databaseName=integrations_db;encrypt=true;trustServerCertificate=true" \
  --username=sa --password='Lab_Mssql_2026!' update 2>&1 | grep -E "Run:|successful|ERROR"
```
Expected: `Run: 16`, `Update has been successful` (or `… executed successfully`).

- [x] **Step 3: Create `$H/qm.sh`** (one SQL Server statement, rows only)

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
cat > $H/qm.sh <<'EOF'
#!/usr/bin/env bash
# Run one SQL statement on the lab SQL Server integrations_db, print rows only.
docker exec lab-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P 'Lab_Mssql_2026!' \
  -d integrations_db -h -1 -W -Q "SET NOCOUNT ON; $1"
EOF
chmod +x $H/qm.sh
$H/qm.sh "INSERT INTO config.integrations_processes (id, short_name, description, project, is_active, is_running) VALUES ('slowtest','slowtest','test only','hop-process-template','Y','N'), ('apperrtest','apperrtest','test only','hop-process-template','Y','N')"
$H/qm.sh "SELECT id FROM config.integrations_processes ORDER BY id"
```
Expected: `apperrtest`, `default`, `slowtest`.

- [x] **Step 4: Let `run.sh` take the environment file from `LAB_ENV`**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
python3 - $H/run.sh <<'PYEOF'
import sys
p=sys.argv[1]; s=open(p).read()
a='S=$(dirname "$0"); COPY=$1'
b='S=$(dirname "$0"); LAB_ENV=${LAB_ENV:-$S/lab-env.json}; COPY=$1'
c='-v "$S/lab-env.json":/env/lab-env.json:ro'
d='-v "$LAB_ENV":/env/lab-env.json:ro'
assert s.count(a)==1 and s.count(c)==1
open(p,'w').write(s.replace(a,b).replace(c,d)); print("patched")
PYEOF
```
Expected: `patched`. Without `LAB_ENV` the script behaves as before (PostgreSQL lab).

- [x] **Step 5: Create `$H/lab-env-mssql.json`** from `lab-env.json`, with the SQL Server values, the two encryption variables and the application-error email sent to Mailpit

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
python3 - $H <<'PYEOF'
import json,sys
H=sys.argv[1]; e=json.load(open(f"{H}/lab-env.json"))
set_={"serasoft.integrations.db.host":"lab-mssql","serasoft.integrations.db.port":"1433",
      "serasoft.integrations.db.user":"sa","serasoft.integrations.db.pwd":"Lab_Mssql_2026!",
      "serasoft.integrations.db.connection.name":"integrations_db_mssql",
      "serasoft.integrations.db.mssql.encrypt":"true",
      "serasoft.integrations.db.mssql.trust.server.certificate":"true",
      "serasoft.email.application.error.feedback.enabled":"1",
      "serasoft.smtp.mail.host":"lab-mailpit","serasoft.smtp.mail.port":"1025"}
names={v["name"] for v in e["variables"]}
for v in e["variables"]:
    if v["name"] in set_: v["value"]=set_[v["name"]]
for k in set_:
    if k not in names: e["variables"].append({"name":k,"value":set_[k],"description":""})
json.dump(e,open(f"{H}/lab-env-mssql.json","w"),indent=2); print("written")
PYEOF
python3 -c "import json;[print(v['name'],'=',v['value']) for v in json.load(open('$H/lab-env-mssql.json'))['variables'] if 'db.' in v['name'] or 'smtp.mail.host' in v['name'] or 'application.error.feedback' in v['name']]"
```
Expected: `written`; host `lab-mssql`, port `1433`, connection `integrations_db_mssql`, both encryption variables `true`, smtp host `lab-mailpit`, application error feedback `1`.

- [x] **Step 6: Create `$H/make_copy_mssql.sh`** (fresh copy; `slowtest` with `WAITFOR DELAY`; new `apperrtest` that records one application event for the running instance)

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
cat > $H/make_copy_mssql.sh <<'EOF'
#!/usr/bin/env bash
# Fresh copy (make_copy.sh) adapted to SQL Server: slowtest waits with WAITFOR DELAY,
# apperrtest records one application event in integrations_log_events.
set -euo pipefail
S=$(cd "$(dirname "$0")" && pwd)
"$S/make_copy.sh" >/dev/null
sed -i 's|<sql>SELECT pg_sleep(60)</sql>|<sql>WAITFOR DELAY '"'"'00:00:40'"'"'</sql>|' "$S/copy/src/project/main/slowtest/start.hwf"
grep -q "WAITFOR DELAY" "$S/copy/src/project/main/slowtest/start.hwf"
mkdir -p "$S/copy/src/project/main/apperrtest"
sed 's|WAITFOR DELAY '"'"'00:00:40'"'"'|INSERT INTO ${serasoft.integrations.db.log.schema}.integrations_log_events (id, date_event, integrations_logs_id, event_subcategory_id, event_severity_id, source_sys_code, source_sys_row_ref, event_text) VALUES ('"'"'${v_process_instance_id}-E'"'"', CURRENT_TIMESTAMP, '"'"'${v_process_instance_id}'"'"', '"'"'SYSGE001'"'"', '"'"'MEDIUM'"'"', '"'"'TEST'"'"', '"'"'row-1'"'"', '"'"'apperrtest application event'"'"')|' \
  "$S/copy/src/project/main/slowtest/start.hwf" > "$S/copy/src/project/main/apperrtest/start.hwf"
grep -q "apperrtest application event" "$S/copy/src/project/main/apperrtest/start.hwf"
chmod -R o+rwX "$S/copy"; echo "mssql copy ready: $S/copy"
EOF
chmod +x $H/make_copy_mssql.sh
$H/make_copy_mssql.sh
grep -o "<sql>[^<]*</sql>" $H/copy/src/project/main/slowtest/start.hwf $H/copy/src/project/main/apperrtest/start.hwf
```
Expected: `mssql copy ready`; slowtest `<sql>WAITFOR DELAY '00:00:40'</sql>`; apperrtest `<sql>INSERT INTO ${serasoft.integrations.db.log.schema}.integrations_log_events (…) VALUES ('${v_process_instance_id}-E', …)</sql>`.

- [x] **Step 7: Baseline (red): the template has no SQL Server connection**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf
grep -m3 -i "integrations_db_mssql" $H/copy/hoprun.log
```
Expected: `RC=1` (or another non-zero code) and log lines saying that connection `integrations_db_mssql` cannot be found. Record the exact message for the report.

No commit (lab files are outside git).

---

### Task 2: SQL Server connection metadata and environment file

**Files:** Create `metadata/rdbms/integrations_db_mssql.json`, `config/template-mssql.json`.

- [x] **Step 1: Create `metadata/rdbms/integrations_db_mssql.json`**

```json
{
  "rdbms": {
    "MSSQLNATIVE": {
      "databaseName": "${serasoft.integrations.db.name}",
      "pluginId": "MSSQLNATIVE",
      "accessType": 0,
      "hostname": "${serasoft.integrations.db.host}",
      "password": "${serasoft.integrations.db.pwd}",
      "pluginName": "MS SQL Server (Native)",
      "port": "${serasoft.integrations.db.port}",
      "usingIntegratedSecurity": false,
      "attributes": {
        "SUPPORTS_TIMESTAMP_DATA_TYPE": "Y",
        "QUOTE_ALL_FIELDS": "N",
        "EXTRA_OPTION_MSSQLNATIVE.encrypt": "${serasoft.integrations.db.mssql.encrypt}",
        "EXTRA_OPTION_MSSQLNATIVE.trustServerCertificate": "${serasoft.integrations.db.mssql.trust.server.certificate}",
        "SUPPORTS_BOOLEAN_DATA_TYPE": "Y",
        "FORCE_IDENTIFIERS_TO_LOWERCASE": "N",
        "PRESERVE_RESERVED_WORD_CASE": "Y",
        "SQL_CONNECT": "",
        "FORCE_IDENTIFIERS_TO_UPPERCASE": "N",
        "PREFERRED_SCHEMA_NAME": ""
      },
      "manualUrl": "",
      "username": "${serasoft.integrations.db.user}"
    }
  },
  "name": "integrations_db_mssql"
}
```

Validate: `python3 -m json.tool metadata/rdbms/integrations_db_mssql.json >/dev/null && echo OK` → `OK`.

- [x] **Step 2: Create `config/template-mssql.json`** (same order and descriptions as `config/template-postgresql.json`, plus the two encryption variables)

```json
{
  "variables" : [
    {
      "name" : "serasoft.integrations.db.config.schema",
      "value" : "config",
      "description" : "Name of the schema containing the configuration tables for the integrations database."
    }, {
      "name" : "serasoft.integrations.db.log.schema",
      "value" : "logs",
      "description" : "Name of schema containing the logs tables for the integrations database."
    }, {
      "name" : "serasoft.integrations.db.host",
      "value" : "localhost",
      "description" : "Name of the hosts where the integrations database is running. This can be an IP address or a hostname."
    }, {
      "name" : "serasoft.integrations.db.connection.name",
      "value" : "integrations_db_mssql",
      "description" : "Name of the connection assigned in Apache Hop for the integrations database. This is used to connect to the database during Hop Process execution."
    }, {
      "name" : "serasoft.integrations.db.name",
      "value" : "integrations_db",
      "description" : "Name of the database containing the configuration and logs tables for the integrations database."
    }, {
      "name" : "serasoft.integrations.db.port",
      "value" : "1433",
      "description" : "Port of the integrations database. This is the port where the database server is listening for connections."
    }, {
      "name" : "serasoft.integrations.db.user",
      "value" : "sa",
      "description" : "Username used to connect to the integrations database. This user must have permissions to read/write in the specified database."
    }, {
      "name" : "serasoft.integrations.db.pwd",
      "value" : "password",
      "description" : "Password used to connect to the integrations database. This user must have permissions to read/write in the specified database."
    }, {
      "name" : "serasoft.integrations.db.mssql.encrypt",
      "value" : "true",
      "description" : "SQL Server only: encrypt the connection (JDBC driver option encrypt). Values: true, false."
    }, {
      "name" : "serasoft.integrations.db.mssql.trust.server.certificate",
      "value" : "true",
      "description" : "SQL Server only: accept the server certificate without validating it (JDBC driver option trustServerCertificate). Set to false when the server certificate is trusted by the JVM. Values: true, false."
    }
  ]
}
```

Validate: `python3 -m json.tool config/template-mssql.json >/dev/null && echo OK` → `OK`.

- [x] **Step 3: Verify (green): normal run on SQL Server**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/make_copy_mssql.sh
$H/qm.sh "UPDATE config.integrations_processes SET is_active='Y', is_running='N'"
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf
grep -E "Terminated Successfully\] \(result" $H/copy/hoprun.log
echo "flag=$($H/qm.sh "SELECT is_running FROM config.integrations_processes WHERE id='default'") last=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='default' ORDER BY date_started DESC")"
```
Expected: `RC=0`, `Terminated Successfully] (result=[true])`, `flag=N last=T`.

If it fails for a SQL incompatibility (error in a template pipeline/workflow, not in the new files): **stop and report the exact error to the controller**; do not change pipelines or workflows.

- [x] **Step 4: Verify that the encryption variables reach the driver**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
python3 - $H <<'PYEOF'
import json,sys
H=sys.argv[1]; e=json.load(open(f"{H}/lab-env-mssql.json"))
for v in e["variables"]:
    if v["name"]=="serasoft.integrations.db.mssql.trust.server.certificate": v["value"]="false"
json.dump(e,open(f"{H}/lab-env-mssql-strict.json","w"),indent=2)
PYEOF
LAB_ENV=$H/lab-env-mssql-strict.json $H/run.sh $H/copy main.hwf
grep -m2 -o -i "PKIX[^\"]*\|could not establish a secure connection[^\"]*" $H/copy/hoprun.log
```
Expected: non-zero `RC` and a certificate error (`PKIX path building failed` / `could not establish a secure connection … SSL`): the variable was resolved and passed to the driver, since the default environment (Step 3) connects. If Step 3 passed and this run also connects, the variables are not applied: switch to the spec fallback — set `"manualUrl": "jdbc:sqlserver://${serasoft.integrations.db.host}:${serasoft.integrations.db.port};databaseName=${serasoft.integrations.db.name};encrypt=${serasoft.integrations.db.mssql.encrypt};trustServerCertificate=${serasoft.integrations.db.mssql.trust.server.certificate}"`, remove the two `EXTRA_OPTION_MSSQLNATIVE.*` attributes, and repeat Steps 3–4.

- [x] **Step 5: Commit**

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
git add metadata/rdbms/integrations_db_mssql.json config/template-mssql.json
git commit -m "Add SQL Server connection metadata and environment file

integrations_db_mssql uses the MSSQLNATIVE plugin (Microsoft JDBC driver,
shipped with Hop). Host, port, database and credentials come from the usual
serasoft.integrations.db.* variables; encrypt and trustServerCertificate
from two new SQL Server-only variables. Verified on SQL Server 2022 with
Hop 2.19: normal run exit 0 / status T; trustServerCertificate=false fails
on the self-signed certificate, so the variables reach the driver.

Refs #35"
```


---

### Task 3: Scenario battery on SQL Server

**Files:** none (verification only). If a scenario fails because of a template pipeline/workflow, stop and report it; no fix without the user's approval.

- [x] **Step 1: Application error (status `X`, event read back, email with `logs.zip`)**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/make_copy_mssql.sh
curl -s -X DELETE http://localhost:18025/api/v1/messages >/dev/null
$H/qm.sh "UPDATE config.integrations_processes SET is_active='Y', is_running='N'"
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf p_base_process_name=apperrtest
echo "last=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='apperrtest' ORDER BY date_started DESC") events=$($H/qm.sh "SELECT COUNT(*) FROM logs.integrations_log_events e JOIN logs.integrations_logs l ON l.id=e.integrations_logs_id WHERE l.integrations_processes_id='apperrtest'")"
curl -s http://localhost:18025/api/v1/messages | python3 -c "import json,sys;m=json.load(sys.stdin)['messages'];print(len(m),[x['Subject'] for x in m],[x['Attachments'] for x in m])"
ID=$(curl -s http://localhost:18025/api/v1/messages | python3 -c "import json,sys;print(json.load(sys.stdin)['messages'][0]['ID'])")
curl -s http://localhost:18025/api/v1/message/$ID | python3 -c "import json,sys;print([a['FileName'] for a in json.load(sys.stdin)['Attachments']])"
```
Expected: `RC=0`; `last=X events=1`; one message whose subject ends with `Terminated successfully with application exceptions.`, with a `logs.zip` attachment that contains `execution_file_apperrtest_…csv` and the execution log. Then check the CSV content:
```bash
PART=$(curl -s http://localhost:18025/api/v1/message/$ID | python3 -c "import json,sys;print([a['PartID'] for a in json.load(sys.stdin)['Attachments'] if a['FileName']=='logs.zip'][0])")
curl -s -o /home/enrico/.claude/jobs/229abd6d/tmp/logs.zip http://localhost:18025/api/v1/message/$ID/part/$PART
python3 -c "import zipfile;z=zipfile.ZipFile('/home/enrico/.claude/jobs/229abd6d/tmp/logs.zip');print(z.namelist());[print(z.read(n).decode()) for n in z.namelist() if n.endswith('.csv')]"
```
Expected: a row with `SYSTEM EXCEPTION`, `GENERIC ERROR`, severity `5`, `TEST`, `row-1`, `apperrtest application event` (this is the "Get logging_details" query, with its three left joins, running on SQL Server).

- [x] **Step 2: Lock present**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
$H/qm.sh "UPDATE config.integrations_processes SET is_active='Y', is_running='Y' WHERE id='default'"
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf
grep -o "ERROR: SKIPPED[^\"]*" $H/copy/hoprun.log | head -1
echo "flag=$($H/qm.sh "SELECT is_running FROM config.integrations_processes WHERE id='default'") last=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='default' ORDER BY date_started DESC")"
```
Expected: `RC=1`; `ERROR: SKIPPED: process 'default' is locked by an instance started at …`; `flag=Y last=L`.

- [x] **Step 3: Process paused**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
N0=$($H/qm.sh "SELECT COUNT(*) FROM logs.integrations_logs WHERE integrations_processes_id='default'")
$H/qm.sh "UPDATE config.integrations_processes SET is_running='N', is_active='N' WHERE id='default'"
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf
grep -o "ERROR: SKIPPED[^\"]*" $H/copy/hoprun.log | head -1
echo "rows before=$N0 after=$($H/qm.sh "SELECT COUNT(*) FROM logs.integrations_logs WHERE integrations_processes_id='default'")"
$H/qm.sh "UPDATE config.integrations_processes SET is_active='Y', is_running='N'"
```
Expected: `RC=1`; `ERROR: SKIPPED: process 'default' is not active`; `before` = `after`.

- [x] **Step 4: Killed run, then `release_lock.hwf`**

```bash
H=/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test
( LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf p_base_process_name=slowtest > $H/slow.out 2>&1 & )
for i in $(seq 1 40); do st=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='slowtest' ORDER BY date_started DESC"); [ "$st" = "R" ] && break; sleep 2; done
docker kill -s KILL hoptest-run >/dev/null; sleep 3
echo "stale: flag=$($H/qm.sh "SELECT is_running FROM config.integrations_processes WHERE id='slowtest'") last=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='slowtest' ORDER BY date_started DESC")"
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy src/template/commons/tools/locks/release_lock.hwf p_base_process_name=slowtest
echo "released: flag=$($H/qm.sh "SELECT is_running FROM config.integrations_processes WHERE id='slowtest'") last=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='slowtest' ORDER BY date_started DESC")"
LAB_ENV=$H/lab-env-mssql.json $H/run.sh $H/copy main.hwf p_base_process_name=slowtest
echo "next: last=$($H/qm.sh "SELECT TOP 1 proc_status FROM logs.integrations_logs WHERE integrations_processes_id='slowtest' ORDER BY date_started DESC")"
```
Expected: `stale: flag=Y last=R`; release `RC=0`, `released: flag=N last=K`; next run `RC=0` (after ~40 s), `next: last=T`.

- [x] **Step 5: Report** the RC and outputs of Steps 1–4 to the controller (they go into the PR body). No commit.

---

### Task 4: README

**Files:** Modify `README.md` (environment variables table).

- [x] **Step 1: Update the table rows and add the two variables** — run from the repo root (each anchor must be found exactly once):

```bash
cd /home/enrico/repositories/serasoft/hop-process-template
python3 - README.md <<'PYEOF'
import sys
p=sys.argv[1]; s=open(p).read()
def rep(a,b):
    global s
    assert s.count(a)==1, a[:80]; s=s.replace(a,b)
rep("|serasoft.integrations.db.connection.name|Name of the connection assigned in Apache Hop for the integrations database. This is used to connect to the database during Hop Process execution.|`integrations_db`|",
    "|serasoft.integrations.db.connection.name|Name of the connection assigned in Apache Hop for the integrations database. This is used to connect to the database during Hop Process execution. One of `integrations_db_postgres`, `integrations_db_mssql`, `integrations_db_sqlite` (environment files `config/template-postgresql.json`, `config/template-mssql.json`, `config/template-sqlite.json`).|`integrations_db_postgres`|")
rep("|serasoft.integrations.db.port|Port of the integrations database. This is the port where the database server is listening for connections|`5432`|",
    "|serasoft.integrations.db.port|Port of the integrations database. This is the port where the database server is listening for connections (`1433` for SQL Server)|`5432`|")
rep("|serasoft.integrations.db.pwd|Password used to connect to the integrations database. This user must have permissions to read/write in the specified database|`password`|\n",
    "|serasoft.integrations.db.pwd|Password used to connect to the integrations database. This user must have permissions to read/write in the specified database|`password`|\n"
    "|serasoft.integrations.db.mssql.encrypt|SQL Server only: encrypt the connection (JDBC driver option `encrypt`)|`true`|\n"
    "|serasoft.integrations.db.mssql.trust.server.certificate|SQL Server only: accept the server certificate without validating it (JDBC driver option `trustServerCertificate`). Set to `false` when the server certificate is trusted by the JVM, e.g. issued by a trusted CA|`true`|\n")
open(p,'w').write(s); print("patched")
PYEOF
grep -n "db.connection.name\|db.port\|db.mssql" README.md | cut -c1-150
```
Expected: `patched`; the four rows shown.

- [x] **Step 2: Commit**

```bash
git add README.md
git commit -m "README: SQL Server connection and encryption variables

Refs #35"
```

---

## After the tasks (controller)

- Update the issue checklist, push the branch (spec, plan and the commits above), open the PR (`Closes #35`) with the Task 2/3 results.
- Lab cleanup after the user's review: `docker rm -f lab-mssql lab-mailpit`; remove `$H/lab-env-mssql-strict.json`.
