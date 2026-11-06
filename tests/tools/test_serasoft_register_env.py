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
    if [[ -n "$(awk -F'|' -v n="$n" '$1==n' "$S/projects")" ]]; then exit 1; fi
    echo "$n|$h" >> "$S/projects"
    if [[ -n "${FAKE_REWRITE:-}" ]]; then echo '{"rewritten": true}' > "$h/config/project-config.json"; fi
    if [[ -n "${FAKE_PC_FAIL:-}" ]]; then echo "fake pc boom" >&2; exit 1; fi ;;
  -ec|-em)
    a=$1; shift
    if [[ -n "${FAKE_ENV_FAIL:-}" ]]; then echo "fake env boom" >&2; exit 1; fi
    while [[ $# -gt 0 ]]; do case "$1" in -e) n=$2 ;; -ep) p=$2 ;; -eg) f=$2 ;; esac; shift 2; done
    exists=$(awk -F'|' -v n="$n" '$1==n' "$S/envs" | wc -l)
    if [[ "$a" == -ec && "$exists" != 0 ]] || [[ "$a" == -em && "$exists" == 0 ]]; then echo "fake env boom" >&2; exit 1; fi
    awk -F'|' -v n="$n" '$1!=n' "$S/envs" > "$S/envs.tmp"; mv "$S/envs.tmp" "$S/envs"
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
    if Path("/etc/serasoft/secrets/myproj_prod").exists():
        pytest.skip("host has /etc/serasoft/secrets/myproj_prod")
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


def test_relative_secrets_dir_becomes_absolute(setup):
    s = setup
    full_env = {**os.environ, "HOP_HOME": str(s["hop"]), "FAKE_HOP_STATE": str(s["state"])}
    script = s["proj"] / "tools" / "serasoft-register-env.sh"
    r = subprocess.run([str(script), "--env", "prod", "--secrets-dir", "secrets"], cwd=s["tmp"],
                       capture_output=True, text=True, env=full_env, check=False)
    assert r.returncode == 0, r.stderr
    assert envs(s)[0].endswith(f",{s['secrets'].resolve()}/myproj_prod")


def test_project_config_restored_if_pc_fails(setup):
    s = setup
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]),
            env={"FAKE_REWRITE": "1", "FAKE_PC_FAIL": "1"})
    assert r.returncode == 1
    assert "fake pc boom" in r.stderr
    assert (s["proj"] / "config" / "project-config.json").read_text() == PROJECT_CONFIG


def test_env_failure_shows_hop_conf_output(setup):
    s = setup
    (s["state"] / "projects").write_text(f"myproj|{s['proj'].resolve()}\n")
    (s["state"] / "envs").write_text("")
    r = run(s, "--env", "prod", "--hop-env", "x", "--secrets-dir", str(s["secrets"]), env={"FAKE_ENV_FAIL": "1"})
    assert r.returncode == 1
    assert "fake env boom" in r.stderr


def test_similar_project_names_not_confused(setup):
    s = setup
    for other in ("myproj-old", "my.proj", "xmyproj"):
        (s["state"] / "projects").write_text(f"{other}|/elsewhere\n")
        r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
        assert r.returncode == 0, (other, r.stderr)
        assert any(c.startswith("-pc -p myproj ") for c in calls(s)), other
        (s["state"] / "calls.log").unlink()
        (s["state"] / "envs").write_text("")


def test_dotted_project_name_not_matched_by_regex_name(setup):
    s = setup
    (s["state"] / "projects").write_text("my.proj|/elsewhere\n")
    r = run(s, "--env", "prod", "--project", "myxproj", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 0, r.stderr
    assert any(c.startswith("-pc -p myxproj ") for c in calls(s))


def test_project_home_with_space_read_entirely(setup):
    s = setup
    proj = s["proj"].resolve()
    (s["state"] / "projects").write_text(f"myproj|{proj}\n")
    spaced = s["tmp"] / "my dir"
    spaced.mkdir()
    shutil.move(str(s["proj"]), str(spaced / "myproj"))
    s["proj"] = spaced / "myproj"
    (s["state"] / "projects").write_text(f"myproj|{s['proj'].resolve()}\n")
    r = run(s, "--env", "prod", "--secrets-dir", str(s["secrets"]))
    assert r.returncode == 0, r.stderr
    assert not any(c.startswith("-pc") for c in calls(s))
