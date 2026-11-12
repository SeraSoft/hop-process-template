# Design: register a project environment on Windows (tools/serasoft-register-env.ps1)

Status: implemented (plan `docs/superpowers/plans/2026-11-12-register-env-ps1.md`); manual Windows PowerShell 5.1 check pending (Testing)
Tracks: #81, #82, single PR
Branch: feat/register-env-ps1
Date: 2026-11-12

## Context

`tools/serasoft-register-env.sh` (spec `2026-11-06-register-env-design.md`)
registers a project and one of its environments in the local Hop installation
(`hop-config.json`) from `config/env/<env>.list`. It is a Bash script for Linux
VMs (cron). Developers working with Hop GUI on Windows register their local
environment by hand (Hop GUI or `hop-conf.bat`), copying the manifest into the
GUI and keeping the passwords in a file outside the repository. The copy
drifts when the manifest changes, and running the Bash script from Git Bash
would store `/c/...` paths that Hop on Windows cannot read.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | A template-owned PowerShell script `tools/serasoft-register-env.ps1` with the behaviour of the Bash script, calling `hop-conf.bat` | One source of truth (the manifest) also for local development on Windows |
| 2 | Runs on Windows PowerShell 5.1 and PowerShell 7; the file is ASCII only | User decision: 5.1 is on every Windows 10/11, nothing to install; 5.1 misreads UTF-8 without BOM |
| 3 | Secrets folder default `%USERPROFILE%\.serasoft\secrets`; for `/run/secrets/<name>` the script uses `<dir>\<name>`, or `<dir>\<name>.json` when the first is missing | User decision: the user profile is private by default and not synced; a `.json` file is easier to create and open on Windows |
| 4 | PowerShell-style parameters `-Env`, `-Project`, `-HopEnv`, `-SecretsDir`, `-HopHome` | Native to PowerShell users; `-HopHome` because `HOP_HOME` is often unset on Windows |
| 5 | `hop-conf.bat` on Windows, `hop-conf.sh` elsewhere | Automated tests on Linux with PowerShell 7 and a fake `hop-conf.sh` |
| 6 | Same exit codes, messages and checks as the Bash script | The two scripts are documented and maintained as one tool |
| 7 | Shipped by `serasoft-sync.sh` (template-owned path), protected by the verify | Same as the Bash script |
| 8 | Release `3.5.0` | New feature |

## Command

```
.\tools\serasoft-register-env.ps1 -Env <env> [-Project <name>] [-HopEnv <name>] [-SecretsDir <dir>] [-HopHome <dir>]
```

| Parameter | Default | Meaning |
|---|---|---|
| `-Env <env>` | mandatory | reads `config\env\<env>.list` |
| `-Project <name>` | name of the project folder | Hop project name |
| `-HopEnv <name>` | `<project>-<env>` | Hop environment name |
| `-SecretsDir <dir>` | `%USERPROFILE%\.serasoft\secrets` | folder holding the files the manifest names `/run/secrets/<name>` |
| `-HopHome <dir>` | `$env:HOP_HOME` | Hop installation folder (`hop-conf.bat` inside) |

- The project folder is the parent of the script's folder, resolved to an
  absolute path. A relative `-SecretsDir` is resolved against the current
  directory.
- Names (`-Env`, `-Project`, `-HopEnv`) must match `^[A-Za-z0-9_.-]+$`.
- Missing `-HopHome` and `HOP_HOME`, or no `hop-conf.bat` (Windows) /
  `hop-conf.sh` (elsewhere, used by the tests) in it: error.

Exit codes: 0 success; 64 usage error (unknown or missing parameter, invalid
name); 1 manifest, file or registration error. Messages on stderr start with
`ERROR:`; warnings with `WARNING:`. Unknown parameters are usage errors (64),
not PowerShell binding errors: the script declares its parameters itself
(e.g. `[CmdletBinding()]` with explicit checks, or `$args` parsing) so that
the exit code is 64.

## Behaviour

Same as `serasoft-register-env.sh`:

1. **Manifest** `config\env\<env>.list` (missing → exit 1): CR at end of line,
   leading and trailing spaces removed; blank lines and lines starting with `#`
   ignored; a relative path → `<project folder>\<path>` (`/` accepted as
   separator); `/run/secrets/<name>` (one path component) → `<secrets-dir>\<name>`,
   or `<secrets-dir>\<name>.json` if the first does not exist; any other
   absolute path (`/…`, `C:\…`, `\\…`) → error; a resolved path containing `,`
   → error; on Windows only, a resolved path (and the project folder) containing
   `&`, `^` or `%` → error (`hop-conf.bat` forwards `%*` unquoted and PowerShell
   quotes an argument only if it has whitespace, so `cmd.exe` would interpret
   them); every file must exist and be readable; an empty list → error. No
   `hop-conf` call unless every line passes.
