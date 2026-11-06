# serasoft-register-env.sh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A template-owned `tools/serasoft-register-env.sh` that registers the project and one environment in the local Hop installation from `config/env/<env>.list`, so a template-based project laid out for the Serasoft Airflow platform can also be started by cron with `hop_runner.sh`.

**Architecture:** Bash script in `tools/`, shipped to projects by `serasoft-sync.sh`. It validates the whole manifest first, then calls `$HOP_HOME/hop-conf.sh` (`-pl`, `-pc`, `-el`, `-ec`/`-em`). pytest tests run it against a fake `hop-conf.sh` that records calls and keeps a small state; a final real run uses the lab images.

**Tech Stack:** Bash 4.4+, GNU coreutils; Apache Hop 2.16/2.19 `hop-conf.sh`; Python 3 + pytest 8.

**Spec:** `docs/superpowers/specs/2026-11-06-register-env-design.md`

## Global Constraints

- Branch `feat/register-env` (exists, holds the spec). One task = one commit. Never push until the controller opens the PR.
- English everywhere.
- Command: `tools/serasoft-register-env.sh --env <env> [--project <name>] [--hop-env <name>] [--secrets-dir <dir>]`; defaults: project = project folder name, hop-env = `<project>-<env>`, secrets-dir = `/etc/serasoft/secrets`. Names match `^[A-Za-z0-9_.-]+$`.
- Exit codes: 0 success; 64 usage/invalid name; 1 manifest, file or registration error. Errors on stderr start with `ERROR:`. Summary line: `OK serasoft-register-env project=<project> hop-env=<hop-env> files=<n>`.
- Manifest rules (same as the platform): blank and `#` lines ignored after trimming; relative path → `<project folder>/<path>`; `/run/secrets/<name>` (one component) → `<secrets-dir>/<name>`; other absolute paths, paths with `,`, missing/unreadable files, empty list → exit 1, **before any `hop-conf` call**.
- `hop-conf.sh` output formats (verified on Hop 2.16.0 and 2.19.0): `-pl` lists projects as lines `  <name> : <home>` (two spaces); `-el` lists environments as lines `  <name>` (two spaces, single field); 2.19 appends lines starting with `Search:`. A second `-pc` for an existing project exits 1. `-pc` with the template's `config/project-config.json` leaves it byte-identical.

## Issues

| Task | Issue |
|---|---|
| 1 | tools/serasoft-register-env.sh — `#62` |
| 2 | Ship serasoft-register-env.sh with the sync; README "Running with cron" — `#63` |

---

### Task 1: `tools/serasoft-register-env.sh`

**Files:** Create `tools/serasoft-register-env.sh`, `tests/tools/test_serasoft_register_env.py`.

**Interfaces:** Produces the script (Task 2 adds it to the sync and documents it).

- [ ] **Step 1: Write the failing tests `tests/tools/test_serasoft_register_env.py`**

