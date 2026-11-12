# serasoft-register-env.ps1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a Windows (PowerShell 5.1 and 7) version of `tools/serasoft-register-env.sh` that registers a project environment in Hop from `config/env/<env>.list`, shipped by the template sync.

**Architecture:** one PowerShell script with the Bash script's behaviour, calling `hop-conf.bat` on Windows and `hop-conf.sh` elsewhere; tested on Linux with PowerShell 7 in Docker and a fake `hop-conf.sh`; template-owned like the Bash script.

**Tech Stack:** PowerShell 5.1/7, pytest, Docker images `mcr.microsoft.com/powershell` (MIT).

Spec: `docs/superpowers/specs/2026-11-12-register-env-ps1-design.md`.

## Global Constraints

- English everywhere; no real customer or project names (`myproj`, `myproject`).
- One task = one commit; do not push.
- No new dependencies in the template (Docker images are used by tests only).
- The script file is ASCII only and runs on Windows PowerShell 5.1 (no `??`, no ternary, no `-Parallel`, no PowerShell 7-only cmdlets).
- Exit codes: 0 success, 64 usage error (unknown/missing parameter, invalid name), 1 manifest/file/registration error. Messages on stderr start with `ERROR:` / `WARNING:`.
- Summary line exactly: `OK serasoft-register-env project=<project> hop-env=<hop-env> files=<n>`.
- Secrets: default folder `%USERPROFILE%\.serasoft\secrets`; `/run/secrets/<name>` → `<dir>\<name>`, or `<dir>\<name>.json` when the first is missing.

## Issues

| Task | Issue |
|---|---|
| 1 | `#81` |
| 2 | `#82` |

Branch: `feat/register-env-ps1` (exists, holds the spec). Tests: `python3 -m pytest tests/tools -q` (129 pass before this work; Docker needed for the new file, which is skipped without it). The test image is chosen by architecture: `mcr.microsoft.com/powershell:7.4-mariner-2.0-arm64` on arm64 (this machine), `mcr.microsoft.com/powershell:7.4-ubuntu-22.04` on amd64. The PowerShell images have no `awk`: the fake `hop-conf.sh` of these tests is Bash only.

The script and the tests below were prototyped and run together before writing this plan (23 passed on PowerShell 7.4.6, arm64).

---

### Task 1: the PowerShell script and its tests (#81)

**Files:**
- Create: `tools/serasoft-register-env.ps1`
- Create: `tests/tools/test_serasoft_register_env_ps1.py`

- [ ] **Step 1: Write the tests** — create `tests/tools/test_serasoft_register_env_ps1.py`:

