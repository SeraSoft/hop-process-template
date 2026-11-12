# Design: Hop projects in a subfolder of a Git repository

Status: approved in brainstorming, ready for implementation planning
Repositories: SeraSoft/hop-process-template (this spec) and SeraSoft/airflow-dags
Tracks: issues to be opened (one per task of the implementation plan), one PR per repository
Date: 2026-11-12

## Context

A customer repository can hold its Hop project in a subfolder (e.g. `etl/`)
next to other content (e.g. `reporting/`). The repository layout is the
customer's choice and cannot change. Two pieces assume that the project is the
root of its repository:

- `tools/serasoft-sync.sh` (template) refuses a `--dest` that is not the root of
  a Git work tree.
- The Serasoft Airflow platform (`SeraSoft/airflow-dags`): `mnt_distribuzione_hop`
  fetches the commit and copies the **whole repository** into the immutable
  version folder `<project>@<commit12>` on the share; `run_hop_workflow()` uses
  that folder as `HOP_PROJECT_FOLDER`, so `config/env/<env>.list` is not found
  when the project is in a subfolder.

`tools/serasoft-verify.sh` and `tools/serasoft-register-env.sh` do not use Git
and already work relative to the project folder. `hop_runner.sh` (cron) has
never been tried on a project in a subfolder; the platform runs such projects
on Swarm.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Optional key `path` per project in `config/hop_projects.yaml`; the distribution copies only that subfolder into the version folder | Execution, pointers, `hop_ref`, retention stay unchanged: the version folder is the project |
| 2 | Several projects of the same repository are supported (one entry each, different `path`) | User decision: only one today, but it costs nothing |
| 3 | The version folder name includes the path when set: `<project>@<commit12>-<path with / → ->` | User decision; a change of `path` without a new commit produces a new version instead of reusing a folder with other content: version folders stay immutable |
| 4 | `serasoft-sync.sh --dest` accepts a subfolder of a Git work tree; the uncommitted-changes check stays on the whole work tree | The sync diff must be reviewable on its own |
| 5 | `hop_runner.sh` with a project in a subfolder: documented as not tried, no change | Not used where these projects run (Swarm) |
| 6 | `tools/serasoft-migrate-1x.py`: out of scope | No 1.0.x project in a subfolder seen so far |
| 7 | Releases: template `3.4.0`, airflow-dags `v1.8.0` | New features |
| 8 | One spec and one plan (this repository) for both; airflow-dags gets a short spec with its own decisions pointing here | The two changes are designed together, implemented and reviewed separately |

## airflow-dags: distribution

### Configuration

```yaml
sales:
  repo: https://gitlab.example.lan/etl/sales.git
  path: etl
  ref: {dev: develop, test: test, prod: main}
```

- `path` (optional): relative path inside the repository, one or more segments
  separated by `/`; each segment matches the name rule
  `[A-Za-z0-9][A-Za-z0-9_.-]*`; no `..`, no leading or trailing `/`, no empty
  segment. Validated by `load_projects()` (`_KEYS` gains `path`), so
  `make test` and the customer's CI report it.
- Entries with the same `repo` and different `path` are distinct projects.

### Script input

`SERASOFT_HOP_DEPLOY_PROJECTS` lines get a fourth tab-separated field, the
path (empty when not set): `name<TAB>repo<TAB>ref<TAB>path`. `deploy_list()`
returns `(name, repo, ref, path)`; the manual trigger with `ref` passes the
project's `path` too. The log line of `prepare` stays `name@ref` (the path is
shown by the script). `check_line` validates the path with the same rule as
the Python side.

### `deploy_one`

- Version folder: `dir="$name@$short"` without path,
  `dir="$name@$short-${path//\//-}"` with path (e.g. `sales@8b11d0aa94c2-etl`).
  The name satisfies the checks of the start script (`pick`: `<project>@…`,
  characters `[A-Za-z0-9_.@-]`, no `/`, no `..`).
- After the checkout, with a path: the subfolder must exist in the commit,
  otherwise the project fails with `path '<path>' not found in <repo> at <commit12>`
  (exit as the other per-project errors; the other projects go on). Only
  `"$work/src/$path/."` is copied to the share.
