# Hop's Process Template

Apache Hop Process template is a mature seed that you can use as a base to develop your Apache Hop processes the correct way.

Features implemented and enforced by the template are:

- **Clear directory structure** for code and configuration files (see "Project structure"): a Hop project gets a predefined structure to manage its processes and configuration files in a single bundle that can easily be distributed.
- **Single process execution**: if an instance of a process is already running, a new instance of the same process does not start (see "Process statuses and stale locks").
- **Single point for errors' management**: as a good methodological approach the template tries to force the management of events and errors in a single point
- **Event logs** structured for operational analysis

We adopt Liquibase in order to keep `config` and `logs` tables up-to-date.

## Prerequisites
#### Liquibase installation 

To be able to create/update the support database conventionally named *integrations_db*, you must install liquibase on your computer. To properly install liquibase on your computer please refer to the [Liquibase installation procedure](https://docs.liquibase.com/start/install/home.html).

- The template is verified with **Liquibase 4.33.0** (Apache 2.0 license), the version used by the test lab. Liquibase 5.x changed license and is being evaluated (#76): use 4.33.0.
- Liquibase 4.33.0 bundles the JDBC drivers for PostgreSQL, Microsoft SQL Server and SQLite: nothing else to download.
- The installers include their own Java; the ZIP/TAR packages need Java on the computer (Java 8 at least, an LTS version 11, 17 or 21 recommended).

Without installing anything, the official Docker image runs the same commands: mount `db/liquibase` and pass the options after the image name, for example from the project root:

```
docker run --rm -v "$PWD/db/liquibase":/liquibase/changelog:ro liquibase/liquibase:4.33.0 \
    --search-path=/liquibase/changelog --changelog-file=master.xml \
    --url="jdbc:postgresql://<host>:5432/integrations_db" --username=<user> --password=<password> \
    update
```

`localhost` inside the container is the container itself: use the host name of the database server (or `--network host` on Linux for a database on the same machine).

## Getting started
### Process template setup

A new project gets the template from a release of hop-process-template, in one of two ways.

**With the Serasoft projects plugin for Hop GUI** (a private Serasoft plugin, `hop-process-template-plugins`): create the project with the **Apply Serasoft Template** option. The plugin downloads the release ZIP named by `template.download.url` in `serasoft-hop-config.json`, in the Hop configuration folder; set it to the wanted release, e.g. `https://github.com/SeraSoft/hop-process-template/releases/download/3.3.0/hop-process-template-v3.3.0.zip`. The ZIP does not record the template version: once the project is a Git repository, record it with a one-off adoption from the same release, run from a checkout of hop-process-template (see "Adopting a project that already holds template files"), then commit:

```
tools/serasoft-sync.sh --tag 3.3.0 --dest ../myproject --adopt-from 3.3.0
```

**Without the plugin**: create an empty Git repository, copy the template files into it with `tools/serasoft-sync.sh` from a checkout of hop-process-template (see "Creating or updating a project"), and register the project in Hop, which writes `config/project-config.json`:

```
tools/serasoft-sync.sh --tag 3.3.0 --dest ../myproject
hop-conf.sh -pc -p myproject -ph /path/to/myproject -pf config/project-config.json
```

In both cases:

1. Check the project `.gitignore`: it must not hide template-owned files (see the recommendations in "Checking a project"), then commit.
2. Create the integrations database (see "Support database creation") and declare the processes (see "Process identity").
3. Write the project environment files (see "Environments").
4. Add the processes under `src/project/main/<short name>/start.hwf` (see "Project structure").
5. Run a process with `main.hwf` and its short name:

```
hop-run.sh -j myproject -e myproject-dev -r local -f /path/to/myproject/main.hwf -p p_base_process_name=<short name>
```

### Project structure

| Path | Owner | Content |
|---|---|---|
| `main.hwf` | template | the only root workflow: pre-phase, the process named by `p_base_process_name`, post-phase, feedback emails |
| `src/template/` | template | pre- and post-phase, locks, logging, mail tools, `check_state.hwf`, `release_lock.hwf`; never edited in a project |
| `src/project/main/<short name>/` | project | one folder per process; `start.hwf` is the entry point that `main.hwf` runs |
| `src/project/commons/` | project | workflows and pipelines shared by the processes |
| `config/template-*.json` | template | template variables and database defaults (see "Environments") |
| `config/project-config.json` | project | the Hop project configuration |
| `config/<project>-<env>.json`, `config/<short name>.properties` | project | project variables per environment, optional variables per process |
| `config/env/<env>.list` | project | load order of the environment files, for the Serasoft Airflow platform and `tools/serasoft-register-env.sh` / `tools/serasoft-register-env.ps1` |
| `metadata/` | template and project | Hop metadata: the integrations database connections and run configurations are template-owned, the project adds its own |
| `db/liquibase/`, `db/sqlite/data/` | template | changelog of the integrations database and SQLite seeds |
| `tools/` | template | `serasoft-verify.sh`, `serasoft-register-env.sh`, `serasoft-register-env.ps1` |
| `SERASOFT_VERSION`, `SERASOFT_MANIFEST.sha256` | template | version and checksums of the template files (see "Template updates") |

To add a process: create `src/project/main/<short name>/start.hwf` (the template repository has a minimal example in `src/project/main/default/start.hwf`), declare the short name in `config.integrations_processes`, and put its own variables, if any, in `config/<short name>.properties`.

### Support database creation
A single changelog, `db/liquibase/master.xml`, creates the support database on PostgreSQL, Microsoft SQL Server and SQLite. Run Liquibase from the `db/liquibase` directory; a properties file for each database is provided there (`liquibase-postgresql.template`, `liquibase-mssql.properties`, `liquibase-sqlite-config.properties`, `liquibase-sqlite-logs.properties`) as a reference.

`db/liquibase/**` is owned by the template: do not edit those files in a project (a template update overwrites them and `tools/serasoft-verify.sh` fails on a modified or extra file). Pass the actual `url`, `username` and `password` on the command line, as in the examples below, or keep a project-owned defaults file **outside** `db/liquibase/` (e.g. `config/liquibase-<env>.properties`; do not commit it when it holds credentials) with `changelogFile=master.xml`, `url`, `username` and `password`, and use it with `--defaults-file`, adding `--search-path` so that Liquibase still finds the changelog (both are global options: put them before the command):

```powershell
liquibase --defaults-file="../../config/liquibase-dev.properties" --search-path="." update
```

Remember, in both cases, to use the actual `url`, `username` and `password`.
#### Database creation
In case of brand new database (fresh installation)

```powershell
liquibase update \
    --url="jdbc:postgresql://localhost:5432/integrations_db" \
    --changeLogFile="master.xml" \
    --username="postgres" \
    --password="password" 
```

On Microsoft SQL Server the database must already exist; the changelog creates the `config` and `logs` schemas:

```powershell
liquibase update \
    --url="jdbc:sqlserver://localhost:1433;databaseName=integrations_db;encrypt=true;trustServerCertificate=true" \
    --changeLogFile="master.xml" \
    --username="sa" \
    --password="password"
```

SQLite has no schemas: `config` and `logs` tables live in two database files (`db/sqlite/data/integrations_db.config` and `integrations_db.logs`, attached as schemas by the `integrations_db_sqlite` Hop connection). Update each file with its properties file, which sets the matching label filter (`config` or `logs`):

```powershell
liquibase update --defaults-file="liquibase-sqlite-config.properties"
liquibase update --defaults-file="liquibase-sqlite-logs.properties"
```

#### Database update
While, if your database already exists (existing environments):

```powershell
liquibase changelogSync \
    --url="jdbc:postgresql://localhost:5432/integrations_db" \
    --changeLogFile="master.xml" \
    --username="postgres" \
    --password="password"
```

PostgreSQL databases created with the former `master-postgresql.xml` changelog have its name recorded in `DATABASECHANGELOG`, so Liquibase would try to run `master.xml` again and fail on the existing tables. Liquibase records the changelog path as it was passed on the command line, so check first how it was recorded (e.g. `master-postgresql.xml` or `changelog/master-postgresql.xml`):

```sql
SELECT filename, count(*) FROM databasechangelog GROUP BY filename;
```

Before the first `update` with `master.xml`, record the new name once:

```sql
UPDATE databasechangelog SET filename = 'master.xml'
WHERE filename = 'master-postgresql.xml' OR filename LIKE '%/master-postgresql.xml';
```

Then `liquibase status` (same options as `update`) must report the database as up to date.

#### Database managed by the customer: SQL scripts

When the customer's DBA creates the database and prefers SQL scripts to running Liquibase, Liquibase generates the script without connecting to any database (offline mode). From the project root, writing outside `db/liquibase/` (template-owned: `tools/serasoft-verify.sh` fails on extra files there), one CSV per database (e.g. per environment):

```
liquibase --search-path=db/liquibase --changelog-file=master.xml \
    --url="offline:postgresql?outputLiquibaseSql=all&changeLogFile=db/integrations_db-prod.csv" \
    --output-file=db/integrations_db-postgresql.sql \
    update-sql
```

(`offline:mssql` for Microsoft SQL Server: the script is split in `GO` batches, run it with `sqlcmd`.) The script creates the `config` and `logs` schemas, the template tables with their initial rows (e.g. the `MEDIUM` severity) and Liquibase's `databasechangelog` table with one row per applied change. The DBA runs it with the usual tools, for example `psql -v ON_ERROR_STOP=1 -f integrations_db-postgresql.sql`.

- Keep the `databasechangelog` rows (`outputLiquibaseSql=all`): with them the database records which template changes it has received, `liquibase status` reports it as up to date, and later template versions can be applied either by Liquibase or by a new script.
- Commit the CSV (`db/integrations_db-prod.csv` above) in the project repository, but only once the script has been applied: the offline mode writes there the changes it put in the script. For a later template version, run the same command with the same CSV: the new script holds only the changes the database does not have yet (an unchanged template gives an empty script). Alternatively, `update-sql` with the real connection (`--url=jdbc:…`) computes the differences from the database itself.
- The script does not create the database, the user Hop connects with, or its grants: they are the DBA's choice. Hop's user needs to read and write the tables of `config` and `logs`.
- The project rows (processes, event categories) are not in the script: run the project seed (e.g. `db/seed/<project>_config.sql`) after it.

## Process identity

A process is identified everywhere by its **short name**, the `short_name` column of `config.integrations_processes`. The short name is:

- the value of `p_base_process_name` when the process is started, checked or unlocked (`main.hwf`, `check_state.hwf`, `release_lock.hwf`);
- the name of its folder, `src/project/main/<short name>/`, whose `start.hwf` is the entry point (see `serasoft.project.link.ref`);
- the name of its optional variables file, `config/<short name>.properties`.

The `id` column is internal: it is the key referenced by `logs.integrations_logs.integrations_processes_id` and can be any unique value, for example a UUID. Before 3.2.0 the pre-phase looked the process up by `id`, so `id` and `short_name` had to be equal; since 3.2.0 they are independent.

To declare a process:

```sql
INSERT INTO config.integrations_processes (id, short_name, description, project, is_active, is_running)
VALUES ('<unique id>', '<short name>', '<description>', '<project>', 'Y', 'N');
```

## Environments

The environment of a template-based project is a list of configuration files read in this order, a later file overriding an earlier one:

1. `config/template-env.json`: the template variables and their defaults (template-owned, never edited);
2. `config/template-<database>.json`, with `<database>` one of `postgresql`, `mssql`, `sqlite` (template-owned, never edited);
3. one project file per environment, e.g. `config/<project>-<environment>-env.json`: the project's own variables and the real values of the `serasoft.*` variables for that environment (database host and credentials, SMTP, mail addresses). Keep the files with credentials out of Git.

```
hop-conf.sh -ec -e prod -ep myproject \
  -eg /opt/projects/myproject/config/template-env.json,/opt/projects/myproject/config/template-postgresql.json,/etc/hop/myproject-prod-env.json
```

**The order matters.** When a variable is defined in more than one file, the value of the file read last wins. Keep the template files first, then the project file, and the credentials last: a project file listed before `config/template-env.json` would be silently overridden by the template defaults. For projects run by the Serasoft Airflow platform the list is the manifest `config/env/<env>.list` (one path per line, in load order, the credentials as `/run/secrets/<name>` on the last line):

```
config/template-env.json
config/template-postgresql.json
config/<project>-<env>.json
/run/secrets/<project>_<env>
```

`tools/serasoft-register-env.sh` registers the same list, in the same order, for executions started by cron (see "Running with cron (`hop_runner.sh`)").

Never add project variables to the template files: `tools/serasoft-sync.sh` overwrites them at every template update and `tools/serasoft-verify.sh` reports them as modified.

## Process parameters (`p_process_params`)

`main.hwf` declares only the template parameters: `p_base_process_name`, `p_log_filename` and `p_process_params`. The values specific to a process are passed through `p_process_params`:

```
hop-run -j <project> -e <environment> -r local -f '${PROJECT_HOME}/main.hwf' \
  -p 'p_base_process_name=<short name>,p_process_params=p_period_type=S;p_reference_date=20261031'
```

- **Format**: `key=value` pairs separated by `;`. Spaces around keys and values are removed, empty pairs (for example a trailing `;`) are ignored, and the value is everything after the first `=` (`p_filter=a=b` gives `a=b`).
- **Limits**: a value cannot contain `;` (the pair separator). By default it cannot contain `,` either, because `hop-run -p` separates parameters with commas: see "Values with commas" below.
- **Keys** must match `^[A-Za-z_][A-Za-z0-9_.]*$` and appear once.
- Each pair becomes a **variable of the root workflow**: `start.hwf` and everything it runs see it as `${key}`. The pre-phase logs the names of the keys it set (`p_process_params: set p_period_type, p_reference_date`), never their values.
- **Logging of rejected entries**: a rejected entry is logged as given, so it may contain a value.
- **Reserved names**: keys can override any variable, including template ones such as `p_base_process_name` or `PROJECT_HOME`: do not use template variable names.
- **Precedence** (the last one wins): environment files → `config/<short name>.properties` → `p_process_params`. Put the defaults of a process in its `.properties` file and override them per execution with `p_process_params`.
- **Why not a plain `-p key=value`**: `hop-run` turns a `-p` key that `main.hwf` does not declare into a variable of the root workflow, so `-p p_period_type=S` also reaches `start.hwf`. But the pre-phase loads `config/<short name>.properties` afterwards and overwrites it: a key that is also in the `.properties` file keeps the file's value. `p_process_params` is set after the `.properties` file, validates its entries and logs only their keys.
- **Errors**: an invalid entry stops the execution in the pre-phase, before the process starts, with exit code `1` and the message `ERROR: invalid p_process_params entry '<entry>': <reason>`, where the reason is `missing '='`, `invalid key '<key>'` or `key '<key>' given more than once`.
- **Do not declare these keys as parameters** of `start.hwf` or of the workflows and pipelines it runs: since Hop 2.20 a declared parameter with a default ignores a variable of the same name set by the caller (apache/hop#8101), so the value passed in `p_process_params` would be lost. Use them as plain variables.

From cron, quote the whole `-p` value so that the shell does not split it on `;`:

```
0 6 * * * /opt/hop/hop-run.sh -j myproject -e prod -r local -f '${PROJECT_HOME}/main.hwf' -p 'p_base_process_name=load_sales,p_process_params=p_period_type=M'
```

From an orchestrator (e.g. Apache Airflow), pass `p_process_params` like any other `-p` parameter of `main.hwf`.

### Values with commas

To pass a list such as `operations.to.import=972,15004,763,10282`, change the separator of the `-p` pairs with `-ps`, so that `hop-run` does not split the value on its commas:

```
hop-run -j <project> -e <environment> -r local -f '${PROJECT_HOME}/main.hwf' -ps '#' \
  -p 'p_base_process_name=<short name>#p_process_params=operations.to.import=972,15004,763,10282'
```

The process receives `${operations.to.import}` = `972,15004,763,10282`. Do not use `;` as the `-ps` separator (it separates the pairs of `p_process_params`), and avoid regular-expression characters such as `|`: Hop 2.16 uses the separator as a regular expression. Wrapping the value in double quotes (`-p 'key="a,b"'`) keeps the commas only from Hop 2.19 on; on Hop 2.16 use `-ps`.

## Template updates

`serasoft-sync.sh` and `serasoft-verify.sh` need Bash 4+ and GNU coreutils: Linux, WSL, or Git Bash on Windows (on macOS install GNU coreutils).

A project gets the template files from an **annotated release tag** of hop-process-template with `tools/serasoft-sync.sh`, and checks them with `tools/serasoft-verify.sh`. The project does not share the template's Git history.

### Who owns what

| Category | Paths | Sync | Verify |
|---|---|---|---|
| Template | `main.hwf`, `src/template/**`, `config/template-*.json`, `metadata/rdbms/integrations_db_*.json`, `metadata/workflow-log/workflow_log.json`, `metadata/pipeline-run-configuration/local.json`, `metadata/workflow-run-configuration/local.json`, `db/liquibase/**`, `tools/serasoft-verify.sh`, `tools/serasoft-register-env.sh`, `tools/serasoft-register-env.ps1`, and this README as `src/template/README.md` | copied, overwritten | checked |
| SQLite seed | `db/sqlite/data/integrations_db`, `integrations_db.config`, `integrations_db.logs` | copied only when missing, never overwritten | not checked |
| Project | everything else: `src/project/**`, `config/project-config.json`, the project environment files, `README.md`, `.gitignore`, … | never touched | not checked |

Two files at the root of the project record the version: `SERASOFT_VERSION` (`<tag> <commit>`) and `SERASOFT_MANIFEST.sha256` (one `sha256sum` line per template file).

### Creating or updating a project

From a checkout of hop-process-template with the tags (`git fetch --tags`), on a clean checkout of the project (a dedicated branch, e.g. `template/3.2.0`):

```
tools/serasoft-sync.sh --tag 3.2.0 --dest ../myproject
```

The sync:

- refuses an unknown or lightweight tag, a destination that is not the root of a Git work tree or has uncommitted changes;
- copies the template files from the tag (never from the working copy), refusing to overwrite a project file: a template file may already exist in the project only if the previous manifest lists it (a first sync without `--adopt-from` also refuses extra files in `src/template/` and `db/liquibase/`);
- removes the template files of the previous version that the new one no longer has;
- copies the SQLite seed files only when missing, and prints `WARNING: kept local <file>` when a local one differs;
- prints `WARNING: db/liquibase/master.xml changed: run liquibase update …` when the database changelog changed: update every project database (see "Support database creation");
- prints `WARNING: ignored by .gitignore in <dest>: <files> …` when the project `.gitignore` hides written template files or seeds: add them with `git add -f` or un-ignore them (see the recommendations below);
- rewrites `SERASOFT_VERSION` and `SERASOFT_MANIFEST.sha256` and prints `OK serasoft-sync tag=… commit=… added=… changed=… removed=… adopted=… forced=…`.

It does not commit: review the diff, commit (e.g. `Template 3.2.0`), open the pull/merge request with the release notes of the tag (`git tag -n99 3.2.0` in the template).

### Adopting a project that already holds template files

A project created before the sync existed (template 2.x copied by hand, or a 1.0.x project after its migration) has template files but no `SERASOFT_MANIFEST.sha256`: the plain sync refuses it. Give the version the project starts from:

```
tools/serasoft-sync.sh --tag 3.2.0 --dest ../myproject --adopt-from 2.1.2
tools/serasoft-sync.sh --tag 3.2.0 --dest ../myproject --adopt-from auto
```

- Every template file of the project is compared with the same file in the starting tag (`2.1.2`, which may be a lightweight tag). Identical files are adopted and replaced by the new version; the files of the starting tag that the new version no longer has (for example `config/default-*.json`, `db/liquibase/master-postgresql.xml`) are removed.
- Files that differ from the starting tag, and files in `src/template/` or `db/liquibase/` that the starting tag does not have, are **local changes**: the sync lists them and stops. Move the project's own content out of the template files, then run again: typical local changes are edited `db/liquibase/*.properties` files (keep them in a project-owned file outside `db/liquibase/`, see "Support database creation") and project variables added to `config/template-env.json` (move them to the project environment file, see "Environments"). A project file at a path the new version owns (e.g. `config/template-env.json`) is refused too; or add `--force` to overwrite or remove them.
- `--adopt-from auto` picks the tag with the most identical files and prints it (`adopt-from auto: 2.1.2 (5/6 files identical)`): check it before committing.
- When `db/liquibase/master.xml` differs from the starting tag the sync prints a warning: for databases created with `master-postgresql.xml` follow "Database update" before running `liquibase update`.
- A file adopted and then dismissed (because the new version no longer has it) is counted in both `adopted` and `removed` in the summary line.
- `--adopt-from` is refused when the project already has a manifest.

### Projects in a subfolder

A Hop project may live in a subfolder of its repository (e.g. `etl/`, next to other content). Give that folder as `--dest`: the template files, `SERASOFT_VERSION` and `SERASOFT_MANIFEST.sha256` go there, nothing outside it is touched. The sync still refuses a work tree with uncommitted changes anywhere, so that its diff can be reviewed on its own:

```
tools/serasoft-sync.sh --tag 3.4.0 --dest ../myrepo/etl
```

Run the verify from the subfolder (in CI: `cd etl && tools/serasoft-verify.sh`). On the Serasoft Airflow platform, set `path: etl` for the project in `config/hop_projects.yaml` (SeraSoft/airflow-dags): the distribution copies only that subfolder.

The registration scripts name the Hop project after its folder by default: for a project in `etl/` pass the real name, `tools/serasoft-register-env.sh --project <name>` or `tools\serasoft-register-env.ps1 -Project <name>` (the same name as the `hop_projects.yaml` entry on the platform).

### Checking a project

From the project root, by hand or in its CI:

```
tools/serasoft-verify.sh
```

It fails (exit code `1`, offending files listed) when a template file was modified or removed, when `src/template/` or `db/liquibase/` hold a file the manifest does not list (or are symlinks), or when `SERASOFT_VERSION` is missing or empty. A GitLab CI job:

```yaml
serasoft-verify:
  image: alpine:3.20
  script:
    - apk add --no-cache bash coreutils
    - tools/serasoft-verify.sh
```

Recommended in the project repository:

- a code-owner or approval rule on `main.hwf`, `src/template/`, `config/template-*.json`, `db/liquibase/`, `SERASOFT_*`, and the template metadata files (`metadata/rdbms/integrations_db_*.json`, `metadata/workflow-log/workflow_log.json`, `metadata/pipeline-run-configuration/local.json`, `metadata/workflow-run-configuration/local.json`), so that template files change only through a template update;
- a `.gitattributes` keeping the template files with LF line endings (with `core.autocrlf=true` a Windows checkout converts them to CRLF and a local verify fails):

  ```
  *.hwf  text eol=lf
  *.hpl  text eol=lf
  *.json text eol=lf
  *.xml  text eol=lf
  *.sh   text eol=lf
  SERASOFT_* text eol=lf
  src/template/** text eol=lf
  db/liquibase/** text eol=lf
  ```

- a `.gitignore` with at least `logs/`, `temp/` and the environment files that hold credentials. It must not ignore template-owned paths: after a rule such as `config/*` add `!config/template-*.json` (and likewise for `db/sqlite/data/*` seeds), otherwise the written files are left out of the commit and the verify fails on a fresh clone.

## Running with cron (`hop_runner.sh`)

The Serasoft Airflow platform reads `config/env/<env>.list` at every run. On a machine where the project is started by cron with `hop_runner.sh` (SeraSoft/useful-scripts), the project and the environment must be registered in the installation's `hop-config.json` first. `tools/serasoft-register-env.sh` does it from the same manifest:

```
export HOP_HOME=/opt/hop
<project>/tools/serasoft-register-env.sh --env prod
```

- A project in a subfolder of its repository (see "Projects in a subfolder") has not been tried with `hop_runner.sh`.
- Each `/run/secrets/<name>` line of the manifest becomes `/etc/serasoft/secrets/<name>` (the folder the platform uses on its SSH targets; change it with `--secrets-dir`). Keep those files readable only by the user that runs Hop (`chmod 600`).
- The project is registered with the name of its folder (`--project` to change it) and `config/project-config.json`; the environment is named `<project>-<env>` (`--hop-env` to change it), because environment names are shared by every project of the installation.
- Every manifest line is checked first (missing or unreadable file, comma in a path, absolute path outside `/run/secrets/`): on error nothing is registered (exit code `1`; `64` for an unknown option or an invalid name).
- The files are registered in the order of the manifest, which is the load order (a later file overrides an earlier one): keep the template files first and the secret last (see "Environments").
- Keep the project folder path ASCII and without `&`, `^`, `%`: the script refuses the latter (`cmd.exe` would interpret them), and non-ASCII characters may not survive the Windows console code pages.

Re-run it after a change of the manifest: the existing environment gets the new file list. A project already registered with another folder is an error. If `hop-conf` fails after the project was registered, fix the cause and re-run: the project is kept and the environment is created.
- `hop-conf` writes the `hop-config.json` of the installation (`$HOP_HOME/config`, or `HOP_CONFIG_FOLDER` when set): run the script with the same `HOP_HOME` and `HOP_CONFIG_FOLDER` that `hop_runner.sh` uses.

Then:

```
hop_runner.sh main.hwf -prj:<project> -env:<project>-prod -param:p_base_process_name=<process>
```

## Registering a local environment on Windows

For local development with Hop GUI on Windows, `tools/serasoft-register-env.ps1` registers the project and one of its environments from `config/env/<env>.list`, like `tools/serasoft-register-env.sh` does on Linux. It runs on Windows PowerShell 5.1 (on every Windows 10/11) and PowerShell 7.

1. **Secrets file.** Each `/run/secrets/<name>` line of the manifest is a Hop environment file with the variables of `config/secrets-example.json` and their real values, kept outside the repository in `%USERPROFILE%\.serasoft\secrets\<name>` or `<name>.json` (e.g. `C:\Users\me\.serasoft\secrets\myproject_local.json`):

   ```json
   { "variables": [ { "name": "myproject.db.pwd", "value": "..." } ] }
   ```

2. **Close Hop GUI**: it keeps the configuration in memory and may write `hop-config.json` again when it exits, dropping the registration.
3. **Register**, from the project folder:

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File tools\serasoft-register-env.ps1 -Env local -HopHome C:\hop
   ```

   `-ExecutionPolicy Bypass` applies to this run only and changes no system setting. `-HopHome` can be left out when `HOP_HOME` is set. Other parameters: `-Project <name>` (default: the project folder name; pass it for a project in a subfolder such as `etl/`), `-HopEnv <name>` (default: `<project>-<env>`), `-SecretsDir <folder>`.
4. Open Hop GUI and select the project and the environment printed by the script.

Keep the project folder path ASCII and without `&`, `^`, `%`: the script refuses the latter (`cmd.exe` would interpret them), and non-ASCII characters may not survive the Windows console code pages.

Re-run it after a change of the manifest: the environment gets the new file list. It stops before touching `hop-config.json` when a file of the manifest is missing, and when the project is already registered with another folder (use `-Project`).

## Migrating a template 1.0.x project

`tools/serasoft-migrate-1x.py` migrates a project built on template 1.0.x (`src/pre/main_pre_job.hwf`, `src/main/`, `config/project-config.json`) to a template tag and to the Serasoft Airflow platform layout. It works on a clean checkout of the project, creates the branch `migration/template-<tag>` and makes one commit per phase. It never pushes: review the branch, then push and open the merge request yourself.

After a read-only analysis (phase 0, nothing written) the phases and their commits are:

| Phase | Commit message |
|---|---|
| 1 structure: processes and project folders moved under `src/project/` (`start.hwf` per process) | `Migration: project structure for template <tag>` |
| 2 rewrites: file references, template variables (`serasoft.*`), runtime variables, connection name | `Migration: paths and variables for template <tag>` |
| 3 old template files and root workflows removed | `Migration: remove template 1.0.x` |
| 4 new template: `tools/serasoft-sync.sh --tag <tag>`, then `tools/serasoft-verify.sh` must pass | `Migration: hop-process-template <tag>` |
| 5 platform configuration | `Migration: configuration for the Serasoft Airflow platform` |
| 6 database seed and report | `Migration: DB seed and report` |

The tool stops at the first error; the commits of the completed phases stay on the branch and the message names the failed phase.

### Prerequisites

- A checkout of this repository with the target annotated tag and the tags `1.0` and `1.0.1` (the tool compares the old template files with them): `git fetch --tags`. Run the tool from that checkout.
- Python 3.10 or later (standard library only) and Git.
- The target tag must be 3.3.0 or later: earlier tags lack `tools/serasoft-register-env.sh`, which the generated `config/env/<env>.list` header and the report checklist refer to.
- A clean checkout of the project (root of the work tree, no uncommitted change).
- If the project kept the sample `main.hwf` of the template, whose `p_base_process_name` default is `template` (the process name is passed at run time with `-p p_base_process_name=<name>`), the tool stops. Before running it, set the default of `p_base_process_name` in that root workflow to the process short name and commit.
- The old environment files of the project (one per environment) and a CSV export of the old configuration (below).

### Exporting the old configuration

The process names, event categories and subcategories come from the old integrations database, not from the files. Run the export on it (PostgreSQL, 1.0.x model):

```
psql "<connection>" -v ON_ERROR_STOP=1 --csv -f tools/serasoft-migrate-1x-export.sql > export.csv
```

The CSV has a `kind` column (`process`, `category`, `subcategory`). Every root workflow of the project must correspond to a `process` row, otherwise the tool stops.

### Running the tool

```
tools/serasoft-migrate-1x.py --dest ../myproject --tag 3.3.0 \
  --processes export.csv \
  --env dev=old/dev.json --env prod=old/prod.json
```

| Option | Default | Meaning |
|---|---|---|
| `--dest` | mandatory | clean Git checkout of the project |
| `--tag` | mandatory | annotated tag of the target template |
| `--processes` | mandatory | CSV produced by the export query |
| `--env NAME=FILE` | at least one | old environment file (JSON) of the environment `NAME` (`dev`, `test`, `prod`, ...); repeat for every environment |
| `--project` | name of the `--dest` folder | project name, used in file names and in `/tmp/<project>` |
| `--db` | `postgresql` | database of the integrations DB (`postgresql`, `mssql`, `sqlite`): selects `config/template-<db>.json` and the seed dialect |
| `--stop-after PHASE` | `6` | stop after this phase (`0` = analysis only, nothing written) |

To review phase by phase, run with `--stop-after 0` first, then check each commit. A stopped run leaves the branch and possibly uncommitted changes, so recover before running again:

1. `git checkout -f <original branch>` (a plain `git checkout -` would carry the uncommitted changes onto it and the next run would stop on "uncommitted changes").
2. `git branch -D migration/template-<tag>`.
3. Delete by hand only the generated untracked files that `git status` lists (`config/<project>*.json`, `config/env/`, `db/seed/`, `config/*.properties`, `docs/migration-report.md`).

Do not use `git clean`: after phase 5 the `.gitignore` no longer hides `config/`, so your local credential files under `config/` appear as untracked and `git clean` would delete them.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | migration complete, nothing left to do by hand |
| `2` | migration complete with manual work listed in the report; this is what a real project gets (secrets to create, credentials to rotate) |
| `1` | stopped: the message names the phase and the cause |
| `64` | usage error |

### What is generated

- `config/env/<env>.list`, the manifest read by the platform, in load order (a later file overrides an earlier one): `config/template-env.json`, `config/template-<db>.json`, `config/<project>.json`, `config/<project>-<env>.json`, `/run/secrets/<project>_<env>`.
- `config/<project>.json`: the project variables common to all environments (taken from the old `config/project-config.json`).
- `config/<project>-<env>.json` per environment: the template variables renamed to `serasoft.*`, values equal to the template default omitted, obsolete variables dropped, project variables unchanged. Log and temporary file names point to `/tmp/<project>/logs` and `/tmp/<project>/temp`.
- `config/secrets-example.json`: every credential variable (names containing `password`, `pwd`, `psw`, `secret` or `token`) with an empty value. Credentials are never copied into the repository; the real file is the Docker secret named in the manifest.
- `config/<process>.properties` for the extra parameters of a root workflow that have a default (the template loads it); extra parameters without a default are only named in the report.
- `db/seed/<project>_config.sql`: idempotent seed of the processes, event categories and subcategories that are not part of the template.

### Report and operator checklist

`docs/migration-report.md` (committed in phase 6) lists the inputs, the process map, the moves, the rewrite counts, template files that differ from 1.0.1 (possible customisations), unresolved references, event-writing steps, variables (mapped, dropped, credentials, project, filesystem paths), and project deployment files (`Dockerfile`, `.gitlab-ci.yml`, `other/hop-config.json`, ...), which are reported and not removed. It ends with the checklist to complete before cut-over:

1. Create the secrets (one per environment, from `config/secrets-example.json`).
2. Create the database with Liquibase and load `db/seed/<project>_config.sql`.
3. Register the project: DAG and `hop_projects.yaml` on the platform, or `tools/serasoft-register-env.sh` where cron starts the project (see "Running with cron").
4. Rotate the credentials that were in the old environment files or in the repository history.
5. Cut over from the old deployment.

### What the tool does not do

- It does not convert steps that write events directly (for example a "Table output" on `integrations_log_events`) to `EventsTraceTransform`; they are listed in the report with pipeline, transform and upstream source, and the seed prepares their categories.
- It does not remove "Set variables" actions that load `config/<short name>.properties` of a process: the template pre-phase now loads that file, so the report lists them (workflow, action, file) for removal by hand.
- It does not migrate 2.x projects: use `tools/serasoft-sync.sh --adopt-from` for those.
- It does not create the database or the secrets.
- It does not support two processes whose entries sit directly in `src/main/` (for example two root workflows both calling `src/main/starter_job.hwf`): the tool stops.
- It only rewrites workflows, pipelines and metadata (`.hwf`, `.hpl`, `metadata/**/*.json`); references in moved files that are not workflows, pipelines or metadata are reported, not changed.

## Releasing the template

This section applies to the hop-process-template repository itself, not to projects.

1. Merge the changes into `main`.
2. Create an **annotated** tag `X.Y.Z` on `main`, with the release notes in the message, and push it:

   ```
   git tag -a 3.2.0 -m "3.2.0: <release notes>"
   git push origin 3.2.0
   ```

`tools/serasoft-sync.sh` refuses lightweight tags (`git tag 3.2.0` without `-a`).

## Supported Apache Hop versions

The template is verified on **Apache Hop 2.16** and **Apache Hop 2.19** with the lab described in "Testing the template".

## Testing the template

This section applies to the hop-process-template repository itself, not to projects.

The workflow tests run `hop-run` from the official `apache/hop` Docker images against a PostgreSQL 16 created with `db/liquibase/master.xml`, on a throw-away copy of the working tree (`tests/hop/work/copy`, git-ignored): the repository itself is never used as a Hop project. Docker is the only prerequisite.

```
tests/hop/lab.sh up               # PostgreSQL + Liquibase + test processes
tests/hop/scenarios.sh 2.16.0     # all scenarios on Hop 2.16
tests/hop/scenarios.sh 2.19.0     # all scenarios on Hop 2.19
tests/hop/lab.sh down             # remove containers, network and tests/hop/work
```

`tests/hop/lab.sh run <hop version> <file> [<params> [<variables>]]` runs a single workflow (e.g. `tests/hop/lab.sh run 2.16.0 main.hwf p_base_process_name=default`), prints `RC=<exit code>` and writes the Hop log to `tests/hop/work/hoprun.log`; call `tests/hop/lab.sh copy` first to refresh the copy. With `LAB_PARAMS_SEPARATOR` set (e.g. `LAB_PARAMS_SEPARATOR="#"`) the run passes it to `hop-run` as `-ps`. The lab environment (`tests/hop/lab-env.json`) disables every feedback email. Test processes: `vartest` and `uuidtest` (internal `id` different from `short_name`), both running `tests/hop/fixtures/start.hwf`, which logs the variables it receives.

## Process template environment variables

The table below summarizes the set of base environment variables provided with the template. This set of variables will be the starting point of your application's environment variables. 

| Variabile Name      | Description                         | Default value |
|---------------|-------------------------------------|---------------|
|serasoft.project.link.ref|Link to activate the main process that must be started by the Hop Process Executor. The link is relative to the project home directory.|`${PROJECT_HOME}/src/project/main/${p_base_process_name}`|
|serasoft.project.main.workflow|Name of the workflow, inside `serasoft.project.link.ref`, that `main.hwf` starts for the process.|`start.hwf`|
|serasoft.hop.user|The operating system user that will run the Hop Process execution. This user must have read/write permissions on the project home directory.|`hopuser`|
|serasoft.hop.program.name|A virtual name assigned to Apache Hop to be inserted in events logging tables as a reference for the running instance|`hop`|
|serasoft.sys.unhandled.exception.subcategory.generic|The generic subcategory for unhandled system exceptions. This is used to categorize exceptions in the logs.|`SYSGE001`|
|serasoft.integrations.db.config.schema|Name of the schema containing the configuration tables for the integrations database|`config`|
|serasoft.integrations.db.log.schema|Name of schema containing the logs tables for the integrations database|`logs`|
|serasoft.integrations.db.host|Name of the hosts where the integrations database is running. This can be an IP address or a hostname.|`localhost`|
|serasoft.integrations.db.connection.name|Name of the connection assigned in Apache Hop for the integrations database. This is used to connect to the database during Hop Process execution. One of `integrations_db_postgres`, `integrations_db_mssql`, `integrations_db_sqlite` (environment files `config/template-postgresql.json`, `config/template-mssql.json`, `config/template-sqlite.json`).|`integrations_db_postgres`|
|serasoft.integrations.db.name|Name of the database containing the configuration and logs tables for the integrations database|`integrations_db`|
|serasoft.integrations.db.port|Port of the integrations database. This is the port where the database server is listening for connections (`1433` for SQL Server)|`5432`|
|serasoft.integrations.db.user|Username used to connect to the integrations database. This user must have permissions to read/write in the specified database|`postgres`|
|serasoft.integrations.db.pwd|Password used to connect to the integrations database. This user must have permissions to read/write in the specified database|`password`|
|serasoft.integrations.db.mssql.encrypt|SQL Server only: encrypt the connection (JDBC driver option `encrypt`)|`true`|
|serasoft.integrations.db.mssql.trust.server.certificate|SQL Server only: accept the server certificate without validating it (JDBC driver option `trustServerCertificate`): the connection stays encrypted, but the server identity is not verified. Set to `false` when the server certificate is trusted by the JVM, e.g. issued by a trusted CA|`true`|
|serasoft.email.success.feedback.enabled|Flag that enables or disables the sending of success feedback emails after a process execution. Set to 1 to enable, 0 to disable|`0`|
|serasoft.email.fail.feedback.enabled|Flag that enables or disables the sending of failure feedback emails after a process execution. Set to 1 to enable, 0 to disable|`1`|
|serasoft.email.application.error.feedback.enabled|Flag that enables or disables the sending of feedback emails after a process execution if application error. Set to 1 to enable, 0 to disable|`1`|
|serasoft.email.notactive.feedback.enabled|Flag that enables or disables the sending of feedback emails if the process is paused. Set to 1 to enable, 0 to disable|`0`|
|serasoft.email.lock.feedback.enabled|Flag that enables or disables the sending of feedback emails if the same process is alredy running. Set to 1 to enable, 0 to disable|`1`|
|serasoft.mail.isauthenticated|Flag to indicate if the SMTP server requires authentication. Set to true if authentication is needed, false otherwise|`false`|
|serasoft.mail.isgmail|Flag to indicate if the SMTP server is Gmail. Set to true if using Gmail, false otherwise|`false`|
|serasoft.smtp.mail.host|Name of the host where the SMTP server is running. This can be an IP address or a hostname|`localhost`|
|serasoft.smtp.mail.port|Port where the SMTP server is listening for connections|`25`|
|serasoft.smtp.mail.user|Username used to connect to SMTP server. This is used for authentication if the SMTP server requires it|`user1`|
|serasoft.smtp.mail.psw|Password used to connect to SMTP server. This is used for authentication if the SMTP server requires it||
|serasoft.smtp.trusted.hosts|Comma-separated list of trusted hosts for the SMTP server. This can be used to allow connections from specific hosts without authentication||
|serasoft.smtp.check.server.identity|Flag to indiceate if the server identity should be checked when connecting to the SMTP server. Set to true to enable, false to disable||
|serasoft.mail.from.displayname|Label displayed in the 'From' field of the email. This is the name that will appear as the sender of the email.|`Hop Process Executor`|
|serasoft.mail.from.email|Email address used in the 'From' field of the email. This is the address that will appear as the sender of the email|`hopexecutor@maildomain.it`|
|serasoft.mail.subject|First part of the text displayed in the subject of the email. It includes the hostname and the base process name|`[${v_hostname} - ${p_base_process_name}]`|
|serasoft.mail.subject.error|Text displayed in the subject of the email when an error occurs due to system exceptions. It includes the base process name.|`${serasoft.mail.subject} Failed for system exceptions`|
|serasoft.mail.subject.success|Text displayed in the subject of the email when the process execution is successful. It includes the base process name|`${serasoft.mail.subject} Terminated successfully`|
|serasoft.mail.subject.lock|Text displayed in the subject of the email when a lock occurs that prevents the process from executing. It includes the base process name|`${serasoft.mail.subject} Same instance is still running. Execution stopped.`|
|serasoft.mail.subject.application.error|Text displayed in the subject of the email when application errors occurs during process execution. It includes the base process name.|`${serasoft.mail.subject} Terminated successfully with application exceptions.`|
|serasoft.mail.subject.notactive|Text displayed in the subject of the email when the process is paused. It includes the base process name|`${serasoft.mail.subject} This instance is paused. Execution not started.`|
|serasoft.default.mail.destination.addresses|Default set of email addresses to included wherever needed. Email addresses are separated by spaces|`destination@maildomain.it`|
|serasoft.success.mail.destination.addresses|Set of email addresses to send success feedback emails to. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|`${serasoft.default.mail.destination.addresses}`|
|serasoft.errors.mail.destination.addresses|Set of email addresses to send error feedback emails to. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|`${serasoft.default.mail.destination.addresses}`|
|serasoft.lock.mail.destination.addresses|Set of feedback's email addresses to send because a lock is present. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|`${serasoft.default.mail.destination.addresses}`|
|serasoft.notactive.mail.destination.addresses|Set of feedback's email addresses to send because the process is not active. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|`${serasoft.default.mail.destination.addresses}`|
|serasoft.application.error.mail.destination.addresses|Set of email addresses to send application's error feedback emails to. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|`${serasoft.default.mail.destination.addresses}`|
|serasoft.success.mail.text|Sample text for the success feedback email. It includes the base process name, hostname, and log file name|`<p>The process ${p_base_process_name} on server ${v_hostname} was terminated successfully.</p><p>Process ${p_base_process_name}'s log attached.</p><p>Complete execution log file available at: ${p_log_filename}.</p><p>PLEASE DO NOT REPLAY TO THIS EMAIL!</p>`|
|serasoft.error.mail.text|Sample text message for the error feedback email. It includes the log file name|`<p>The process ${p_base_process_name} was terminated abnormally because of an Exception.</p><p>Process ${p_base_process_name}'s log attached.</p><p>Complete execution log file available at: ${p_log_filename}.</p><p>PLEASE DO NOT REPLAY TO THIS EMAIL!</p>`|
|serasoft.lock.mail.text|Sample text message used because a process cannot be started because a lock occurs. It includes the base process name, hostname, last job run timestamp, and log file name|`<p>The process ${p_base_process_name} on server ${v_hostname} can't be started because <strong>same process started at ${v_last_instance_start_timestamp} is not yet terminated</strong>.</p><p>Execution log file available at: ${p_log_filename}</p><p>PLEASE DO NOT REPLAY TO THIS EMAIL!</p>`|
|serasoft.application.error.mail.text|Sample text message used when an application error occurs. It includes the log file name and mentions that detailed exceptions are in the .csv file inside the `logs.zip` attachment|`<p>During process ${p_base_process_name}'s execution we collected some exceptions on integrations_log_details.</p><p>Process ${p_base_process_name}'s log and the .csv file with the collected exceptions are in the logs.zip file attached to this email.</p><p>Execution log file available at: ${p_log_filename}</p><p>PLEASE DO NOT REPLAY TO THIS EMAIL!</p>`|
|serasoft.notactive.mail.text|Sample text message used when a process cannot be started because it is not active. It includes the base process name, hostname, and log file name|`<p>The process ${p_base_process_name} on server ${v_hostname} can't be started because <strong>is set to not active</strong>.</p><p>Execution log file available at: ${p_log_filename}</p><p>PLEASE DO NOT REPLAY TO THIS EMAIL!</p>`|
|serasoft.execution.log.filename|Log file name, attached to the feedback mail inside `logs.zip`|`${PROJECT_HOME}/logs/execution_log_${p_base_process_name}_${serasoft.project.main.workflow}_${v_process_run_timestamp}.log`|
|serasoft.execution.file.name|File name with the events recorded, attached to the feedback mail inside `logs.zip`|`${PROJECT_HOME}/temp/execution_file_${p_base_process_name}_${serasoft.project.main.workflow}_${v_process_run_timestamp}.csv`|

## Exit codes

`hop-run` ends a template-based execution with:

| Exit code | Meaning |
|---|---|
| `0` | The process ran and terminated successfully (possibly with application errors recorded in `integrations_log_details`, status `X`). |
| `1` | The process failed, **or it was skipped**: another instance holds the single-instance lock, or the process is paused (`is_active` not `Y`). A skipped execution logs an explicit `SKIPPED: …` error message and still runs the post phase and the feedback email, if enabled for that case. |
| `2`, `9` | General `hop-run` error / invalid parameters (Hop Run, *Possible exit codes*). |

A skipped execution is reported as a failure on purpose: an orchestrator (cron, Apache Airflow) must not treat "nothing was processed" as success.

### Result marker for orchestrators

`hop-run` cannot return codes other than 0/1/2/9, so a skipped execution exits `1` like a failure. An orchestrator that needs to tell them apart sets the variable `SERASOFT_RESULT_FILE` (for example `hop-run … -s SERASOFT_RESULT_FILE=/tmp/serasoft-result`) to the path of a file. When an execution is skipped, the template writes a single token, without a trailing newline, to that file (overwriting it; the parent directory must exist), just before ending with exit code `1`:

| Content | Meaning |
|---|---|
| `skipped_locked` | another instance holds the single-instance lock |
| `skipped_paused` | the process is paused (`is_active` not `Y`) |

Nothing is written for a normal run or a failure: the orchestrator must remove the file before the run, and give each run its own file if runs can overlap. If the variable is not set (cron, manual runs) nothing changes. A failure while writing the file still ends the execution with exit code `1`. Serasoft's Airflow library uses this marker to report the two cases with dedicated exit codes (76 and 77, SeraSoft/airflow-dags#40).

### Checking whether a process can run

`src/template/commons/tools/check_state.hwf` tells an orchestrator whether a process can run, without starting it. It reads the same state as the pre-job of `main.hwf` and writes nothing: no row in `logs.integrations_logs`, `is_running` untouched, no feedback email, no post phase.

```
hop-run -j <project> -e <environment> -r local \
  -f ${PROJECT_HOME}/src/template/commons/tools/check_state.hwf \
  -p p_base_process_name=<process short name>
```

| Result | Exit code | Marker (`SERASOFT_RESULT_FILE`) | Log |
|---|---|---|---|
| can run | `0` | none | `Process '…' can run` |
| paused (`is_active` not `Y`) | `1` | `skipped_paused` | `SKIPPED: process '…' is not active` |
| locked (`is_running` = `Y`) | `1` | `skipped_locked` | `SKIPPED: process '…' is locked by an instance started at …` |
| not declared | `1` | none | `ERROR: process '…' is not declared` |
| state not readable (database error) | `1` | none | `ERROR: could not read the state of process '…'` |

When the lock is set but no execution of the process is recorded as running (no `R` row, for example a lock set by hand), the start time in the locked message, in the lock warning of `main.hwf` and in the lock email reads `unknown time (no running instance recorded)`.

The check is not atomic: another instance can take the lock between the check and the run, so `main.hwf` keeps its own lock check. Serasoft's Airflow library runs this workflow before `main.hwf` (SeraSoft/airflow-dags#41).

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

It stops with an error if no process has that short name. The two updates are not one transaction: if the release fails part-way, just run it again (it is idempotent).

**Future improvement** (#28): an optional lock max-age parameter; an orchestrator that enforces its own execution timeout could pass it so that locks older than that timeout, which are necessarily stale, are released automatically.

---
