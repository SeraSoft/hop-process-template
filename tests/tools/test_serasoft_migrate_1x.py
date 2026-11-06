"""Tests for tools/serasoft-migrate-1x.py on fixture 1.0.x projects (tests/tools/fixtures_1x.py)."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from fixtures_1x import GIT_ENV, ROOT, fixture_101, fixture_pre101, fixture_starterjob, git, write

TOOL = ROOT / "tools" / "serasoft-migrate-1x.py"
TAG = "3.2.1"


def migrate(fx, *extra, tag=TAG):
    args = ["python3", str(TOOL), "--dest", str(fx["dest"]), "--tag", tag, "--processes", str(fx["csv"])]
    for name, path in fx["envs"].items():
        args += ["--env", f"{name}={path}"]
    return subprocess.run([*args, *extra], capture_output=True, text=True, check=False,
                          env={**os.environ, **GIT_ENV})


def tracked(dest):
    return set(git(dest, "ls-files").split("\n"))


@pytest.fixture(params=[fixture_101, fixture_pre101, fixture_starterjob], ids=["101", "pre101", "starterjob"])
def fx(request, tmp_path):
    return request.param(tmp_path)


def test_stops_on_dirty_tree(tmp_path):
    fx = fixture_101(tmp_path)
    write(fx["dest"], "src/main/load_sales_folder/new.hpl", "x\n")
    r = migrate(fx)
    assert r.returncode == 1 and "uncommitted" in r.stderr
    assert git(fx["dest"], "branch", "--show-current") == "main"


def test_stops_when_not_1x(tmp_path):
    fx = fixture_101(tmp_path)
    git(fx["dest"], "rm", "-q", "src/pre/main_pre_job.hwf")
    git(fx["dest"], "commit", "-q", "-m", "x")
    r = migrate(fx)
    assert r.returncode == 1 and "1.0.x" in r.stderr


def test_stops_on_process_missing_from_csv(tmp_path):
    fx = fixture_101(tmp_path)
    fx["csv"].write_text(fx["csv"].read_text().replace("load_sales", "other_name"))
    r = migrate(fx)
    assert r.returncode == 1 and "load_sales" in r.stderr
    assert git(fx["dest"], "branch", "--show-current") == "main"


def test_stops_on_colliding_moves(tmp_path):
    fx = fixture_pre101(tmp_path)
    p = fx["dest"] / "load_b.hwf"
    p.write_text(p.read_text().replace("<default_value>proc_b</default_value>", "<default_value>proc_a</default_value>"))
    git(fx["dest"], "commit", "-qam", "x")
    r = migrate(fx)
    assert r.returncode == 1 and "proc_a" in r.stderr


def test_usage_errors(tmp_path):
    fx = fixture_101(tmp_path)
    r = subprocess.run(["python3", str(TOOL), "--dest", str(fx["dest"])], capture_output=True, text=True)
    assert r.returncode == 64
    r = migrate(fx, "--db", "oracle")
    assert r.returncode == 64


def test_analysis_succeeds(fx):
    r = migrate(fx)
    assert r.returncode in (0, 2), r.stderr


def test_stops_on_unreadable_or_wrong_csv(tmp_path):
    fx = fixture_101(tmp_path)
    fx["csv"].write_text("kind,id,short_name\nprocess,11,load_sales\n")
    r = migrate(fx)
    assert r.returncode == 1 and "export" in r.stderr
    fx["csv"] = tmp_path / "missing.csv"
    r = migrate(fx)
    assert r.returncode == 1 and "missing.csv" in r.stderr and "Traceback" not in r.stderr


def _analyse(fx):
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_1x", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = ["--dest", str(fx["dest"]), "--tag", TAG, "--processes", str(fx["csv"])]
    for name, path in fx["envs"].items():
        argv += ["--env", f"{name}={path}"]
    return mod.analyse(mod.parse_args(argv))


def test_customisation_ignores_root_workflows(tmp_path):
    plan = _analyse(fixture_101(tmp_path))
    assert "main.hwf" not in plan.report.customised
    assert plan.report.customised == []


def test_customisation_accepts_1_0_and_flags_real_changes(tmp_path):
    fx = fixture_101(tmp_path)
    soft = "src/post/logging/check_for_soft_errors.hpl"
    old = subprocess.run(["git", "-C", str(ROOT), "show", f"1.0:{soft}"], check=True,
                         capture_output=True, text=True).stdout
    write(fx["dest"], soft, old)
    pre = fx["dest"] / "src/pre/init/dummy_init_stuff.hwf"
    pre.write_text(pre.read_text().replace("  </actions>", '    <action>\n      <name>Extra</name>\n'
                                           "      <type>DUMMY</type>\n    </action>\n  </actions>", 1))
    git(fx["dest"], "commit", "-qam", "x")
    plan = _analyse(fx)
    assert soft not in plan.report.customised
    assert plan.report.customised == ["src/pre/init/dummy_init_stuff.hwf"]