- Pointers (`<project>.current`, `<project>@<ref>.ref`), the "unchanged" check
  (pointer equals `dir`), the `.serasoft-current` marker, retention and grace
  period work on version names and need no change.

### Execution

No change: `run_hop_workflow()` reads the pointer and gets a folder that is the
project.

### Tests (pytest, local `file://` repositories)

- `load_projects`: valid paths (`etl`, `a/b`, `a.b-c_d`) and invalid ones
  (`..`, `/etl`, `etl/`, `a//b`, `a b`, `.x`, non-string).
- `deploy_list` and the manual trigger carry the path.
- Distribution with path: version folder name, content limited to the
  subfolder (a file outside it is not on the share).
- Same commit, `path` changed: a new version, pointer moved, the previous one
  untouched.
- Path missing in the commit: error message, no version folder, pointer
  unchanged, other projects distributed.
- Two projects from the same repository with different paths.
- Mode `ref` with path.
- `check_line` rejects an invalid path.
- Regression: projects without `path` produce exactly today's names and content.

### Documentation

README (distribution section), `config/hop_projects.yaml.example`,
`docs/dag-author-guide.md` where it describes `hop_projects.yaml`.

## hop-process-template: tools

### `tools/serasoft-sync.sh`

- `--dest` is the root of a Git work tree **or a folder inside one**: the check
  becomes "inside a work tree" (`git -C "$dest" rev-parse --show-toplevel`
  succeeds). The project is `--dest`: template files, SQLite seeds,
  `SERASOFT_VERSION` and `SERASOFT_MANIFEST.sha256` are written there; nothing
  outside it is touched.
- `git -C "$dest" status --porcelain` keeps checking the whole work tree; the
  message names the work tree root.
- `--dest` must not be the template repository nor a folder inside it.
- The ignored-files warning (`git ls-files --others --ignored --exclude-standard`)
  already applies every `.gitignore` level; no change, covered by a test.

### `tools/serasoft-verify.sh`, `tools/serasoft-register-env.sh`

No change; a verify test on a project in a subfolder.

### Tests (pytest, `tests/tools/`)

- First sync and `--adopt-from` into a subfolder: files only in the subfolder,
  the rest of the work tree untouched.
- Refused when the work tree has uncommitted changes outside the subfolder.
- A root `.gitignore` hiding template files of the subfolder: warning.
- Refused when `--dest` is a folder inside the template repository.
- `serasoft-verify.sh` run from the subfolder.

### Documentation

README:

- "Template updates": projects in a subfolder (sync command, CI job
  `cd <subfolder> && tools/serasoft-verify.sh`).
- "Running with cron (`hop_runner.sh`)": not tried with projects in a
  subfolder.
- Pointer to the `path` key of `hop_projects.yaml` for the platform.

## Lab check (Swarm, run by the user on the lab machine)

The airflow-dags spec carries the step-by-step procedure with expected
results; the user runs it and reports the outputs.

1. A Git repository reachable from the lab with a project in `etl/`, created
   with `serasoft-sync.sh --tag 3.4.0 --dest <repo>/etl`, and a test process that
   logs a recognisable line.
2. Lab `hop_projects.yaml` with `path: etl`; trigger `mnt_distribuzione_hop`.
   Expected: `<project>@<commit12>-etl` and `<project>.current` on the share;
   the version folder holds only the project.
3. A test DAG with `run_hop_workflow()`: `check_state.hwf`, then `main.hwf` on
   the test process. Expected: exit 0, the log shows the `…-etl` version and the
   process line.
4. `path` change alone: the test repository also holds a copy of the project
   in `etl2/` (same commit); set `path: etl2` and trigger the distribution.
   Expected: a new version `<project>@<commit12>-etl2`, the pointer moved, the
   `…-etl` version untouched; the test DAG runs on `…-etl2`.

## Out of scope

- `hop_runner.sh` support for projects in a subfolder.
- `tools/serasoft-migrate-1x.py` for 1.0.x projects in a subfolder.
- Fetching a repository once for several projects.