2. **Project**: `hop-conf -pl`; lines `  <name> : <home>`. Not registered →
   `hop-conf -pc -p <project> -ph <folder> -pf config/project-config.json`; the
   script saves `config\project-config.json` first and restores it (with a
   `WARNING:`) if Hop rewrote it. Registered with the same home (compared as
   full paths, case-insensitive on Windows) → nothing. Registered with another
   home → exit 1 naming both.
3. **Environment**: `hop-conf -el`; lines `  <name>`. Missing → `-ec`, existing
   → `-em`, with `-e <hop-env> -ep <project> -eu <env> -eg <files joined with ,>`.
4. `Invoke-HopConf` sets `$ErrorActionPreference = 'Continue'` (and
   `$PSNativeCommandUseErrorActionPreference = $false`) in its own scope, so a
   profile or session with `'Stop'` does not turn `hop-conf.bat` stderr lines
   into terminating errors, which would skip the `project-config.json` restore.
5. **Summary** on stdout:
   `OK serasoft-register-env project=<project> hop-env=<hop-env> files=<n>`
   followed by `  Hop GUI: select project <project>, environment <hop-env>`.

## Documentation

Template `README.md`, new section "Registering a local environment on
Windows" (after "Running with cron"):

- the secrets file: a Hop environment file with the variables of
  `config/secrets-example.json` and their values, in
  `%USERPROFILE%\.serasoft\secrets\<name>` or `<name>.json`, where `<name>` is
  the `/run/secrets/<name>` line of the manifest;
- the command:
  `powershell -NoProfile -ExecutionPolicy Bypass -File tools\serasoft-register-env.ps1 -Env local [-HopHome C:\hop]`
  (`-ExecutionPolicy Bypass` applies to that run only and changes no system
  setting);
- close Hop GUI before running it: Hop GUI keeps the configuration in memory
  and may write `hop-config.json` again when it exits;
- re-run after a manifest change.

The "Who owns what" table and the "Project structure" table list the new
script.

## Testing

- pytest `tests/tools/test_serasoft_register_env_ps1.py`, skipped when Docker
  is not available: runs the script with PowerShell 7
  (`mcr.microsoft.com/powershell:7.4-ubuntu-22.04`, MIT) in a container, with
  a fake `hop-conf.sh` in a temporary Hop folder that records its calls and
  answers `-pl`/`-el` from a state file (same fake as
  `test_serasoft_register_env.py`). Cases: new project and environment,
  re-run (environment updated, project kept), secrets as `<name>` and as
  `<name>.json`, default secrets folder (`USERPROFILE` set in the container),
  custom `-Project`/`-HopEnv`, every manifest error with no `hop-conf` call,
  project registered with another home, `project-config.json` restored, usage
  errors (exit 64), missing `-HopHome`/`HOP_HOME`.
- A test that the script file is ASCII only.
- `tests/tools/test_serasoft_sync.py`: the script is template-owned (shipped,
  in the manifest).
- Manual checklist for the user (Windows PowerShell 5.1, Hop 2.16):
  (a) the README command with Hop GUI closed, with `-HopHome` and with only
  `HOP_HOME`: OK line, exit 0;
  (b) Hop GUI: select project/environment, run `check_state.hwf` on a process;
  `hop-config.json` has `C:\...` paths and the secrets `.json` is used;
  (c) re-run unchanged (environment modified, project kept), then change the
  manifest and re-run (new list in the GUI);
  (d) project path with a space;
  (e) project path with an accented character, run twice;
  (f) path with `&`: refused with ERROR, nothing registered (the `& ^ %` check
  runs only on Windows, so it cannot be unit-tested on Linux);
  (g) a profile with `$ErrorActionPreference='Stop'` on a fresh project (stderr
  and project-config restore path);
  (h) errors: missing secrets file (exit 1, `hop-config.json` unchanged), bad
  parameter (exit 64), `git status` clean afterwards;
  (i) optionally the same with `pwsh -File`.

## Out of scope

- Windows versions of `serasoft-sync.sh` and `serasoft-verify.sh` (Git Bash or
  WSL, as the README says).
- Unregistering projects or environments.
