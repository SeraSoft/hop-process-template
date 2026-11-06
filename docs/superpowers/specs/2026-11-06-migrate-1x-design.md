# Design: migration tool for template 1.0.x projects (tools/serasoft-migrate-1x.py)

Status: approved in brainstorming, ready for implementation planning
Tracks: issues to be opened (one per task of the implementation plan), single PR
Branch: feat/migrate-1x
Date: 2026-11-06

## Context

Customer projects built on hop-process-template 1.0.x must move to the current
template (3.3.0, the tag that will contain this tool and
`tools/serasoft-register-env.sh`) and to the Serasoft Airflow platform layout.
One project was migrated by hand; this spec turns that work into a tool.

A 1.0.x project:

- holds the template in `src/pre/`, `src/post/`, `src/commons/tools/`,
  `src/main/starter_job.hwf`, `main.hwf`, `metadata/rdbms/integrations_db.json`,
  `db/postgresql_integrationsdb_model_ddl.sql` (24 files in tag 1.0.1, the
  same paths in 1.0; projects created before 1.0.1 reference them through
  `${Internal.Entry.Current.Folder}` instead of `${PROJECT_HOME}`);
- starts each process with a **root workflow**, a copy of the old `main.hwf`
  (pre-phase `src/pre/main_pre_job.hwf`, main action, post-phases), whose
  `p_base_process_name` default is the process name and whose main action
  calls either `src/main/<folder>/start.hwf` or `src/main/starter_job.hwf`
  (then the process files may sit directly in `src/main/`); the root workflow
  may declare extra parameters;
- keeps project folders next to the template ones (e.g. `src/main/commons/`,
  non-template folders in `src/commons/`, `tools/`);
- uses template variables without the `serasoft.` prefix (`mail.*`,
  `integrations.db.db.*`, …), runtime variables `v_process_id`,
  `v_job_run_timestamp`, `p_logfile_name`, …, and the connection
  `integrations_db`;
- stores its configuration in environment files (in the repository or
  outside it) and sometimes variables in `config/project-config.json`;
- may write template events directly with a "Table output" on
  `integrations_log_events` (old columns `event_subcategory_id`, `gravity`).

The target is the template layout (`main.hwf` → `src/project/main/<short
name>/start.hwf`, `src/template/`) and the platform configuration:
`config/project-config.json`, `config/env/<env>.list`, project environment
files without credentials, credentials in Docker secrets, nothing written in
the (read-only) project folder.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | The tool always produces the **platform layout**; cron installations register it with `tools/serasoft-register-env.sh` | User decision; one layout, the manifest is the single source of truth |
| 2 | Process names come from an **export of the old configuration**: a SQL query shipped with the tool (`tools/serasoft-migrate-1x-export.sql`) run by the operator on the old `integrations_db`, saved as CSV | User decision; no network access to the customer DB from the tool; the configuration table, not the root workflows, is the reference |
| 3 | Steps writing template events directly are **detected and reported, not converted** (the seed prepares their categories) | User decision; `EventsTraceTransform` needs fixed names, a safe automatic conversion is not general |
| 4 | The tool works on a clean checkout, creates `migration/template-<tag>`, **one commit per phase**, never pushes | User decision; reviewable merge request, phase-level rollback |
| 5 | Python 3, standard library only, in the template repository, **not shipped** to projects (like `serasoft-sync.sh`) | XML/CSV/JSON processing; no third-party licence; run from a template checkout at the wanted tag |
| 6 | XML files are changed with **targeted text replacements**, never re-serialised | Minimal diffs; Hop sees its own formatting |
| 7 | Variables of `config/project-config.json` go to a **project environment file common to all environments**, `config/<project>.json` | User decision |
| 8 | Extra parameters of root workflows: only those **with a default** go to `config/<short name>.properties` | User decision; the template loads that file; values are not lost |
| 9 | Credentials recognised by name (`password`, `pwd`, `psw`, `secret`, `token`, case-insensitive) go to `config/secrets-example.json` without value | No credential in the repository; the report lists them |
| 10 | Project-specific deployment files (`Dockerfile`, `.gitlab-ci.yml`, `other/hop-config.json`, …) are **reported, not removed** | They depend on the project |
| 11 | No real customer or project names in the repository (tests and docs use neutral names) | User rule |
| 12 | Release with `3.3.0` (with `serasoft-register-env.sh`) | Template fixes found while building the tool go into the same tag |

## Command

```
tools/serasoft-migrate-1x.py --dest <project checkout> --tag <X.Y.Z> \
  --processes <export.csv> --env <name>=<file> [--env <name>=<file> …] \
  [--project <name>] [--db postgresql|mssql|sqlite]
```