~~~python
"""Tests for tools/serasoft-register-env.sh against a fake hop-conf.sh."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "serasoft-register-env.sh"

FAKE_HOP_CONF = r"""#!/usr/bin/env bash
# Fake hop-conf.sh: records calls in $FAKE_HOP_STATE/calls.log, keeps projects and
# environments in $FAKE_HOP_STATE/projects ("name|home") and envs ("name|project|files").
S="$FAKE_HOP_STATE"
touch "$S/projects" "$S/envs"
echo "$*" >> "$S/calls.log"
case "$1" in
  -pl)
    echo "Projects:"
    while IFS='|' read -r n h; do
      echo "  $n : $h"
      echo "    Configuration file: file:$h/config/project-config.json"
    done < "$S/projects"
    echo "Search: include project text files set to 'true'" ;;
  -el)
    echo "Lifecycle environments:"
    while IFS='|' read -r n p f; do
      echo "  $n"
      echo "    Purpose: x"
      echo "    Project name: $p"
    done < "$S/envs" ;;
  -pc)
    shift
    while [[ $# -gt 0 ]]; do case "$1" in -p) n=$2 ;; -ph) h=$2 ;; esac; shift 2; done
    if grep -q "^$n|" "$S/projects"; then exit 1; fi
    echo "$n|$h" >> "$S/projects"
    if [[ -n "${FAKE_REWRITE:-}" ]]; then echo '{"rewritten": true}' > "$h/config/project-config.json"; fi ;;
  -ec|-em)
    a=$1; shift
    while [[ $# -gt 0 ]]; do case "$1" in -e) n=$2 ;; -ep) p=$2 ;; -eg) f=$2 ;; esac; shift 2; done
    exists=$(grep -c "^$n|" "$S/envs")
    if [[ "$a" == -ec && "$exists" != 0 ]] || [[ "$a" == -em && "$exists" == 0 ]]; then exit 1; fi
    grep -v "^$n|" "$S/envs" > "$S/envs.tmp"; mv "$S/envs.tmp" "$S/envs"
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
    shutil.copy2(SCRIPT, proj / "tools" / "serasoft-register-env.sh")
    (proj / "config" / "env").mkdir(parents=True)
    (proj / "config" / "project-config.json").write_text(PROJECT_CONFIG)
    for f in ("template-env.json", "template-postgresql.json", "myproj-prod.json"):
        (proj / "config" / f).write_text('{"variables": []}\n')
    (proj / "config" / "env" / "prod.list").write_text(
        "# prod environment\n\nconfig/template-env.json\n  config/template-postgresql.json  \n"
        "config/myproj-prod.json\n/run/secrets/myproj_prod\n")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "myproj_prod").write_text('{"variables": []}\n')
    return {"hop": hop, "state": state, "proj": proj, "secrets": secrets, "tmp": tmp_path}


def run(setup, *args, env=None):
    full_env = {**os.environ, "HOP_HOME": str(setup["hop"]), "FAKE_HOP_STATE": str(setup["state"])}
    if env:
        full_env.update(env)
    script = setup["proj"] / "tools" / "serasoft-register-env.sh"
    return subprocess.run([str(script), *args], capture_output=True, text=True, env=full_env, check=False)


def calls(setup):
    log = setup["state"] / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def envs(setup):
    return (setup["state"] / "envs").read_text().splitlines()


def test_first_registration(setup):
    s = setup
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 0, r.stderr
    assert "OK serasoft-register-env project=myproj hop-env=myproj-prod files=4" in r.stdout
    assert "-prj:myproj -env:myproj-prod" in r.stdout
    proj = s["proj"].resolve()
    assert f"-pc -p myproj -ph {proj} -pf config/project-config.json" in calls(s)
    files = ",".join([f"{proj}/config/template-env.json", f"{proj}/config/template-postgresql.json",
                      f"{proj}/config/myproj-prod.json", f"{s['secrets']}/myproj_prod"])
    assert f"-ec -e myproj-prod -ep myproj -eu prod -eg {files}" in calls(s)
    assert envs(s) == [f"myproj-prod|myproj|{files}"]


def test_rerun_updates_environment_and_keeps_project(setup):
    s = setup
    assert run(s, "--env", "prod", "--secrets-dir", str(s["secrets"])).returncode == 0
    lst = s["proj"] / "config" / "env" / "prod.list"
    lst.write_text(lst.read_text().replace("config/template-postgresql.json", "config/template-env.json"))
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 0, r.stderr
    assert sum(c.startswith("-pc") for c in calls(s)) == 1
    assert any(c.startswith("-em -e myproj-prod") for c in calls(s))
    assert "template-postgresql" not in envs(s)[0]


def test_default_secrets_dir(setup):
    s = setup
    r = run(s, "--env", "prod")
    assert r.returncode == 1
    assert "/etc/serasoft/secrets/myproj_prod" in r.stderr
    assert calls(s) == []


def test_custom_names(setup):
    s = setup
    r = run(s, "--env", "prod", "--project", "other", "--hop-env", "prod-a", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 0, r.stderr
    assert any(c.startswith("-pc -p other ") for c in calls(s))
    assert envs(s)[0].startswith("prod-a|other|")


@pytest.mark.parametrize("content, fragment", [
    ("config/missing.json\n", "missing or not readable"),
    ("config/a,b.json\n", "comma"),
    ("/etc/passwd\n", "only under /run/secrets/"),
    ("/run/secrets/a/b\n", "invalid secret path"),
    ("# only comments\n\n", "lists no file"),
])
def test_manifest_errors_touch_nothing(setup, content, fragment):
    s = setup
    (s["proj"] / "config" / "env" / "prod.list").write_text(content)
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 1
    assert fragment in r.stderr
    assert calls(s) == []


def test_unreadable_file(setup):
    s = setup
    if os.geteuid() == 0:
        pytest.skip("root can read anything")
    (s["secrets"] / "myproj_prod").chmod(0)
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 1
    assert calls(s) == []


def test_missing_manifest(setup):
    r = run(setup, "--env", "test", "--secrets-dir", str(setup["secrets"]))
    assert r.returncode == 1
    assert "test.list" in r.stderr


def test_project_registered_elsewhere(setup):
    s = setup
    (s["state"] / "projects").write_text("myproj|/somewhere/else\n")
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 1
    assert "/somewhere/else" in r.stderr
    assert not any(c.startswith(("-pc", "-ec", "-em")) for c in calls(s))


def test_project_config_restored_if_rewritten(setup):
    s = setup
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]), env={"FAKE_REWRITE": "1"})
    assert r.returncode == 0, r.stderr
    assert "restored" in r.stderr
    assert (s["proj"] / "config" / "project-config.json").read_text() == PROJECT_CONFIG


