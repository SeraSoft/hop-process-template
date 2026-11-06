# Design: template 3.2.0 — short_name lookup, generic process parameters, template sync from a tag

Status: approved in brainstorming, ready for implementation planning
Tracks: issues to be opened (one per task of the implementation plan), single PR
Branch: feat/template-3.2.0
Date: 2026-11-05

## Context

Customer Hop projects built on older template versions must be brought to the
current template. Two families exist:

- **1.0.x** (e.g. UNI projects; BancaFinintGroup/Mercury_ETL as a sample):
  template in `src/commons`, `src/pre`, `src/post`; one root workflow per
  process (a copy of the old `main.hwf`) calling `src/main/<folder>/start.hwf`;
  project variables without the `serasoft.` prefix; old database model.
- **2.x**: same layout as 3.x (`main.hwf`, `src/template/`,
  `src/project/main/<process>/start.hwf`), same `serasoft.*` variables, same
  database schema; only file renames (`config/default-*.json` →
  `config/template-*.json` in 2.0.x, `master-postgresql.xml` → `master.xml`).

The migration is split in two specs:

- **Spec A (this document)**: changes to hop-process-template, released as
  `3.2.0`, so that the target of every migration supports what the migrated
  projects need and can be kept up to date from a tag.
- **Spec B (next)**: the 1.0.x → 3.2.0 migration tool and the runbooks for
  1.0.x and 2.x projects. It relies on A.

Target Hop version for the customer projects: **2.16**. The template was last
developed and verified on Hop 2.19 (Airflow lab).

## Findings that drive this design

