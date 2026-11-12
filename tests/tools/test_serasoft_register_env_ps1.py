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
    [[ -n "${FAKE_PL_FAIL:-}" ]] && exit 1
    echo "Projects:"
    while IFS='|' read -r n h; do echo "  $n : $h"; echo "    Configuration file: file:$h/config/project-config.json"; done < "$S/projects" ;;
  -el)
    [[ -n "${FAKE_EL_FAIL:-}" ]] && exit 1
    echo "Lifecycle environments:"
    while IFS='|' read -r n p f; do echo "  $n"; echo "    Purpose: x"; echo "    Project name: $p"; done < "$S/envs" ;;
  -pc)
    shift
    while [[ $# -gt 0 ]]; do case "$1" in -p) n=$2 ;; -ph) h=$2 ;; esac; shift 2; done
    has "$n" "$S/projects" && exit 1
    [[ -n "${FAKE_STDERR:-}" ]] && echo "fake stderr line" >&2
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


def run(s, *args, env=None, strict=False):
    e = {"FAKE_HOP_STATE": str(s["state"]), "USERPROFILE": str(s["profile"]), "HOP_HOME": str(s["hop"]),
         "HOME": "/tmp", **(env or {})}
    flags = []
    for k, v in e.items():
        if v is not None:
            flags += ["-e", f"{k}={v}"]
    script = str(s["proj"] / "tools" / "serasoft-register-env.ps1")
    if strict:  # caller with $ErrorActionPreference = 'Stop' (e.g. set by a profile)
        pw = ["-Command", "$ErrorActionPreference='Stop'; & '" + script + "' " + " ".join(args) + "; exit $LASTEXITCODE"]
    else:
        pw = ["-File", script, *args]
    return subprocess.run(
        ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{s['tmp']}:{s['tmp']}",
         "-w", str(s["tmp"]), *flags, IMAGE, "pwsh", "-NoProfile", *pw],
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
    assert f"-ec -e myproj-local -ep myproj -eu local -eg {files(s, s['secrets'] / 'myproj_local')}" in calls(s)


@pytest.mark.parametrize("change,message", [
    (lambda s: (s["proj"] / "config/env/local.list").unlink(), "manifest"),
    (lambda s: (s["proj"] / "config/myproj-local.json").unlink(), "missing or not readable"),
    (lambda s: (s["secrets"] / "myproj_local").unlink(), "missing or not readable"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("/etc/passwd\n"), "absolute paths"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("C:\\x\\y.json\n"), "absolute paths"),
    (lambda s: (s["proj"] / "config/env/local.list").write_text("\\\\server\\share\\x.json\n"), "absolute paths"),
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


def test_missing_project_config(setup):
    s = setup
    (s["proj"] / "config/project-config.json").unlink()
    r = run(s, "-Env", "local")
    assert r.returncode == 1 and "ERROR:" in r.stderr and "project-config.json" in r.stderr
    assert not any(c.startswith(("-pc", "-ec", "-em")) for c in calls(s))


@pytest.mark.parametrize("switch,flag", [("FAKE_PL_FAIL", "-pl"), ("FAKE_EL_FAIL", "-el")])
def test_list_failure(setup, switch, flag):
    r = run(setup, "-Env", "local", env={switch: "1"})
    assert r.returncode == 1 and "ERROR:" in r.stderr and f"hop-conf {flag} failed" in r.stderr


def test_error_action_preference_stop(setup):
    s = setup
    r = run(s, "-Env", "local", env={"FAKE_STDERR": "1", "FAKE_REWRITE": "1"}, strict=True)
    assert r.returncode == 0, r.stderr
    assert "OK serasoft-register-env project=myproj hop-env=myproj-local files=4" in r.stdout
    assert (s["proj"] / "config/project-config.json").read_text() == PROJECT_CONFIG
