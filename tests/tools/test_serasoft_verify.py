"""Tests for tools/serasoft-verify.sh on hand-made project directories."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "tools" / "serasoft-verify.sh"

OWNED = {
    "main.hwf": "<workflow/>\n",
    "src/template/pre/main_pre_job.hwf": "pre\n",
    "src/template/README.md": "# template\n",
    "config/template-env.json": "{}\n",
    "db/liquibase/master.xml": "<databaseChangeLog/>\n",
}


def write(base, rel, text):
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "project"
    for rel, text in OWNED.items():
        write(proj, rel, text)
    (proj / "tools").mkdir()
    shutil.copy2(VERIFY, proj / "tools" / "serasoft-verify.sh")
    write(proj, "src/project/main/p1/start.hwf", "project\n")
    write(proj, "db/sqlite/data/integrations_db", "seed\n")
    files = sorted([*OWNED, "tools/serasoft-verify.sh"])
    manifest = subprocess.run(["sha256sum", *files], cwd=proj, check=True,
                              capture_output=True, text=True).stdout
    (proj / "SERASOFT_MANIFEST.sha256").write_text(manifest)
    (proj / "SERASOFT_VERSION").write_text("3.2.0 0123456789abcdef\n")
    return proj


def verify(cwd, *args):
    return subprocess.run([str(cwd / "tools" / "serasoft-verify.sh"), *args], cwd=cwd,
                          capture_output=True, text=True, check=False)


def test_intact_project_passes(project):
    r = verify(project)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "OK serasoft-verify version=3.2.0 files=6"


def test_modified_file_fails(project):
    write(project, "main.hwf", "<workflow>changed</workflow>\n")
    r = verify(project)
    assert r.returncode == 1
    assert "main.hwf" in r.stderr


def test_missing_file_fails(project):
    (project / "config" / "template-env.json").unlink()
    r = verify(project)
    assert r.returncode == 1
    assert "config/template-env.json" in r.stderr


@pytest.mark.parametrize("extra", ["src/template/pre/custom.hpl", "db/liquibase/extra.xml"])
def test_extra_file_in_owned_dir_fails(project, extra):
    write(project, extra, "x\n")
    r = verify(project)
    assert r.returncode == 1
    assert extra in r.stderr


def test_extra_symlink_in_owned_dir_fails(project):
    os.symlink("../../main.hwf", project / "src" / "template" / "link.hwf")
    r = verify(project)
    assert r.returncode == 1
    assert "src/template/link.hwf" in r.stderr


def test_owned_dir_symlink_fails(project, tmp_path):
    shutil.move(project / "db" / "liquibase", tmp_path / "elsewhere")
    os.symlink(tmp_path / "elsewhere", project / "db" / "liquibase")
    r = verify(project)
    assert r.returncode == 1
    assert "db/liquibase is a symlink" in r.stderr


def test_empty_version_fails(project):
    (project / "SERASOFT_VERSION").write_text("\n")
    r = verify(project)
    assert r.returncode == 1
    assert "SERASOFT_VERSION" in r.stderr


def test_project_files_and_seeds_ignored(project):
    write(project, "src/project/main/p2/start.hwf", "new process\n")
    write(project, "db/sqlite/data/integrations_db", "rows written by a run\n")
    assert verify(project).returncode == 0


def test_crlf_manifest_accepted(project):
    manifest = project / "SERASOFT_MANIFEST.sha256"
    manifest.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
    assert verify(project).returncode == 0, verify(project).stderr


def test_outside_project_root(project):
    r = subprocess.run([str(project / "tools" / "serasoft-verify.sh")], cwd=project / "src",
                       capture_output=True, text=True, check=False)
    assert r.returncode == 66


def test_arguments_rejected(project):
    assert verify(project, "extra").returncode == 64