| Option | Default | Meaning |
|---|---|---|
| `--dest` | mandatory | clean Git checkout of the project (root of a work tree, no uncommitted change) |
| `--tag` | mandatory | annotated tag of the target template, passed to `tools/serasoft-sync.sh` |
| `--processes` | mandatory | CSV produced by `tools/serasoft-migrate-1x-export.sql` |
| `--env <name>=<file>` | at least one | old environment file of environment `<name>` (`dev`, `test`, `prod`, …), anywhere on disk |
| `--project` | name of the project folder | project name (platform name, file names) |
| `--db` | `postgresql` | database of the integrations DB (`config/template-<db>.json` in the manifests) |

Exit codes: 0 migration complete; 2 migration complete with manual work listed
in the report; 1 stopped (message says which phase and why); 64 usage error.
Output: commits on `migration/template-<tag>`, `docs/migration-report.md`, a
short summary on stdout.

## Export

`tools/serasoft-migrate-1x-export.sql` (PostgreSQL, old 1.0.x model) outputs
one CSV with a `kind` column:

- `process`: `short_name`, `description`, `is_active` from
  `config.integrations_processes`;
- `category`: `id`, `event_type`, `name` from `config.event_category`;
- `subcategory`: `id`, `event_category_id`, `name` from
  `config.event_subcategory`.

The README gives the `psql` command (`\copy (…) to … csv header`).

## Phases

The tool stops at the first error. Phase 0 writes nothing; a later failure
leaves the commits of the completed phases on the branch and names the failed
phase.

### Phase 0 — analysis

1. Check the inputs: clean work tree, annotated tag in the template checkout,
   CSV readable with the expected columns, every `--env` file valid JSON.
2. Recognise the 1.0.x layout: at least `src/pre/main_pre_job.hwf`; otherwise
   stop (not a 1.0.x project).
3. Template files: the union of the template file lists of tags 1.0 and 1.0.1
   (constant in the tool). For each one present, compare its logic with tag
   1.0.1 (actions/transforms with type, SQL, file names normalised to the
   project root; hops), ignoring `${Internal.Entry.Current.Folder}` vs
   `${PROJECT_HOME}` and layout: a difference is reported as a possible
   customisation.
4. Root workflows: `*.hwf` at the project root (including `main.hwf`) whose
   pre-phase action calls `src/pre/main_pre_job.hwf`. For each one: the
   `p_base_process_name` default, the main action target, the extra
   parameters with their defaults.
5. Processes: each root workflow's short name must be a `process` of the CSV,
   otherwise stop. CSV processes without a root workflow and root workflows
   whose default is empty are reported. Target folder:
   `src/project/main/<short name>/`.
6. Plan the moves: process folder `src/main/<folder>/` → target folder;
   `starter_job.hwf` → `<target>/start.hwf` with the process files that sit
   directly in `src/main/`; `src/main/<other>/` not used by a root workflow,
   non-template folders of `src/commons/` and a root `tools/` →
   `src/project/commons/…` / `src/project/tools/…`. A destination that would
   receive two sources stops the tool.
7. Environment files: classify every variable (template mapping, dropped,
   credential, project); nothing can stay unclassified (project variables are
   all the names that are neither template nor dropped).

### Phase 1 — structure (commit "Migration: project structure for template <tag>")

`git mv` of the planned moves.

### Phase 2 — rewrites (commit "Migration: paths and variables for template <tag>")

In every `.hwf`, `.hpl` and `metadata/**/*.json` of the project (not the old
template files, removed in phase 3):

- file references: every `${PROJECT_HOME}/<old path>` and
  `${Internal.Entry.Current.Folder}/…` / `${Internal.Workflow.Filename.Folder}/…`
  relative reference to a moved file → `${PROJECT_HOME}/<new path>`;
- template variables: fixed mapping old → `serasoft.*` (including
  `integrations.db.db.host|name|port|user|password` →
  `serasoft.integrations.db.host|name|port|user|pwd`, `mail.*`, `smtp.*`,
  `email.*`, destination addresses, texts);
- runtime variables: `v_process_id` → `v_process_instance_id`,
  `v_job_run_timestamp` → `v_process_run_timestamp`, `v_job_run_date` →
  `v_process_run_date`, `terminated.successfully` →
  `v_terminated_successfully`, `p_logfile_name` → `p_log_filename`,
  `v_last_job_run_timestamp` → `v_last_instance_start_timestamp`;
- connection: `<connection>integrations_db</connection>` and
  `${integrations.db.connection.name}` → `${serasoft.integrations.db.connection.name}`;
- report: references to files that do not exist after the migration, the
  remaining references to removed template files, every "Table output" (or
  other transform) on `integrations_log_events` with its pipeline, transform
  name and the upstream source of `event_subcategory_id` / `gravity`.

### Phase 3 — old template removed (commit "Migration: remove template 1.0.x")

