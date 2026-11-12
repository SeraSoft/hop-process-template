"""Tests for tools/serasoft-sync.sh against throw-away template and project repositories."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "tools" / "serasoft-sync.sh"
VERIFY = ROOT / "tools" / "serasoft-verify.sh"

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}

TEMPLATE_FILES = {
    "main.hwf": "<workflow>v1</workflow>\n",
    "src/template/pre/main_pre_job.hwf": "pre v1\n",
    "src/template/post/old_post.hwf": "dropped later\n",
    "src/project/main/default/start.hwf": "sample\n",
    "config/template-env.json": "{\"env\": 1}\n",
    "config/template-postgresql.json": "{\"pg\": 1}\n",
    "config/project-config.json": "{\"project\": 1}\n",
    "metadata/rdbms/integrations_db_postgres.json": "{\"rdbms\": 1}\n",
    "metadata/workflow-log/workflow_log.json": "{\"log\": 1}\n",
    "metadata/pipeline-run-configuration/local.json": "{\"prc\": 1}\n",
    "metadata/workflow-run-configuration/local.json": "{\"wrc\": 1}\n",
    "db/liquibase/master.xml": "<databaseChangeLog/>\n",
    "db/sqlite/data/integrations_db": "seed-a\n",
    "db/sqlite/data/integrations_db.config": "seed-b\n",
    "db/sqlite/data/integrations_db.logs": "seed-c\n",
    "docs/x.md": "docs\n",
    ".github/workflows/x.yml": "on: push\n",
    "integration-tests/t.hwf": "t\n",
    "tests/tools/test_x.py": "x\n",
    "README.md": "# template v1\n",
    ".gitignore": "logs/\n",
}
SEEDS = ["db/sqlite/data/integrations_db", "db/sqlite/data/integrations_db.config",
         "db/sqlite/data/integrations_db.logs"]
SHIPPED = sorted([
    "config/template-env.json",
    "config/template-postgresql.json",
    "db/liquibase/master.xml",
    "main.hwf",
    "metadata/pipeline-run-configuration/local.json",
    "metadata/rdbms/integrations_db_postgres.json",
    "metadata/workflow-log/workflow_log.json",
    "metadata/workflow-run-configuration/local.json",
    "src/template/README.md",
    "src/template/post/old_post.hwf",
    "src/template/pre/main_pre_job.hwf",
    "tools/serasoft-register-env.sh",
    "tools/serasoft-verify.sh",
])
PROJECT_FILES = {
    "README.md": "project\n",
    ".gitignore": "logs/\ntemp/\n",
    "config/project-config.json": "{\"mine\": 1}\n",
    "src/project/main/p1/start.hwf": "p1\n",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def write(base, rel, text):
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def template(tmp_path):
    up = tmp_path / "template"
    for rel, text in TEMPLATE_FILES.items():
        write(up, rel, text)
    (up / "tools").mkdir()
    shutil.copy2(SYNC, up / "tools" / "serasoft-sync.sh")
    shutil.copy2(VERIFY, up / "tools" / "serasoft-verify.sh")
    shutil.copy2(ROOT / "tools" / "serasoft-register-env.sh", up / "tools" / "serasoft-register-env.sh")
    git(up, "init", "-q", "-b", "main")
    commit_all(up, "v1")
    git(up, "tag", "-a", "3.2.0", "-m", "3.2.0 release notes")
    return up


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "project"
    for rel, text in PROJECT_FILES.items():
        write(proj, rel, text)
    git(proj, "init", "-q", "-b", "main")
    commit_all(proj, "init")
    return proj


def sync(template, *args):
    return subprocess.run([str(template / "tools" / "serasoft-sync.sh"), *args],
                          capture_output=True, text=True, check=False,
                          env={**os.environ, **GIT_ENV})


def files(repo):
    out = git(repo, "ls-files", "--others", "--cached", "--exclude-standard")
    return sorted(f for f in out.split("\n") if f)


def from_template(repo):
    return [f for f in files(repo) if f not in PROJECT_FILES
            and f not in {"SERASOFT_VERSION", "SERASOFT_MANIFEST.sha256"}]


def verify(repo):
    return subprocess.run([str(repo / "tools" / "serasoft-verify.sh")], cwd=repo,
                          capture_output=True, text=True, check=False)


def test_creation(template, project):
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OK serasoft-sync tag=3.2.0 commit=")
    assert "added=16 changed=0 removed=0 adopted=0 forced=0" in r.stdout
    assert from_template(project) == sorted(SHIPPED + SEEDS)
    manifest = (project / "SERASOFT_MANIFEST.sha256").read_text().splitlines()
    assert [line.split("  ", 1)[1] for line in manifest] == SHIPPED
    commit = git(template, "rev-parse", "3.2.0^{commit}")
    assert (project / "SERASOFT_VERSION").read_text() == f"3.2.0 {commit}\n"
    assert (project / "README.md").read_text() == "project\n"
    assert (project / "config/project-config.json").read_text() == "{\"mine\": 1}\n"
    assert (project / "src/template/README.md").read_text() == "# template v1\n"
    assert verify(project).returncode == 0


def test_update_from_second_tag(template, project):
    assert sync(template, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    commit_all(project, "template 3.2.0")
    write(template, "main.hwf", "<workflow>v2</workflow>\n")
    (template / "src/template/post/old_post.hwf").unlink()
    write(template, "src/template/pre/new.hpl", "new\n")
    write(template, "db/liquibase/master.xml", "<databaseChangeLog>v2</databaseChangeLog>\n")
    commit_all(template, "v2")
    git(template, "tag", "-a", "3.3.0", "-m", "3.3.0")
    r = sync(template, "--tag", "3.3.0", "--dest", str(project))
    assert r.returncode == 0, r.stderr
    assert "added=1 changed=2 removed=1" in r.stdout
    assert not (project / "src/template/post").exists()
    assert (project / "main.hwf").read_text() == "<workflow>v2</workflow>\n"
    assert "WARNING: db/liquibase/master.xml changed" in r.stderr
    assert verify(project).returncode == 0


def test_second_run_changes_nothing(template, project):
    assert sync(template, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    commit_all(project, "template 3.2.0")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 0, r.stderr
    assert "added=0 changed=0 removed=0" in r.stdout
    assert "WARNING" not in r.stderr
    assert git(project, "status", "--porcelain") == ""


def test_uses_tag_not_working_copy(template, project):
    write(template, "main.hwf", "<workflow>uncommitted</workflow>\n")
    assert sync(template, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    assert (project / "main.hwf").read_text() == "<workflow>v1</workflow>\n"


def test_refuses_lightweight_tag(template, project):
    git(template, "tag", "3.2.1")
    r = sync(template, "--tag", "3.2.1", "--dest", str(project))
    assert r.returncode == 1
    assert "not annotated" in r.stderr


def test_refuses_unknown_tag(template, project):
    r = sync(template, "--tag", "9.9.9", "--dest", str(project))
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_refuses_dirty_destination(template, project):
    write(project, "src/project/main/p1/start.hwf", "uncommitted\n")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 1
    assert "uncommitted changes" in r.stderr


def test_refuses_non_git_destination(template, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    r = sync(template, "--tag", "3.2.0", "--dest", str(plain))
    assert r.returncode == 1
    assert "not inside a Git work tree" in r.stderr


def test_refuses_template_itself(template):
    r = sync(template, "--tag", "3.2.0", "--dest", str(template))
    assert r.returncode == 1


def test_first_sync_refuses_existing_template_file(template, project):
    write(project, "main.hwf", "<workflow>copied by hand</workflow>\n")
    commit_all(project, "manual copy")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 1
    assert "main.hwf" in r.stderr
    assert "--adopt-from" in r.stderr
    assert git(project, "status", "--porcelain") == ""


def test_first_sync_refuses_stale_file_in_owned_dir(template, project):
    write(project, "src/template/custom.hwf", "mine\n")
    commit_all(project, "custom")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 1
    assert "src/template/custom.hwf" in r.stderr


def test_refuses_project_file_in_the_way_on_update(template, project):
    assert sync(template, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    commit_all(project, "template 3.2.0")
    write(template, "config/template-mssql.json", "{}\n")
    commit_all(template, "v2")
    git(template, "tag", "-a", "3.3.0", "-m", "3.3.0")
    write(project, "config/template-mssql.json", "{\"mine\": 1}\n")
    commit_all(project, "own file")
    r = sync(template, "--tag", "3.3.0", "--dest", str(project))
    assert r.returncode == 1
    assert "config/template-mssql.json" in r.stderr


def test_refuses_damaged_manifest(template, project):
    assert sync(template, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    with open(project / "SERASOFT_MANIFEST.sha256", "a") as f:
        f.write("0" * 64 + "  README.md\n")
    commit_all(project, "damaged")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 1
    assert "not a template-owned entry" in r.stderr
    assert (project / "README.md").exists()


def test_seed_files_kept_when_present(template, project):
    assert sync(template, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    write(project, "db/sqlite/data/integrations_db", "rows of a run\n")
    (project / "db/sqlite/data/integrations_db.logs").unlink()
    commit_all(project, "dev runs")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 0, r.stderr
    assert "WARNING: kept local db/sqlite/data/integrations_db" in r.stderr
    assert (project / "db/sqlite/data/integrations_db").read_text() == "rows of a run\n"
    assert (project / "db/sqlite/data/integrations_db.logs").read_text() == "seed-c\n"
    assert "added=1 " in r.stdout
    assert verify(project).returncode == 0


def test_usage(template, project):
    assert sync(template, "--tag", "3.2.0").returncode == 64
    assert sync(template, "--bogus", "x").returncode == 64


LEGACY_FILES = {
    "main.hwf": "<workflow>v0</workflow>\n",
    "src/template/pre/main_pre_job.hwf": "pre v0\n",
    "config/default-env.json": "{\"env\": 0}\n",
    "config/project-config.json": "{\"project\": 0}\n",
    "metadata/rdbms/integrations_db_postgres.json": "{\"rdbms\": 1}\n",
    "db/liquibase/master-postgresql.xml": "<databaseChangeLog>pg</databaseChangeLog>\n",
    "db/sqlite/data/integrations_db": "seed-old\n",
    "README.md": "# template v0\n",
}


@pytest.fixture
def template_with_legacy(tmp_path):
    """Template whose history starts with a 2.x-like lightweight tag 2.1.2, then 3.2.0."""
    up = tmp_path / "template"
    for rel, text in LEGACY_FILES.items():
        write(up, rel, text)
    git(up, "init", "-q", "-b", "main")
    commit_all(up, "v0")
    git(up, "tag", "2.1.2")
    for rel in LEGACY_FILES:
        (up / rel).unlink()
    for rel, text in TEMPLATE_FILES.items():
        write(up, rel, text)
    (up / "tools").mkdir(exist_ok=True)
    shutil.copy2(SYNC, up / "tools" / "serasoft-sync.sh")
    shutil.copy2(VERIFY, up / "tools" / "serasoft-verify.sh")
    shutil.copy2(ROOT / "tools" / "serasoft-register-env.sh", up / "tools" / "serasoft-register-env.sh")
    commit_all(up, "v1")
    git(up, "tag", "-a", "3.2.0", "-m", "3.2.0")
    return up


@pytest.fixture
def project_2x(tmp_path):
    """A project holding the 2.1.2 template files copied by hand, plus its own files."""
    proj = tmp_path / "project"
    for rel, text in LEGACY_FILES.items():
        if rel != "README.md":
            write(proj, rel, text)
    for rel, text in PROJECT_FILES.items():
        write(proj, rel, text)
    git(proj, "init", "-q", "-b", "main")
    commit_all(proj, "2.x project")
    return proj


def test_adopt_identical_files(template_with_legacy, project_2x):
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project_2x), "--adopt-from", "2.1.2")
    assert r.returncode == 0, r.stderr
    assert "adopted=5 forced=0" in r.stdout
    assert not (project_2x / "config/default-env.json").exists()
    assert not (project_2x / "db/liquibase/master-postgresql.xml").exists()
    assert (project_2x / "main.hwf").read_text() == "<workflow>v1</workflow>\n"
    assert (project_2x / "config/project-config.json").read_text() == "{\"mine\": 1}\n"
    assert (project_2x / "db/sqlite/data/integrations_db").read_text() == "seed-old\n"
    assert "WARNING: kept local db/sqlite/data/integrations_db" in r.stderr
    assert "WARNING: db/liquibase/master.xml changed since 2.1.2" in r.stderr
    assert verify(project_2x).returncode == 0


def test_adopt_refuses_locally_modified_file(template_with_legacy, project_2x):
    write(project_2x, "main.hwf", "<workflow>v0 patched</workflow>\n")
    commit_all(project_2x, "local patch")
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project_2x), "--adopt-from", "2.1.2")
    assert r.returncode == 1
    assert "main.hwf" in r.stderr
    assert "--force" in r.stderr
    assert git(project_2x, "status", "--porcelain") == ""


def test_adopt_force_overwrites_and_removes(template_with_legacy, project_2x):
    write(project_2x, "main.hwf", "<workflow>v0 patched</workflow>\n")
    write(project_2x, "src/template/custom.hwf", "mine\n")
    commit_all(project_2x, "local changes")
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project_2x),
             "--adopt-from", "2.1.2", "--force")
    assert r.returncode == 0, r.stderr
    assert "forced=2" in r.stdout
    assert (project_2x / "main.hwf").read_text() == "<workflow>v1</workflow>\n"
    assert not (project_2x / "src/template/custom.hwf").exists()
    assert verify(project_2x).returncode == 0


def test_adopt_auto_picks_starting_tag(template_with_legacy, project_2x):
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project_2x), "--adopt-from", "auto")
    assert r.returncode == 0, r.stderr
    assert "adopt-from auto: 2.1.2 (5/6 files identical)" in r.stderr


def test_adopt_refused_with_manifest(template_with_legacy, project):
    assert sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project)).returncode == 0
    commit_all(project, "template 3.2.0")
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project), "--adopt-from", "2.1.2")
    assert r.returncode == 1
    assert "first sync only" in r.stderr


def test_adopt_unknown_tag(template_with_legacy, project_2x):
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(project_2x), "--adopt-from", "0.0.1")
    assert r.returncode == 1
    assert "0.0.1" in r.stderr


def test_force_needs_adopt_from(template, project):
    assert sync(template, "--tag", "3.2.0", "--dest", str(project), "--force").returncode == 64


def test_warns_when_template_files_are_ignored(template, project):
    write(project, ".gitignore", "logs/\nconfig/*\n")
    commit_all(project, "ignore config")
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 0, r.stderr
    warning = [l for l in r.stderr.splitlines() if l.startswith("WARNING: ignored by .gitignore")]
    assert len(warning) == 1
    assert "config/template-env.json" in warning[0]
    assert "config/template-postgresql.json" in warning[0]
    assert "main.hwf" not in warning[0]


def test_no_ignored_warning_without_ignore_rules(template, project):
    r = sync(template, "--tag", "3.2.0", "--dest", str(project))
    assert r.returncode == 0, r.stderr
    assert "ignored by .gitignore" not in r.stderr


@pytest.fixture
def monorepo(tmp_path):
    """A repository with the Hop project in etl/ and other content next to it."""
    repo = tmp_path / "mono"
    write(repo, "README.md", "mono\n")
    write(repo, "reporting/README.md", "reports\n")
    for rel, text in PROJECT_FILES.items():
        write(repo, f"etl/{rel}", text)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "init")
    return repo


def outside_etl(repo):
    status = git(repo, "status", "--porcelain", "--untracked-files=all")
    # git() strips the output, which can eat the leading space of the first line
    paths = [line.split(maxsplit=1)[1] for line in status.splitlines()]
    return [p for p in paths if not p.startswith("etl/")]


def test_creation_in_subfolder(template, monorepo):
    etl = monorepo / "etl"
    r = sync(template, "--tag", "3.2.0", "--dest", str(etl))
    assert r.returncode == 0, r.stderr
    assert "added=16 changed=0 removed=0 adopted=0 forced=0" in r.stdout
    assert from_template(etl) == sorted(SHIPPED + SEEDS)
    assert (etl / "SERASOFT_VERSION").is_file()
    assert not (monorepo / "SERASOFT_VERSION").exists()
    assert not (monorepo / "main.hwf").exists()
    assert outside_etl(monorepo) == []
    assert verify(etl).returncode == 0


def test_adopt_in_subfolder(template_with_legacy, tmp_path):
    repo = tmp_path / "mono2x"
    write(repo, "reporting/README.md", "reports\n")
    for rel, text in LEGACY_FILES.items():
        if rel != "README.md":
            write(repo, f"etl/{rel}", text)
    for rel, text in PROJECT_FILES.items():
        write(repo, f"etl/{rel}", text)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "2.x project in etl/")
    r = sync(template_with_legacy, "--tag", "3.2.0", "--dest", str(repo / "etl"), "--adopt-from", "2.1.2")
    assert r.returncode == 0, r.stderr
    assert "adopted=5 forced=0" in r.stdout
    assert not (repo / "etl/config/default-env.json").exists()
    assert outside_etl(repo) == []
    assert verify(repo / "etl").returncode == 0


def test_subfolder_refused_when_work_tree_is_dirty(template, monorepo):
    write(monorepo, "reporting/draft.md", "uncommitted\n")
    r = sync(template, "--tag", "3.2.0", "--dest", str(monorepo / "etl"))
    assert r.returncode == 1
    assert "uncommitted changes" in r.stderr
    assert "mono has uncommitted changes" in r.stderr
    assert not (monorepo / "etl/main.hwf").exists()


def test_subfolder_root_gitignore_warning(template, monorepo):
    write(monorepo, ".gitignore", "etl/config/*\n")
    commit_all(monorepo, "ignore etl config")
    r = sync(template, "--tag", "3.2.0", "--dest", str(monorepo / "etl"))
    assert r.returncode == 0, r.stderr
    warning = [l for l in r.stderr.splitlines() if l.startswith("WARNING: ignored by .gitignore")]
    assert len(warning) == 1
    assert "config/template-env.json" in warning[0]


def test_refuses_folder_inside_template(template):
    r = sync(template, "--tag", "3.2.0", "--dest", str(template / "docs"))
    assert r.returncode == 1
    assert "template" in r.stderr
