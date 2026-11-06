# Design: register a project environment from its manifest (tools/serasoft-register-env.sh)

Status: approved in brainstorming, ready for implementation planning
Tracks: issues to be opened (one per task of the implementation plan), single PR
Branch: feat/register-env
Date: 2026-11-06

## Context

A project migrated to template 3.2.x for the Serasoft Airflow platform lists
its Hop environment files in `config/env/<env>.list` (one per line, load
order, relative paths from the project folder, credentials as
`/run/secrets/<name>`). The platform reads the manifest at every run and
passes the files to the image entrypoint, which registers the environment in
a container-local `hop-config.json`.

The same project can also be started on a VM by cron through
`hop_runner.sh` (SeraSoft/useful-scripts), which only passes `-j <project>`
and `-e <environment>` to `hop-run`: the project and the environment must
already be registered in the installation's `hop-config.json` with
`hop-conf`. Registering by hand copies the manifest into a command line and
drifts when the manifest changes. On a VM `hop-config.json` is shared by every
project of the installation, so environment names must be unique.

The platform's SSH backend already maps a secret `<name>` to
`/etc/serasoft/secrets/<name>` (mode 0600, service user) on the VMs
(SeraSoft/airflow-dags, `serasoft_airflow/hop.py`).

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | A template-owned script `tools/serasoft-register-env.sh`, shipped to projects by `serasoft-sync.sh` (added to its template-owned paths) | Every template-based project gets it; the manifest stays the only source of truth also for cron |
| 2 | `/run/secrets/<name>` → `<secrets-dir>/<name>`, `--secrets-dir` default `/etc/serasoft/secrets` | User decision; same convention as the platform's SSH backend, so a VM can move between cron and Airflow without moving files |
| 3 | Hop environment name default `<project>-<env>`, `--hop-env` to override | User decision; environment names are global in a VM's `hop-config.json` |
| 4 | Project name default: the project folder name | The platform uses the folder name as Hop project name |
| 5 | Idempotent: a registered project with the same home is kept; an existing environment gets its file list updated | Re-running after a manifest change realigns the VM |
| 6 | A project registered with another home folder is an error | Never re-point a project silently |
| 7 | All manifest checks before any `hop-conf` call | A broken manifest leaves `hop-config.json` untouched |
| 8 | Release `3.3.0` | New feature |

## Command

```
tools/serasoft-register-env.sh --env <env> [--project <name>] [--hop-env <name>] [--secrets-dir <dir>]
```

| Option | Default | Meaning |
|---|---|---|
| `--env <env>` | mandatory | reads `config/env/<env>.list` |
| `--project <name>` | name of the project folder | Hop project name |
| `--hop-env <name>` | `<project>-<env>` | Hop environment name |
| `--secrets-dir <dir>` | `/etc/serasoft/secrets` | folder holding the files the manifest names `/run/secrets/<name>` |

- The project folder is the parent of the script's folder (`<project>/tools/`),
  resolved to an absolute physical path.
- `HOP_HOME` must be set; `hop-conf` is `$HOP_HOME/hop-conf.sh`.
- Names (`--project`, `--hop-env`, `--env`) must match `^[A-Za-z0-9_.-]+$`.

Exit codes: 0 success; 64 usage error (unknown or missing option, invalid
name); 1 manifest, file or registration error. Messages on stderr start with
`ERROR:`.

## Behaviour

1. **Manifest** `config/env/<env>.list` (missing → exit 1). Same rules as the
   platform: blank lines and lines starting with `#` (after trimming) ignored;
   leading/trailing spaces trimmed; relative path → `<project folder>/<path>`;
   `/run/secrets/<name>` (a single path component) → `<secrets-dir>/<name>`;
   any other absolute path → error; a path containing `,` → error; every
   resolved file must exist and be readable; an empty list → error. No
   `hop-conf` call happens unless all lines pass.
2. **Project**: list the registered projects (`hop-conf.sh -pl`). Not
   registered → `hop-conf.sh -pc -p <project> -ph <folder> -pf
   config/project-config.json`. Registered with the same home → nothing.
   Registered with another home → exit 1 naming both folders. The script
   checks that `config/project-config.json` is unchanged after the call
   (`hop-conf -pc` rewrites it); if Hop reformats it, the script restores
   the original content and says so (a dirty checkout would be reset by a
   later `hop_runner.sh -pull:Y`).
3. **Environment**: list the environments (`hop-conf.sh -el`). Missing →
   `hop-conf.sh -ec -e <hop-env> -ep <project> -eu <env> -eg <files>`.
   Existing → `hop-conf.sh -em -e <hop-env> -ep <project> -eu <env> -eg
   <files>` (the files joined with `,`, in manifest order).
4. **Summary** on stdout:
   `OK serasoft-register-env project=<project> hop-env=<hop-env> files=<n>`
   followed by an example command:
   `hop_runner.sh main.hwf -prj:<project> -env:<hop-env> -param:p_base_process_name=<process>`.

The exact output formats of `hop-conf.sh -pl` / `-el` (Hop 2.16 and 2.19)
are checked during implementation; the parsing must not depend on anything
else than the project/environment names and the project home.

## Documentation

Template `README.md`, new section "Running with cron (hop_runner.sh)": when
to use it, the command, the secrets folder and file permissions, the
environment name and the `hop_runner.sh` call, re-running after a manifest
change. The "Template updates" ownership table lists the new script.

## Testing

- pytest `tests/tools/test_serasoft_register_env.py` with a fake
  `hop-conf.sh` in a temporary `HOP_HOME` that records its calls and answers
  `-pl` / `-el` from a small state file: new project and environment,
  re-run (environment updated, project kept), secrets mapping (default and
  `--secrets-dir`), custom `--project` / `--hop-env`, every manifest error
  (missing manifest, missing file, unreadable file, comma, absolute path
  outside `/run/secrets`, empty list) with no `hop-conf` call, project
  registered with another home, usage errors.
- `tests/tools/test_serasoft_sync.py`: the script is template-owned (shipped,
  in the manifest).
- Real run in `apache/hop:2.16.0` and `apache/hop:2.19.0` (lab image): register
  the lab copy of the template with a manifest and a secret file, run
  `hop-run -j <project> -e <project>-<env>` on the `vartest` process, re-run the
  registration after changing the manifest, check `config/project-config.json`
  unchanged.

## Out of scope

- Unregistering projects or environments.
- Windows (`hop-conf.bat`).
- The migration tool for 1.0.x projects (separate spec).