`git rm` of the old template files found in phase 0 and of the root
workflows (their role passes to the new `main.hwf`).

### Phase 4 — new template (commit "Migration: hop-process-template <tag>")

`tools/serasoft-sync.sh --tag <tag> --dest <project>` (first sync, no
template file left); files ignored by the project `.gitignore` are added
with `git add -f`; `tools/serasoft-verify.sh` must pass.

### Phase 5 — configuration (commit "Migration: configuration for the Serasoft Airflow platform")

- `config/project-config.json`: the template's file (variables empty); the
  previous file's variables go to `config/<project>.json` (Decision 7),
  except runtime names (`v_*`, `p_*`, reported) and credentials (Decision 9).
- `config/<short name>.properties` with the extra parameters that have a
  default (Decision 8); the others are only named in the report.
- Per `--env <name>`: `config/<project>-<name>.json` (template variables
  mapped, values equal to the template default omitted, obsolete ones
  dropped — `base.tmp.dir`, `lock.dir`, `db.type`, `hop.project.code`, …,
  credentials excluded, project variables unchanged,
  `serasoft.execution.log.filename` / `serasoft.execution.file.name` under
  `/tmp/<project>/logs|temp/`), and `config/env/<name>.list`:
  `config/template-env.json`, `config/template-<db>.json`,
  `config/<project>.json`, `config/<project>-<name>.json`,
  `/run/secrets/<project>_<name>`.
- `config/secrets-example.json`: every credential variable, empty value.
- Variables whose value looks like a filesystem path (starts with `/` or a
  drive letter) are reported: writable path or `/tmp/<project>/…`.
- `.gitignore`: `config/` committed (only local files ignored, as in the
  migrated project); old environment files with credentials that were in the
  repository are removed (reported, with the reminder to rotate them).
- Project-specific deployment files are reported (Decision 10).

### Phase 6 — seed and report (commit "Migration: DB seed and report")

- `db/seed/<project>_config.sql`, idempotent (`INSERT … WHERE NOT EXISTS`),
  for the configured `--db`: processes (id = short name, `is_running='N'`),
  event categories (old `event_type` → `type`) and subcategories of the CSV
  that are not template ones (`SYS001`, `SYSGE001`).
- `docs/migration-report.md`: inputs (tag, CSV, env files), process map,
  moves, rewrites (counts per kind), customised template files, unresolved
  references, event-writing steps to replace with `EventsTraceTransform`,
  variables (mapped / dropped / credentials / project / paths), deployment
  files, and the operator checklist (secrets, DB creation with Liquibase and
  seed, DAG and `hop_projects.yaml` or `serasoft-register-env.sh` for cron,
  credential rotation, cut-over from the old deployment).

## Testing

Fixtures generated by the tests from template tags (no project copies in the
repository), neutral names only:

- `fixture-101`: tag 1.0.1 plus a root workflow (copy of `main.hwf`, process
  `load_sales`) calling `src/main/load_sales_folder/start.hwf` that uses
  template variables, `${PROJECT_HOME}/src/…` references, a direct event
  insert, a project connection and an extra parameter with a default;
- `fixture-pre101`: like the first, with `${Internal.Entry.Current.Folder}`
  references, two root workflows, a shared `src/main/commons/` and a process
  folder named differently from the short name;
- `fixture-starterjob`: `main.hwf` calling `starter_job.hwf`, process files
  directly in `src/main/`, a project folder inside `src/commons/`, variables
  in `config/project-config.json`, environment files in the repository with
  credentials.

pytest `tests/tools/test_serasoft_migrate_1x.py`: every phase (layout, file
contents, commits), the analysis stops (unknown process, colliding moves, not
1.0.x, dirty tree), the environment classification, `.list` order, seed,
report; on every migrated fixture `tools/serasoft-verify.sh` passes and no
`.hwf`/`.hpl` keeps a reference to a removed file or an old template variable.

Real run: the three migrated fixtures in the Hop lab (`tests/hop`) on Hop
2.16 and 2.19, project mounted read-only, environment from the generated
`.list` (secret replaced by a lab file): `check_state.hwf` exits 0 and
`main.hwf` runs the fixture process. Final check outside the repository: the
tool run on a real 1.0.x project already migrated by hand, the differences
explained (manual decisions) or turned into report items.

## Documentation

Template README, section "Migrating a template 1.0.x project": prerequisites,
the export query, the command, the report, what follows (secrets, database,
DAG, or `tools/serasoft-register-env.sh` for cron).

## Out of scope

- Converting event-writing steps (Decision 3).
- 2.x projects (they use `tools/serasoft-sync.sh --adopt-from`).
- Moving or rewriting process logic beyond paths and variables.
- Creating the database or the secrets.