```python
"""Tests for tools/serasoft-register-env.ps1, run with PowerShell 7 in Docker against a fake hop-conf.sh."""
import os
from pathlib import Path
import platform
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "serasoft-register-env.ps1"
# Official PowerShell images (MIT); the multi-arch tags have no arm64 variant.
IMAGE = ("mcr.microsoft.com/powershell:7.4-mariner-2.0-arm64" if platform.machine() in ("aarch64", "arm64")
         else "mcr.microsoft.com/powershell:7.4-ubuntu-22.04")

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")

# Bash only (the PowerShell images have no awk); same behaviour as the fake of test_serasoft_register_env.py.
FAKE_HOP_CONF = r"""#!/usr/bin/env bash
S="$FAKE_HOP_STATE"
touch "$S/projects" "$S/envs"
echo "$*" >> "$S/calls.log"
has() { local n=$1 f=$2 a; while IFS='|' read -r a _; do [[ "$a" == "$n" ]] && return 0; done < "$f"; return 1; }
case "$1" in
  -pl)
    echo "Projects:"
    while IFS='|' read -r n h; do echo "  $n : $h"; echo "    Configuration file: file:$h/config/project-config.json"; done < "$S/projects" ;;
  -el)
    echo "Lifecycle environments:"
    while IFS='|' read -r n p f; do echo "  $n"; echo "    Purpose: x"; echo "    Project name: $p"; done < "$S/envs" ;;
  -pc)
    shift
    while [[ $# -gt 0 ]]; do case "$1" in -p) n=$2 ;; -ph) h=$2 ;; esac; shift 2; done
    has "$n" "$S/projects" && exit 1
    echo "$n|$h" >> "$S/projects"
    if [[ -n "${FAKE_REWRITE:-}" ]]; then echo '{"rewritten": true}' > "$h/config/project-config.json"; fi
    if [[ -n "${FAKE_PC_FAIL:-}" ]]; then echo "fake pc boom" >&2; exit 1; fi ;;
  -ec|-em)
    a=$1; shift
    if [[ -n "${FAKE_ENV_FAIL:-}" ]]; then echo "fake env boom" >&2; exit 1; fi
    while [[ $# -gt 0 ]]; do case "$1" in -e) n=$2 ;; -ep) p=$2 ;; -eg) f=$2 ;; esac; shift 2; done
    if has "$n" "$S/envs"; then [[ "$a" == -em ]] || { echo "fake env boom" >&2; exit 1; }
    else [[ "$a" == -ec ]] || { echo "fake env boom" >&2; exit 1; }; fi
    : > "$S/envs.tmp"
    while IFS='|' read -r x rest; do [[ "$x" == "$n" ]] || echo "$x|$rest" >> "$S/envs.tmp"; done < "$S/envs"
    mv "$S/envs.tmp" "$S/envs"
    echo "$n|$p|$f" >> "$S/envs" ;;
  *) exit 2 ;;
esac
"""

PROJECT_CONFIG = '{\n  "metadataBaseFolder" : "${PROJECT_HOME}/metadata"\n}\n'


@pytest.fixture
def setup(tmp_path):
    hop = tmp_path / "hop"
    hop.mkdir()
    (hop / "hop-conf.sh").write_text(FAKE_HOP_CONF)
    (hop / "hop-conf.sh").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    proj = tmp_path / "myproj"
    (proj / "tools").mkdir(parents=True)
    shutil.copy2(SCRIPT, proj / "tools" / "serasoft-register-env.ps1")
    (proj / "config" / "env").mkdir(parents=True)
    (proj / "config" / "project-config.json").write_text(PROJECT_CONFIG)
    for f in ("template-env.json", "template-sqlite.json", "myproj-local.json"):
        (proj / "config" / f).write_text('{"variables": []}\n')
    (proj / "config" / "env" / "local.list").write_text(
        "# local environment\r\n\r\nconfig/template-env.json\r\n  config/template-sqlite.json  \r\n"
        "config/myproj-local.json\r\n/run/secrets/myproj_local\r\n")
    profile = tmp_path / "profile"
    secrets = profile / ".serasoft" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "myproj_local").write_text('{"variables": []}\n')
    return {"hop": hop, "state": state, "proj": proj, "profile": profile, "secrets": secrets, "tmp": tmp_path}


def run(s, *args, env=None):
    e = {"FAKE_HOP_STATE": str(s["state"]), "USERPROFILE": str(s["profile"]), "HOP_HOME": str(s["hop"]),
         "HOME": "/tmp", **(env or {})}
    flags = []
    for k, v in e.items():
        if v is not None:
            flags += ["-e", f"{k}={v}"]
    return subprocess.run(
        ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{s['tmp']}:{s['tmp']}",
         "-w", str(s["tmp"]), *flags, IMAGE, "pwsh", "-NoProfile", "-File",
         str(s["proj"] / "tools" / "serasoft-register-env.ps1"), *args],
        capture_output=True, text=True, check=False)


def calls(s):
    log = s["state"] / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def files(s, secret):
    p = s["proj"]
    return ",".join([f"{p}/config/template-env.json", f"{p}/config/template-sqlite.json",
                     f"{p}/config/myproj-local.json", str(secret)])


def test_script_is_ascii():
    assert all(b < 128 for b in SCRIPT.read_bytes())


def test_first_registration_default_secrets_dir(setup):
    s = setup
    r = run(s, "-Env", "local")
    assert r.returncode == 0, r.stderr
    assert "OK serasoft-register-env project=myproj hop-env=myproj-local files=4" in r.stdout
    assert "Hop GUI: select project myproj, environment myproj-local" in r.stdout
    assert f"-pc -p myproj -ph {s['proj']} -pf config/project-config.json" in calls(s)
    assert f"-ec -e myproj-local -ep myproj -eu local -eg {files(s, s['secrets'] / 'myproj_local')}" in calls(s)


def test_rerun_updates_environment_and_keeps_project(setup):
    s = setup
    assert run(s, "-Env", "local").returncode == 0
    r = run(s, "-Env", "local")
    assert r.returncode == 0, r.stderr
    assert sum(c.startswith("-pc") for c in calls(s)) == 1
    assert any(c.startswith("-em -e myproj-local") for c in calls(s))


def test_secret_with_json_extension(setup):
    s = setup
    (s["secrets"] / "myproj_local").rename(s["secrets"] / "myproj_local.json")
    r = run(s, "-Env", "local")
    assert r.returncode == 0, r.stderr
    assert files(s, s["secrets"] / "myproj_local.json") in calls(s)[-1]


def test_custom_names_and_secrets_dir(setup):
    s = setup
    other = s["tmp"] / "other-secrets"
    other.mkdir()
    (other / "myproj_local").write_text('{"variables": []}\n')
    r = run(s, "-Env", "local", "-Project", "p1", "-HopEnv", "dev-box", "-SecretsDir", str(other))
    assert r.returncode == 0, r.stderr
    assert f"-ec -e dev-box -ep p1 -eu local -eg {files(s, other / 'myproj_local')}" in calls(s)


def test_hop_home_parameter(setup):
    s = setup
    r = run(s, "-Env", "local", "-HopHome", str(s["hop"]), env={"HOP_HOME": None})
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("change,message", [
    (lambda s: (s["proj"] / "config/env/local.list").unlink(), "manifest"),
    (lambda s: (s["proj"] / "config/myproj-local.json").unlink(), "missing or not readable"),
    (lambda s: (s["secrets"] / "myproj_local").unlink(), "missing or not readable"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("/etc/passwd\n"), "absolute paths"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("C:\\x\\y.json\n"), "absolute paths"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("/run/secrets/a/b\n"), "invalid secret path"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("# only comments\n\n"), "lists no file"),
])
def test_manifest_errors_touch_nothing(setup, change, message):
    s = setup
    change(s)
    r = run(s, "-Env", "local")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr and message in r.stderr
    assert calls(s) == []


def test_comma_in_path(setup):
    s = setup
    (s["proj"] / "config/a,b.json").write_text('{"variables": []}\n')
    (s["proj"] / "config/env/local.list").write_text("config/a,b.json\n")
    r = run(s, "-Env", "local")
    assert r.returncode == 1 and "comma" in r.stderr
    assert calls(s) == []


def test_project_registered_elsewhere(setup):
    s = setup
    (s["state"] / "projects").write_text("myproj|/somewhere/else\n")
    r = run(s, "-Env", "local")
    assert r.returncode == 1
    assert "/somewhere/else" in r.stderr and "-Project" in r.stderr
    assert not any(c.startswith(("-pc", "-ec", "-em")) for c in calls(s))


def test_project_config_restored(setup):
    s = setup
    r = run(s, "-Env", "local", env={"FAKE_REWRITE": "1"})
    assert r.returncode == 0, r.stderr
    assert "WARNING: hop-conf rewrote config/project-config.json" in r.stderr
    assert (s["proj"] / "config/project-config.json").read_text() == PROJECT_CONFIG


def test_registration_failure(setup):
    s = setup
    r = run(s, "-Env", "local", env={"FAKE_ENV_FAIL": "1"})
    assert r.returncode == 1 and "fake env boom" in r.stderr


@pytest.mark.parametrize("args", [[], ["-Env"], ["-Env", "local", "-Bogus", "x"], ["local"]])
def test_usage(setup, args):
    r = run(setup, *args)
    assert r.returncode == 64
    assert "usage:" in r.stderr
    assert calls(setup) == []


def test_invalid_name(setup):
    r = run(setup, "-Env", "local", "-HopEnv", "bad name")
    assert r.returncode == 64 and "invalid name" in r.stderr


def test_missing_hop_home(setup):
    r = run(setup, "-Env", "local", env={"HOP_HOME": None})
    assert r.returncode == 1 and "HOP_HOME" in r.stderr
```