@pytest.mark.parametrize("args", [[], ["--env"], ["--env", "prod", "--bogus", "x"],
                                  ["--env", "pr od"], ["--env", "prod", "--hop-env", "a/b"]])
def test_usage_errors(setup, args):
    r = run(setup, *args)
    assert r.returncode == 64
    assert calls(setup) == []


def test_missing_hop_home(setup):
    r = run(setup, "--env", "prod", env={"HOP_HOME": ""})
    assert r.returncode == 1
    assert "HOP_HOME" in r.stderr
~~~

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest -q tests/tools/test_serasoft_register_env.py`
Expected: errors (script missing).

- [ ] **Step 3: Write `tools/serasoft-register-env.sh`**

~~~bash
#!/usr/bin/env bash
# Registers this project and one of its environments in the local Hop
# installation (hop-config.json), from config/env/<env>.list, for executions
# started by cron/hop_runner.sh instead of the Serasoft Airflow platform.
# Lines /run/secrets/<name> of the manifest are mapped to <secrets-dir>/<name>.
# Safe to re-run: an existing environment gets the current file list.
# See README.md (src/template/README.md in projects), "Running with cron".
#
# Usage: tools/serasoft-register-env.sh --env <env> [--project <name>] [--hop-env <name>] [--secrets-dir <dir>]
set -uo pipefail

usage() {
  echo "usage: tools/serasoft-register-env.sh --env <env> [--project <name>] [--hop-env <name>] [--secrets-dir <dir>]" >&2
  exit 64
}
die() { echo "ERROR: $*" >&2; exit 1; }

env_name="" project="" hop_env="" secrets_dir="/etc/serasoft/secrets"
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --env)         env_name="$2" ;;
    --project)     project="$2" ;;
    --hop-env)     hop_env="$2" ;;
    --secrets-dir) secrets_dir="$2" ;;
    *)             usage ;;
  esac
  shift 2
done
[[ -n "$env_name" ]] || usage

unset CDPATH
home="$(cd "$(dirname "$0")/.." && pwd -P)"
project="${project:-$(basename "$home")}"
hop_env="${hop_env:-$project-$env_name}"
for n in "$env_name" "$project" "$hop_env"; do
  [[ "$n" =~ ^[A-Za-z0-9_.-]+$ ]] \
    || { echo "ERROR: invalid name '$n' (letters, digits, '_', '.', '-' only)" >&2; exit 64; }
done

[[ -n "${HOP_HOME:-}" ]] || die "HOP_HOME environment variable is not set"
hop_conf="$HOP_HOME/hop-conf.sh"
[[ -x "$hop_conf" ]] || die "$hop_conf not found or not executable"

# --- manifest: every line is checked before hop-config.json is touched ---
manifest="$home/config/env/$env_name.list"
[[ -f "$manifest" ]] || die "manifest $manifest not found"
files=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  case "$line" in ''|'#'*) continue ;; esac
  if [[ "$line" == /run/secrets/* ]]; then
    name="${line#/run/secrets/}"
    [[ -n "$name" && "$name" != */* ]] || die "$manifest: invalid secret path: $line"
    path="$secrets_dir/$name"
  elif [[ "$line" == /* ]]; then
    die "$manifest: absolute paths are allowed only under /run/secrets/: $line"
  else
    path="$home/$line"
  fi
  [[ "$path" != *,* ]] || die "$manifest: the path of '$line' contains a comma: $path"
  [[ -f "$path" && -r "$path" ]] || die "$manifest: $path (from '$line') is missing or not readable"
  files+=("$path")
done < "$manifest"
[[ ${#files[@]} -gt 0 ]] || die "$manifest lists no file"

# --- project ---
project_config="$home/config/project-config.json"
[[ -f "$project_config" ]] || die "$project_config not found"
listing="$("$hop_conf" -pl 2>/dev/null)" || die "hop-conf.sh -pl failed"
registered_home="$(awk -v p="$project" '/^  [^ ]/ && $1 == p && $2 == ":" { sub(/^  [^ ]+ : /, ""); print; exit }' <<<"$listing")"
if [[ -z "$registered_home" ]]; then
  backup="$(mktemp)"
  trap 'rm -f "$backup"' EXIT
  cp -p "$project_config" "$backup"
  "$hop_conf" -pc -p "$project" -ph "$home" -pf config/project-config.json >/dev/null \
    || die "hop-conf.sh: cannot register project $project"
  if ! cmp -s "$backup" "$project_config"; then
    cp -p "$backup" "$project_config"
    echo "WARNING: hop-conf.sh rewrote config/project-config.json: original content restored" >&2
  fi
elif [[ "$registered_home" != "$home" ]]; then
  die "project $project is already registered with home $registered_home, not $home (use --project <name>)"
fi

# --- environment ---
envs="$("$hop_conf" -el 2>/dev/null)" || die "hop-conf.sh -el failed"
joined="$(IFS=,; printf '%s' "${files[*]}")"
if awk -v e="$hop_env" '/^  [^ ]/ && NF == 1 && $1 == e { found = 1 } END { exit !found }' <<<"$envs"; then
  action=-em
else
  action=-ec
fi
"$hop_conf" "$action" -e "$hop_env" -ep "$project" -eu "$env_name" -eg "$joined" >/dev/null \
  || die "hop-conf.sh $action: cannot register environment $hop_env"

echo "OK serasoft-register-env project=$project hop-env=$hop_env files=${#files[@]}"
echo "  hop_runner.sh main.hwf -prj:$project -env:$hop_env -param:p_base_process_name=<process>"
~~~

Run: `chmod +x tools/serasoft-register-env.sh`

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest -q tests/tools`
Expected: all passed (the existing sync/verify tests included).