1. **`id` and `short_name` are not decoupled.** The 1.0.1 template looked up
   the process by `short_name`. The refactoring of #6 (commit `d872548`)
   changed the lookup in `init_process_id.hpl` to `id = p_base_process_name`,
   while the lock (#11, #12, `main_pre_job.hwf`), `update_process_reference.hpl`,
   `release_lock.hwf`/`release_lock_check.hpl` and `check_state.hwf` use
   `short_name`. Today `p_base_process_name` must equal both `id` and
   `short_name`; no issue ever decoupled them. `init_process_id.hpl` is the only
   place that uses `id`.
2. **Undeclared parameters do not reach `start.hwf`.**
   - `hop-run -p key=value` for a parameter the workflow does not declare is
     silently ignored (`NamedParameters.setParameterValue` does nothing for an
     unknown key; checked on Hop 2.20.0-rc1 and `main`).
   - `main.hwf` passes to `start.hwf` only its own declared parameters
     (`pass_all_parameters=Y`): `p_base_process_name`, `p_log_filename`.
   - Parameter semantics are changing across Hop versions: since
     apache/hop#8101 (in 2.20) a parameter declared with a default in a child
     pipeline/workflow no longer takes a same-named variable inherited from the
     caller; apache/hop#9192 (after 2.20.0-rc1) does the same for `hop-run`.
     A mechanism based on declared parameters in `start.hwf` would behave
     differently on 2.16 and 2.20+.
   - `hop-run -p` splits its value on commas: a single parameter value cannot
     contain `,`.
3. **Process-level variables already exist** (#13): `main_pre_job.hwf`
   (action "Init Process Context Variables") loads
   `${PROJECT_HOME}/config/${p_base_process_name}.properties`, when present,
   at `ROOT_WORKFLOW` scope.
4. **SeraSoft/airflow-dags already solves "customer repository from a tag"**
   (`tools/serasoft-sync.sh`, `tools/serasoft-verify.sh`, design
   `docs/superpowers/specs/2026-10-05-customer-repo-sync-design.md`): no shared
   history, Serasoft-owned files copied from an annotated tag with
   `git archive`, `SERASOFT_VERSION` and `SERASOFT_MANIFEST.sha256` at the root
   of the customer repository, a verify script for the customer CI.
5. hop-process-template tags are lightweight so far (`3.1.0` is a commit, not a
   tag object).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | `id` of `config.integrations_processes` is internal only; every lookup by process name uses `short_name` | Finding 1; a process can be renamed or migrated without touching its id or its log rows |
| 2 | New `main.hwf` parameter `p_process_params`: `key=value` pairs separated by `;` | Finding 2: the only way to pass process-specific values that works the same on every Hop version and needs no declaration in `start.hwf`; `;` because `hop-run -p` splits on `,` |
| 3 | Precedence: environment < `config/<short_name>.properties` < `p_process_params` | The caller's explicit value wins over the per-process default |
| 4 | Template files are synced into projects from an annotated tag with `tools/serasoft-sync.sh`, modelled on airflow-dags; projects check them with `tools/serasoft-verify.sh` | Finding 4: same conventions across Serasoft repositories; the version in use is always readable |
| 5 | Scripts in Bash, as in airflow-dags | Reuse of tested logic; Git Bash or WSL on Windows; verify runs in CI on Linux |
| 6 | First sync of a project with no manifest uses `--adopt-from <tag\|auto>` | 2.x projects (and 1.0.x projects after the spec B migration) hold template files copied by hand: knowing the starting version detects local modifications and removes dismissed files |
| 7 | SQLite database files are *seed* files: copied when missing, never overwritten, not in the manifest | They are data that change at every development run |
| 8 | The template `README.md` is shipped as `src/template/README.md` | Operational documentation of the version in use travels with the project |
| 9 | `.gitignore` is project-owned; no template `.gitignore` for now | The template writes `logs/` and `temp/` at the project root, which a nested `.gitignore` cannot cover; the README lists the recommended entries |
| 10 | Run configurations (`metadata/*-run-configuration/local.json`) are template-owned | User decision |
| 11 | Annotated tags from `3.2.0` on, release notes in the tag message | Required by the sync; same rule as airflow-dags |
| 12 | Workflows verified on Hop 2.16 and 2.19; incompatibilities found on 2.16 are fixed in this work | 2.16 is the customer target, 2.19 the Airflow platform |
| 13 | Release `3.2.0` (minor) | Backward compatible: in every 3.x installation `id = short_name`, so the lookup change keeps them working |

## A1. Process lookup by `short_name`

- `src/template/pre/init/init_process_id.hpl`, step
  "Get integration_process_id ref" (DBLookup on `integrations_processes`):
  the key becomes `short_name = base_process_name` (was `id`). It still returns
  `id`, renamed `integration_process_id`, which feeds
  `v_integrations_process_id` (FK of `logs.integrations_logs`). Default `-1`
  unchanged.
- Used by `main_pre_job.hwf` and `check_state.hwf`: both pick up the change.
- No other file changes: all the other lookups already use `short_name`. The
  Liquibase `default` row (`id = short_name = 'default'`) stays valid.
- Parameter descriptions that mention `id` as the process name are updated.

## A2. `p_process_params`

- `main.hwf` declares `p_process_params`, default empty, description:
  "Process parameters as `key=value` pairs separated by `;` (no `;` or `,` in
  values). Each pair becomes a variable of the root workflow; it overrides
  `config/<p_base_process_name>.properties`."
- New pipeline `src/template/pre/init/init_process_params.hpl`, run by
  `main_pre_job.hwf` right **after** "Init Process Context Variables" (also when
  the `.properties` file does not exist):
  - empty `p_process_params`: does nothing;
  - splits on `;`, ignores empty pieces (a trailing `;` is allowed), splits each
    piece on the first `=`, trims key and value;
  - validates: a piece without `=`, a key not matching
    `^[A-Za-z_][A-Za-z0-9_.]*$`, or a key given twice is an error;
  - on error: logs `ERROR: invalid p_process_params entry '<piece>': <reason>`
    and the pre-job fails, so the execution ends through the error post phase
    (exit code 1), like any other pre-job error;
  - otherwise sets one variable per pair at `ROOT_WORKFLOW` scope and logs the
    keys set (not the values, which may be sensitive).
- `check_state.hwf` and `release_lock.hwf` do not take `p_process_params`: they
  do not run the process.
- Processes **must not declare** these keys as parameters of `start.hwf`: on
  Hop 2.20+ a declared parameter with a default ignores the inherited variable
  (apache/hop#8101). Documented in the README.

Example:

```
hop-run -j <project> -e <environment> -r local -f ${PROJECT_HOME}/main.hwf \
  -p p_base_process_name=mercury_aum_tables,p_process_params="p_tipo_periodo=S;p_data_rif=20261031"
```

## A3. `tools/serasoft-sync.sh` and `tools/serasoft-verify.sh`

### Ownership

| Category | Paths (as of the tag) | Sync | In manifest / verified |
|---|---|---|---|
| Template-owned | `main.hwf`; `src/template/**`; `config/template-*.json`; `metadata/rdbms/integrations_db_*.json`; `metadata/workflow-log/workflow_log.json`; `metadata/pipeline-run-configuration/local.json`; `metadata/workflow-run-configuration/local.json`; `db/liquibase/**`; `tools/serasoft-verify.sh` | copied, overwritten | yes |
| Template-owned, renamed | `README.md` → `src/template/README.md` | copied, overwritten | yes |
| Seed | `db/sqlite/data/integrations_db`, `integrations_db.config`, `integrations_db.logs` | copied only when missing; kept (warning) when present | no |
| Never copied | `README.md` at the root, `.gitignore`, `docs/`, `.github/`, `integration-tests/`, `tests/`, `src/project/**`, `config/project-config.json`, `tools/serasoft-sync.sh` | — | — |

Owned directories (no extra file allowed by verify): `src/template/`,
`db/liquibase/`. Template-owned paths that do not exist in an older tag are
skipped (`git archive` fails on a missing path).

### Sync

`tools/serasoft-sync.sh --tag <X.Y.Z> --dest <project checkout> [--adopt-from <tag|auto> [--force]]`,
run from a checkout of hop-process-template that has the tags. It does not
commit: the operator reviews the diff, commits, opens the PR/MR.

1. Refuses: unknown tag; lightweight tag; `--dest` not a directory, not the
   root of a Git work tree, the template itself, or with uncommitted changes.
2. Extracts the template-owned and seed paths **from the tag** with
   `git archive` (never from the working copy); refuses file names with a
   backslash or a newline (`sha256sum` escapes them).
3. With a previous `SERASOFT_MANIFEST.sha256`: validates every entry (format,
   template-owned path) before writing anything, so a damaged manifest can never
   remove a project file. A template-owned file of the new version that already
   exists in `--dest` must be listed in the previous manifest, otherwise the
   sync refuses (project file in the way).
4. Without a manifest (first sync):
   - without `--adopt-from`: any template-owned file of the new version already
     present in `--dest` makes the sync refuse, and the message suggests
     `--adopt-from`;
   - `--adopt-from <tag>`: the tag must exist (annotated or not: the old tags
     are lightweight). Every template-owned path present in `--dest` is compared
     with the same path in `<tag>`:
     - identical → adopted (overwritten by the new version);
     - different, or not in `<tag>` but inside an owned directory → listed as
       *locally modified*; the sync refuses unless `--force`, which overwrites
       them and lists them again in the summary;
     - files of `<tag>` that are template-owned there (including the 2.x names
       `config/default-*.json`, `db/liquibase/master-*.xml`) and absent from
       the new version are removed from `--dest` when identical to `<tag>`;
       when different they are listed as locally modified (same rule as above);
   - `--adopt-from auto`: picks the tag with the most template-owned files
     identical to `--dest`, prints it (`adopt-from auto: <tag> (<n>/<m> files
     identical)`), then behaves as `--adopt-from <tag>`.
5. Removes the files listed in the previous manifest that the new version no
   longer has (and empty parent directories).
6. Copies the template-owned files; writes `README.md` as
   `src/template/README.md`; copies each seed file only if missing, otherwise
   prints `WARNING: kept local <file>`.
7. Prints `WARNING: db/liquibase/master.xml changed: run liquibase update on
   the project databases (see src/template/README.md)` when `master.xml`
   differs from the previous manifest entry (or, on a first sync, from
   `<adopt-from tag>`).
8. Rewrites `SERASOFT_VERSION` (`<tag> <commit>`) and
   `SERASOFT_MANIFEST.sha256` (`sha256sum` format, sorted by path, template-owned
   files only).
9. Prints one summary line:
   `OK serasoft-sync tag=<tag> commit=<12 chars> added=<n> changed=<n> removed=<n> adopted=<n> forced=<n>`.

Exit codes: 0 full success, 1 refused/failed (message on stderr), 64 usage.
Same Bash rules as airflow-dags: `set -euo pipefail`, idempotent (a second run
with the same tag changes nothing).

### Verify

`tools/serasoft-verify.sh`, from the project root (CI or by hand). Fails
(exit 1, offending files on stderr) when:

- a manifest entry is modified or missing, or a line is malformed
  (`sha256sum --check --strict`; CRLF manifest lines accepted);
- `src/template/` or `db/liquibase/` holds a file or symlink not in the
  manifest, or is itself a symlink;
- `SERASOFT_VERSION` is missing or empty.

Seed files are not checked. Success prints
`OK serasoft-verify version=<tag> files=<n>`. Exit 66 when run outside the
project root (no manifest), 64 on usage error.

Known limitation, documented: on Windows with `core.autocrlf=true` the
checkout converts template files to CRLF and a **local** verify fails; the
README recommends a project `.gitattributes` with `eol=lf` for the
template-owned paths (the sync does not write it: it is project-owned).

## Documentation

`README.md` (also shipped as `src/template/README.md`), new or updated sections:

- `p_process_params`: format, comma/semicolon limits, precedence with the
  environment and `config/<short_name>.properties`, validation errors and exit
  code, examples (cron, Airflow), the "do not declare them in `start.hwf`" rule.
- Process identity: `short_name` is the process name everywhere
  (`p_base_process_name`, folder `src/project/main/<short_name>/`), `id` is
  internal.
- Environments in three layers: `config/template-env.json`,
  `config/template-<db>.json` (template-owned, never edited), then a
  project file per environment holding the project variables and the real
  values of the `serasoft.*` variables (later files override earlier ones).
- Template updates: creating a project from a tag, updating, `--adopt-from`
  (2.x projects and migrated 1.0.x projects), `--force`, seed files, the
  Liquibase warning, verify in CI (snippet), recommended CODEOWNERS/approval
  rule on template-owned paths, `.gitattributes`, recommended project
  `.gitignore` entries (`logs/`, `temp/`, environment files with credentials).
- Supported Hop versions: verified on 2.16 and 2.19.
- Release procedure: annotated tag `X.Y.Z` on `main`, release notes in the tag
  message.

## Testing

### Workflows (Hop 2.16 and 2.19)

Harness committed in `tests/hop/` (never copied to projects):

- PostgreSQL 16 container; `integrations_db` created from
  `db/liquibase/master.xml` with the Liquibase image;
- `hop-run` from the official images `apache/hop:2.16.0` and
  `apache/hop:2.19.0`, on a throwaway copy of the working tree (runs write
  `logs/`, `temp/`, never in the repository), environment with all feedback
  emails disabled;
- test processes added to the copy only: one that logs the variables it
  receives, one slow process for the lock.

Scenarios, on both versions:

1. `default` process: exit 0, unchanged behaviour;
2. process declared with `id` (UUID) ≠ `short_name`: runs, its log row has the
   UUID as `integrations_processes_id`, the lock is set and released;
   `check_state.hwf` and `release_lock.hwf` work by `short_name`;
3. `p_process_params` empty, set, set together with
   `config/<short_name>.properties` (the parameter wins);
4. invalid `p_process_params` (piece without `=`, invalid key, repeated key):
   exit 1 and `ERROR: invalid p_process_params entry …`;
5. regression: lock present, paused process, `SERASOFT_RESULT_FILE` marker.

### Sync and verify

pytest in `tests/tools/` (run locally, no GitHub Actions job): temporary
template repository with annotated and lightweight tags, temporary project
repository.

- creation, update from a second tag (changed, added, removed files), second
  run with the same tag changes nothing;
- refusals: unknown or lightweight tag, dirty destination, non-Git
  destination, the template itself, project file in the way;
- `--adopt-from <tag>`: identical files adopted, modified file refused, then
  overwritten with `--force`, dismissed files removed; `--adopt-from auto`
  picks the right tag;
- seed files copied when missing, kept with a warning when present;
- Liquibase warning when `master.xml` changes;
- `README.md` written as `src/template/README.md`, root `README.md` untouched;
- the tag content is used, not uncommitted changes in the template checkout;
- verify: intact project passes; modified, missing, extra file and symlink
  each fail naming the file; empty `SERASOFT_VERSION` fails; seed files ignored.

## Release

- Merge of the single PR, then annotated tag `3.2.0` on `main` with the release
  notes in the tag message. `ship-package.yml` unchanged.

## Out of scope

- The 1.0.x migration tool and the runbooks (spec B).
- A CI pipeline template and CODEOWNERS for customer repositories (README
  recommendations only).
- Automatic expiry of stale locks (#28) and the other open issues.