- [ ] **Step 2: Run them, expect failures** (the script does not exist)

Run: `python3 -m pytest tests/tools/test_serasoft_register_env_ps1.py -q`
Expected: errors/failures on the missing `tools/serasoft-register-env.ps1`.

- [ ] **Step 3: Write the script** — create `tools/serasoft-register-env.ps1` (ASCII only; LF line endings like the other scripts):

```powershell
# Registers this project and one of its environments in the local Hop
# installation (hop-config.json), from config/env/<env>.list, for local
# development with Hop GUI on Windows (Windows PowerShell 5.1 or PowerShell 7).
# Lines /run/secrets/<name> of the manifest are mapped to <secrets-dir>\<name>,
# or <secrets-dir>\<name>.json. Safe to re-run: an existing environment gets
# the current file list. Close Hop GUI before running it.
# Same behaviour, checks and exit codes as tools/serasoft-register-env.sh.
# See README.md (src/template/README.md in projects), "Registering a local
# environment on Windows". This file must stay ASCII (Windows PowerShell 5.1).
#
# Usage: tools\serasoft-register-env.ps1 -Env <env> [-Project <name>] [-HopEnv <name>] [-SecretsDir <dir>] [-HopHome <dir>]

$UsageText = 'usage: tools\serasoft-register-env.ps1 -Env <env> [-Project <name>] [-HopEnv <name>] [-SecretsDir <dir>] [-HopHome <dir>]'

function Exit-Usage { [Console]::Error.WriteLine($UsageText); exit 64 }
function Exit-Error([string]$Message) { [Console]::Error.WriteLine("ERROR: $Message"); exit 1 }
function Write-Warn([string]$Message) { [Console]::Error.WriteLine("WARNING: $Message") }

# Parameters parsed by hand: an unknown or incomplete parameter exits with 64,
# like the Bash script (a param() block would fail with a PowerShell error).
$opt = @{ Env = ''; Project = ''; HopEnv = ''; SecretsDir = ''; HopHome = '' }
$i = 0
while ($i -lt $args.Count) {
  $key = [string]$args[$i]
  if (-not $key.StartsWith('-') -or ($i + 1) -ge $args.Count) { Exit-Usage }
  $name = @($opt.Keys | Where-Object { $_ -eq $key.Substring(1) })
  if ($name.Count -ne 1) { Exit-Usage }
  $opt[$name[0]] = [string]$args[$i + 1]
  $i += 2
}
if (-not $opt.Env) { Exit-Usage }

$OnWindows = ($env:OS -eq 'Windows_NT')
$ProjectHome = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
if (-not $opt.Project) { $opt.Project = Split-Path -Leaf $ProjectHome }
if (-not $opt.HopEnv) { $opt.HopEnv = $opt.Project + '-' + $opt.Env }
foreach ($n in @($opt.Env, $opt.Project, $opt.HopEnv)) {
  if ($n -cnotmatch '^[A-Za-z0-9_.-]+$') {
    [Console]::Error.WriteLine("ERROR: invalid name '$n' (letters, digits, '_', '.', '-' only)")
    exit 64
  }
}

$SecretsDir = $opt.SecretsDir
if (-not $SecretsDir) {
  if (-not $env:USERPROFILE) { Exit-Error 'USERPROFILE is not set: use -SecretsDir' }
  $SecretsDir = [IO.Path]::Combine($env:USERPROFILE, '.serasoft', 'secrets')
}
# hop-conf runs from the Hop folder: every path must be absolute
if (-not [IO.Path]::IsPathRooted($SecretsDir)) { $SecretsDir = Join-Path (Get-Location).ProviderPath $SecretsDir }

$HopHome = $opt.HopHome
if (-not $HopHome) { $HopHome = $env:HOP_HOME }
if (-not $HopHome) { Exit-Error 'HOP_HOME environment variable is not set (or use -HopHome)' }
if ($OnWindows) { $HopConf = Join-Path $HopHome 'hop-conf.bat' } else { $HopConf = Join-Path $HopHome 'hop-conf.sh' }
if (-not (Test-Path -LiteralPath $HopConf -PathType Leaf)) { Exit-Error "$HopConf not found" }

function Invoke-HopConf([string[]]$HopArgs) {
  $out = & $HopConf @HopArgs 2>&1 | ForEach-Object { "$_" }
  return @{ Code = $LASTEXITCODE; Out = ($out -join "`n") }
}