- [ ] **Step 5: Commit**

~~~bash
git add tools/serasoft-register-env.sh tests/tools/test_serasoft_register_env.py
git commit -m "tools/serasoft-register-env.sh: register project and environment from config/env/<env>.list"
~~~

---

### Task 2: Ship it with the sync and document it

**Files:** Modify `tools/serasoft-sync.sh` (`owned_path`), `tests/tools/test_serasoft_sync.py`, `README.md`.

**Interfaces:** Consumes the script of Task 1.

- [ ] **Step 1: Failing sync test.** In `tests/tools/test_serasoft_sync.py`:
  - the `template` fixture copies the new script too: after `shutil.copy2(VERIFY, up / "tools" / "serasoft-verify.sh")` add `shutil.copy2(ROOT / "tools" / "serasoft-register-env.sh", up / "tools" / "serasoft-register-env.sh")`; do the same in `template_with_legacy`;
  - add `"tools/serasoft-register-env.sh"` to `SHIPPED` (keep it sorted);
  - in `test_creation` the counter becomes `added=16` (15 + the new script).

Run `python3 -m pytest -q tests/tools/test_serasoft_sync.py` → `test_creation` fails (script not shipped).

- [ ] **Step 2: Ship it.** In `tools/serasoft-sync.sh`, `owned_path`:

~~~bash
    main.hwf|tools/serasoft-verify.sh|tools/serasoft-register-env.sh) return 0 ;;
~~~

Run `python3 -m pytest -q tests/tools` → all passed.

- [ ] **Step 3: README.** In the "Who owns what" table of "Template updates", add `tools/serasoft-register-env.sh` next to `tools/serasoft-verify.sh`. Add a section after "Template updates":

~~~markdown
## Running with cron (`hop_runner.sh`)

The Serasoft Airflow platform reads `config/env/<env>.list` at every run. On a machine where the project is started by cron with `hop_runner.sh` (SeraSoft/useful-scripts), the project and the environment must be registered in the installation's `hop-config.json` first. `tools/serasoft-register-env.sh` does it from the same manifest:

```
export HOP_HOME=/opt/hop
<project>/tools/serasoft-register-env.sh --env prod
```

- Each `/run/secrets/<name>` line of the manifest becomes `/etc/serasoft/secrets/<name>` (the folder the platform uses on its SSH targets; change it with `--secrets-dir`). Keep those files readable only by the user that runs Hop (`chmod 600`).
- The project is registered with the name of its folder (`--project` to change it) and `config/project-config.json`; the environment is named `<project>-<env>` (`--hop-env` to change it), because environment names are shared by every project of the installation.
- Every manifest line is checked first (missing or unreadable file, comma in a path, absolute path outside `/run/secrets/`): on error nothing is registered (exit code `1`).
- Re-run it after a change of the manifest: the existing environment gets the new file list. A project already registered with another folder is an error.

Then:

```
hop_runner.sh main.hwf -prj:<project> -env:<project>-prod -param:p_base_process_name=<process>
```
~~~

- [ ] **Step 4: Commit**

~~~bash
git add tools/serasoft-sync.sh tests/tools/test_serasoft_sync.py README.md
git commit -m "Ship serasoft-register-env.sh with the sync; README: running with cron"
~~~

---

## Final verification (controller)

- [ ] `python3 -m pytest -q tests/tools` — all passed.
- [ ] Real run on `apache/hop:2.16.0` and `apache/hop:2.19.0` with the lab (`tests/hop/lab.sh up`, `copy`): in the copy, a manifest `config/env/lab.list` (`config/template-env.json`, `config/template-postgresql.json`, `/run/secrets/tpl_lab`) and a secrets folder with `tpl_lab` = the lab overrides of `tests/hop/lab-env.json`; inside the container `HOP_HOME=/opt/hop`, run the script with `--env lab --project tpl --secrets-dir <folder>`, then `hop-run.sh -j tpl -e tpl-lab -r local -f /project/main.hwf -p p_base_process_name=vartest` → exit 0 and the `VARTEST` line; re-run the script (environment updated, exit 0); `config/project-config.json` unchanged.
- [ ] Issue checklists done; push; one PR closing both issues; after merge, annotated tag `3.3.0` when the user asks.