# --- manifest: every line is checked before hop-config.json is touched ---
$Manifest = [IO.Path]::Combine($ProjectHome, 'config', 'env', $opt.Env + '.list')
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) { Exit-Error "manifest $Manifest not found" }
$Files = @()
foreach ($raw in [IO.File]::ReadAllLines($Manifest)) {
  $line = $raw.Trim()
  if ($line -eq '' -or $line.StartsWith('#')) { continue }
  if ($line.StartsWith('/run/secrets/')) {
    $secret = $line.Substring('/run/secrets/'.Length)
    if ($secret -eq '' -or $secret.Contains('/') -or $secret.Contains('\')) { Exit-Error "${Manifest}: invalid secret path: $line" }
    $path = Join-Path $SecretsDir $secret
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -and (Test-Path -LiteralPath "$path.json" -PathType Leaf)) { $path = "$path.json" }
  } elseif ($line.StartsWith('/') -or $line.StartsWith('\') -or $line -match '^[A-Za-z]:') {
    Exit-Error "${Manifest}: absolute paths are allowed only under /run/secrets/: $line"
  } else {
    $path = Join-Path $ProjectHome ($line.Replace('/', [IO.Path]::DirectorySeparatorChar))
  }
  if ($path.Contains(',')) { Exit-Error "${Manifest}: the path of '$line' contains a comma: $path" }
  $readable = $false
  if (Test-Path -LiteralPath $path -PathType Leaf) {
    try { [IO.File]::OpenRead($path).Dispose(); $readable = $true } catch { $readable = $false }
  }
  if (-not $readable) { Exit-Error "${Manifest}: $path (from '$line') is missing or not readable" }
  $Files += $path
}
if ($Files.Count -eq 0) { Exit-Error "$Manifest lists no file" }

# --- project ---
$ProjectConfig = [IO.Path]::Combine($ProjectHome, 'config', 'project-config.json')
if (-not (Test-Path -LiteralPath $ProjectConfig -PathType Leaf)) { Exit-Error "$ProjectConfig not found" }
$r = Invoke-HopConf @('-pl')
if ($r.Code -ne 0) { Exit-Error 'hop-conf -pl failed' }
$RegisteredHome = ''
foreach ($l in ($r.Out -split "`n")) {
  if ($l -match '^  (\S+) : (.*)$' -and $Matches[1] -ceq $opt.Project) { $RegisteredHome = $Matches[2].Trim(); break }
}
function Get-Normalized([string]$p) { return [IO.Path]::GetFullPath($p).TrimEnd('\', '/') }
if (-not $RegisteredHome) {
  $backup = [IO.File]::ReadAllBytes($ProjectConfig)
  $r = Invoke-HopConf @('-pc', '-p', $opt.Project, '-ph', $ProjectHome, '-pf', 'config/project-config.json')
  $after = [IO.File]::ReadAllBytes($ProjectConfig)
  if ([Convert]::ToBase64String($after) -ne [Convert]::ToBase64String($backup)) {
    [IO.File]::WriteAllBytes($ProjectConfig, $backup)
    Write-Warn 'hop-conf rewrote config/project-config.json: original content restored'
  }
  if ($r.Code -ne 0) { Exit-Error ("hop-conf: cannot register project " + $opt.Project + "`n" + $r.Out) }
} else {
  $same = if ($OnWindows) { (Get-Normalized $RegisteredHome) -eq (Get-Normalized $ProjectHome) } else { (Get-Normalized $RegisteredHome) -ceq (Get-Normalized $ProjectHome) }
  if (-not $same) { Exit-Error ("project " + $opt.Project + " is already registered with home $RegisteredHome, not $ProjectHome (use -Project <name>)") }
}

# --- environment ---
$r = Invoke-HopConf @('-el')
if ($r.Code -ne 0) { Exit-Error 'hop-conf -el failed' }
$Action = '-ec'
foreach ($l in ($r.Out -split "`n")) {
  if ($l -match '^  (\S+)\s*$' -and $Matches[1] -ceq $opt.HopEnv) { $Action = '-em'; break }
}
$r = Invoke-HopConf @($Action, '-e', $opt.HopEnv, '-ep', $opt.Project, '-eu', $opt.Env, '-eg', ($Files -join ','))
if ($r.Code -ne 0) { Exit-Error ("hop-conf ${Action}: cannot register environment " + $opt.HopEnv + "`n" + $r.Out) }

Write-Output ("OK serasoft-register-env project=" + $opt.Project + " hop-env=" + $opt.HopEnv + " files=" + $Files.Count)
Write-Output ("  Hop GUI: select project " + $opt.Project + ", environment " + $opt.HopEnv)
exit 0
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/tools/test_serasoft_register_env_ps1.py -q` → 23 passed; then `python3 -m pytest tests/tools -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/serasoft-register-env.ps1 tests/tools/test_serasoft_register_env_ps1.py
git commit -m "serasoft-register-env.ps1: register a project environment on Windows"
```

---

### Task 2: ship and document the script (#82)

**Files:**
- Modify: `tools/serasoft-sync.sh:64`
- Modify: `tests/tools/test_serasoft_sync.py`
- Modify: `README.md`

- [ ] **Step 1: Sync tests** — in `tests/tools/test_serasoft_sync.py`:
  - add `"tools/serasoft-register-env.ps1",` to `SHIPPED` (the list is wrapped in `sorted()`: the position does not matter);
  - in both template fixtures (`template` and `template_with_legacy`), after the line copying `serasoft-register-env.sh`, add
    `shutil.copy2(ROOT / "tools" / "serasoft-register-env.ps1", up / "tools" / "serasoft-register-env.ps1")`;
  - change the two assertions `"added=16 changed=0 removed=0 adopted=0 forced=0"` to `"added=17 changed=0 removed=0 adopted=0 forced=0"`.

- [ ] **Step 2: Run them, expect failures**: `python3 -m pytest tests/tools/test_serasoft_sync.py -q` — `added=16` instead of 17, the script missing from the manifest.

- [ ] **Step 3: Sync** — in `tools/serasoft-sync.sh` line 64 change

```bash
    main.hwf|tools/serasoft-verify.sh|tools/serasoft-register-env.sh) return 0 ;;
```
to
```bash
    main.hwf|tools/serasoft-verify.sh|tools/serasoft-register-env.sh|tools/serasoft-register-env.ps1) return 0 ;;
```

- [ ] **Step 4: Run the tests**: `python3 -m pytest tests/tools -q` → all pass.

- [ ] **Step 5: README**
  - "Project structure" table, row `tools/`: `` `serasoft-verify.sh`, `serasoft-register-env.sh` `` → `` `serasoft-verify.sh`, `serasoft-register-env.sh`, `serasoft-register-env.ps1` ``.
  - "Who owns what" table, Template row: after `` `tools/serasoft-register-env.sh`, `` add `` `tools/serasoft-register-env.ps1`, ``.
  - Insert before `## Migrating a template 1.0.x project`:

````markdown
## Registering a local environment on Windows

For local development with Hop GUI on Windows, `tools/serasoft-register-env.ps1` registers the project and one of its environments from `config/env/<env>.list`, like `tools/serasoft-register-env.sh` does on Linux. It runs on Windows PowerShell 5.1 (on every Windows 10/11) and PowerShell 7.

1. **Secrets file.** Each `/run/secrets/<name>` line of the manifest is a Hop environment file with the variables of `config/secrets-example.json` and their real values, kept outside the repository in `%USERPROFILE%\.serasoft\secrets\<name>` or `<name>.json` (e.g. `C:\Users\me\.serasoft\secrets\myproject_local.json`):

   ```json
   { "variables": [ { "name": "myproject.db.pwd", "value": "..." } ] }
   ```

2. **Close Hop GUI**: it keeps the configuration in memory and may write `hop-config.json` again when it exits, dropping the registration.
3. **Register**, from the project folder:

   ```
   powershell -ExecutionPolicy Bypass -File tools\serasoft-register-env.ps1 -Env local -HopHome C:\hop
   ```

   `-ExecutionPolicy Bypass` applies to this run only and changes no system setting. `-HopHome` can be left out when `HOP_HOME` is set. Other parameters: `-Project <name>` (default: the project folder name), `-HopEnv <name>` (default: `<project>-<env>`), `-SecretsDir <folder>`.
4. Open Hop GUI and select the project and the environment printed by the script.

Re-run it after a change of the manifest: the environment gets the new file list. It stops before touching `hop-config.json` when a file of the manifest is missing, and when the project is already registered with another folder (use `-Project`).
````

- [ ] **Step 6: Commit**

```bash
git add tools/serasoft-sync.sh tests/tools/test_serasoft_sync.py README.md
git commit -m "Ship and document serasoft-register-env.ps1"
```

---

## After the tasks (controller)

Final review, push `feat/register-env-ps1`, PR closing #81 and #82. Tag `3.5.0` only when the user asks. The user runs the real check on Windows PowerShell 5.1 (spec, Testing).
