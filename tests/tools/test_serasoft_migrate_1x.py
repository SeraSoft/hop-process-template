"""Tests for tools/serasoft-migrate-1x.py on fixture 1.0.x projects (tests/tools/fixtures_1x.py)."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from fixtures_1x import (GIT_ENV, ROOT, env_file, fixture_101, fixture_pre101, fixture_starterjob, git,
                         pipeline, pipeline_action, root_workflow, transform, workflow, write)

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


def _add_process(fx, short_name):
    fx["csv"].write_text(fx["csv"].read_text() + f"process,{short_name},{short_name},Added,Y,,,\n")


def test_stops_when_a_process_folder_has_two_root_workflows(tmp_path):
    fx = fixture_101(tmp_path)
    root_workflow(fx["dest"], "second.hwf", "load_sales_two", "${PROJECT_HOME}/src/main/load_sales_folder/start.hwf")
    git(fx["dest"], "add", "-A")
    git(fx["dest"], "commit", "-qm", "x")
    _add_process(fx, "load_sales_two")
    r = migrate(fx)
    assert r.returncode == 1 and "belongs to more than one process" in r.stderr, r.stderr
    assert "load_sales" in r.stderr and "load_sales_two" in r.stderr
    assert git(fx["dest"], "branch", "--show-current") == "main"


def test_stops_when_two_entries_sit_directly_in_src_main(tmp_path):
    fx = fixture_starterjob(tmp_path)
    write(fx["dest"], "src/main/other_entry.hwf", workflow("other_entry", [], ["START"]))
    root_workflow(fx["dest"], "other.hwf", "sj_two", "${PROJECT_HOME}/src/main/other_entry.hwf")
    git(fx["dest"], "add", "-A")
    git(fx["dest"], "commit", "-qm", "x")
    _add_process(fx, "sj_two")
    r = migrate(fx)
    assert r.returncode == 1 and "belongs to more than one process" in r.stderr, r.stderr


def test_stops_on_unchanged_template_sample(tmp_path):
    fx = fixture_101(tmp_path)
    sample = subprocess.run(["git", "-C", str(ROOT), "show", "1.0.1:main.hwf"], check=True,
                            capture_output=True, text=True).stdout
    write(fx["dest"], "sample.hwf", sample)
    git(fx["dest"], "add", "-A")
    git(fx["dest"], "commit", "-qm", "x")
    r = migrate(fx)
    assert r.returncode == 1 and "sample.hwf is the unchanged template sample (p_base_process_name=template)" in r.stderr


def test_stops_on_invalid_root_xml(tmp_path):
    fx = fixture_101(tmp_path)
    write(fx["dest"], "broken.hwf", "<workflow>\n")
    git(fx["dest"], "add", "-A")
    git(fx["dest"], "commit", "-qm", "x")
    r = migrate(fx)
    assert r.returncode == 1 and "broken.hwf" in r.stderr and "Traceback" not in r.stderr


def test_stops_on_duplicate_csv_short_name(tmp_path):
    fx = fixture_101(tmp_path)
    _add_process(fx, "load_sales")
    r = migrate(fx)
    assert r.returncode == 1 and "load_sales" in r.stderr and "more than once" in r.stderr


def test_stops_on_duplicate_env_name(tmp_path):
    fx = fixture_101(tmp_path)
    r = migrate(fx, "--env", f"dev={fx['envs']['prod']}")
    assert r.returncode == 1 and "dev" in r.stderr and "more than once" in r.stderr


def test_csv_with_bom(tmp_path):
    fx = fixture_101(tmp_path)
    fx["csv"].write_bytes(b"\xef\xbb\xbf" + fx["csv"].read_bytes())
    r = migrate(fx)
    assert r.returncode in (0, 2), r.stderr


def test_stops_without_tags_1_0_and_1_0_1(tmp_path):
    repo = tmp_path / "template"
    (repo / "tools").mkdir(parents=True)
    tool = repo / "tools" / TOOL.name
    tool.write_text(TOOL.read_text())
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "x")
    git(repo, "tag", "-a", TAG, "-m", TAG)
    fx = fixture_101(tmp_path / "p")
    args = ["python3", str(tool), "--dest", str(fx["dest"]), "--tag", TAG, "--processes", str(fx["csv"]),
            "--env", f"dev={fx['envs']['dev']}"]
    r = subprocess.run(args, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    assert r.returncode == 1 and "tags 1.0 and 1.0.1 are needed" in r.stderr and "git fetch --tags" in r.stderr


def test_main_action_with_internal_entry_folder(tmp_path):
    fx = fixture_pre101(tmp_path)
    p = fx["dest"] / "load_a.hwf"
    p.write_text(p.read_text().replace("${PROJECT_HOME}/src/main/", "${Internal.Entry.Current.Folder}/src/main/"))
    git(fx["dest"], "commit", "-qam", "x")
    assert "${Internal.Entry.Current.Folder}/src/main/folder_a/start.hwf" in p.read_text()
    plan = _analyse(fx)
    assert [r.target for r in plan.roots if r.short_name == "proc_a"] == ["src/main/folder_a/start.hwf"]
    assert plan.moves["src/main/folder_a/start.hwf"] == "src/project/main/proc_a/start.hwf"


def test_stops_without_exactly_one_main_action(tmp_path):
    fx = fixture_101(tmp_path)
    p = fx["dest"] / "main.hwf"
    p.write_text(p.read_text().replace("${PROJECT_HOME}/src/main/load_sales_folder/start.hwf",
                                       "${PROJECT_HOME}/elsewhere/start.hwf"))
    git(fx["dest"], "commit", "-qam", "x")
    r = migrate(fx)
    assert r.returncode == 1 and "main.hwf: cannot find the process workflow" in r.stderr


def test_root_tools_folder_moves_to_project(tmp_path):
    fx = fixture_101(tmp_path)
    write(fx["dest"], "tools/run.sh", "echo run\n")
    git(fx["dest"], "add", "-A")
    git(fx["dest"], "commit", "-qm", "x")
    plan = _analyse(fx)
    assert plan.moves["tools/run.sh"] == "src/project/tools/run.sh"


def test_phases_1_to_3(tmp_path):
    fx = fixture_101(tmp_path)
    r = migrate(fx, "--stop-after", "3")
    assert r.returncode == 0, r.stderr
    d = fx["dest"]
    assert git(d, "branch", "--show-current") == f"migration/template-{TAG}"
    log = git(d, "log", "--format=%s", "-3").split("\n")
    assert log == ["Migration: remove template 1.0.x", f"Migration: paths and variables for template {TAG}",
                   f"Migration: project structure for template {TAG}"]
    files = tracked(d)
    assert "src/project/main/load_sales/start.hwf" in files
    assert "src/project/main/load_sales/write_event.hpl" in files
    assert not any(f.startswith(("src/pre/", "src/post/", "src/main/")) for f in files)
    assert "main.hwf" not in files
    start = (d / "src/project/main/load_sales/start.hwf").read_text()
    assert "${PROJECT_HOME}/src/project/main/load_sales/read_sales.hpl" in start
    assert "${v_process_instance_id}" in start and "${serasoft.mail.from.email}" in start
    event = (d / "src/project/main/load_sales/write_event.hpl").read_text()
    assert "${serasoft.integrations.db.connection.name}" in event


def test_pre101_relative_references(tmp_path):
    fx = fixture_pre101(tmp_path)
    assert migrate(fx, "--stop-after", "3").returncode == 0
    d = fx["dest"]
    files = tracked(d)
    assert {"src/project/main/proc_a/start.hwf", "src/project/main/proc_b/start.hwf",
            "src/project/commons/init.hpl"} <= files
    a = (d / "src/project/main/proc_a/start.hwf").read_text()
    assert "${PROJECT_HOME}/src/project/commons/init.hpl" in a
    b = (d / "src/project/main/proc_b/start.hwf").read_text()
    assert "Internal.Entry.Current.Folder" not in b
    assert "${v_process_run_timestamp}" in b


def test_starterjob_layout(tmp_path):
    fx = fixture_starterjob(tmp_path)
    assert migrate(fx, "--stop-after", "3").returncode == 0
    files = tracked(fx["dest"])
    assert {"src/project/main/sj_proc/start.hwf", "src/project/main/sj_proc/step.hpl",
            "src/project/commons/extra/helper.hpl"} <= files
    start = (fx["dest"] / "src/project/main/sj_proc/start.hwf").read_text()
    assert "${PROJECT_HOME}/src/project/main/sj_proc/step.hpl" in start
    assert "${PROJECT_HOME}/src/project/commons/extra/helper.hpl" in start


def test_stop_after_each_phase(tmp_path):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    head = git(d, "rev-parse", "HEAD")
    assert migrate(fx, "--stop-after", "0").returncode == 0
    assert git(d, "branch", "--show-current") == "main" and git(d, "rev-parse", "HEAD") == head
    assert migrate(fx, "--stop-after", "7").returncode == 64


def test_rewrite_report_and_template_references(tmp_path, monkeypatch):
    """Reports references to missing files and to removed template files without an equivalent, maps
    template files with an equivalent to src/template/, finds event steps with the source of their fields."""
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    write(d, "src/main/load_sales_folder/extra.hwf", workflow("extra", [
        pipeline_action("Missing", "${PROJECT_HOME}/src/main/load_sales_folder/missing.hpl"),
        pipeline_action("Attach", "${PROJECT_HOME}/src/commons/tools/mail_sender_with_attachment.hwf", 700),
        pipeline_action("Mail", "${PROJECT_HOME}/src/commons/tools/mail_sender.hwf", 900),
        pipeline_action("Conn", "${Internal.Entry.Current.Folder}/../../../metadata/rdbms/sales_db.json", 1100),
    ], ["START", "Missing", "Attach", "Mail", "Conn"]))
    write(d, "src/main/load_sales_folder/read_log.hpl", pipeline("read_log", [transform(
        "Read", "TableInput", 100, "    <connection>integrations_db</connection>\n    <sql>select 1</sql>\n")], ["Read"]))
    git(d, "add", "-A")
    git(d, "commit", "-qm", "x")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_1x_phases", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = ["--dest", str(d), "--tag", TAG, "--processes", str(fx["csv"])]
    for name, path in fx["envs"].items():
        argv += ["--env", f"{name}={path}"]
    plan = mod.analyse(mod.parse_args(argv))
    mod.phase_structure(plan)
    mod.phase_rewrites(plan)
    mod.phase_removal(plan)
    extra = (d / "src/project/main/load_sales/extra.hwf").read_text()
    assert "${PROJECT_HOME}/src/template/commons/tools/mail_sender.hwf" in extra
    assert "${PROJECT_HOME}/metadata/rdbms/sales_db.json" in extra
    rep = plan.report
    assert [ref for _, ref in rep.unresolved] == ["${PROJECT_HOME}/src/main/load_sales_folder/missing.hpl"]
    assert [ref for _, ref in rep.removed_refs] == ["${PROJECT_HOME}/src/commons/tools/mail_sender_with_attachment.hwf"]
    assert rep.events == [("src/project/main/load_sales/write_event.hpl", "Ins integrations_log_events",
                           "event_subcategory_id, gravity from: Event fields")]
    assert ("src/main/load_sales_folder/start.hwf", "src/project/main/load_sales/start.hwf") in rep.moved
    assert "<connection>${serasoft.integrations.db.connection.name}</connection>" in (
        d / "src/project/main/load_sales/read_log.hpl").read_text()
    assert rep.rewrites["connections"] == 1 and rep.rewrites["paths"] == 3 and rep.rewrites["variables"] == 4
    mod.commit(plan, "phase without changes")   # a phase with nothing to change still gets its commit
    assert git(d, "log", "-1", "--format=%s") == "phase without changes"


def test_template_and_configuration(tmp_path):
    fx = fixture_101(tmp_path)
    r = migrate(fx, "--stop-after", "5")
    assert r.returncode == 0, r.stderr
    d = fx["dest"]
    assert subprocess.run(["tools/serasoft-verify.sh"], cwd=d, capture_output=True).returncode == 0
    files = tracked(d)
    assert {"main.hwf", "src/template/pre/main_pre_job.hwf", "config/template-env.json",
            "config/env/dev.list", "config/env/prod.list", "config/fixture-101.json",
            "config/fixture-101-dev.json", "config/secrets-example.json", "config/load_sales.properties"} <= files
    assert (d / "config/env/prod.list").read_text().splitlines()[-5:] == [
        "config/template-env.json", "config/template-postgresql.json", "config/fixture-101.json",
        "config/fixture-101-prod.json", "/run/secrets/fixture-101_prod"]
    dev = {v["name"]: v["value"] for v in json.loads((d / "config/fixture-101-dev.json").read_text())["variables"]}
    assert dev["serasoft.integrations.db.host"] == "db-dev.example.invalid"
    assert dev["sales.db.host"] == "sales-dev.example.invalid"
    assert dev["serasoft.mail.subject.error"] == "${serasoft.mail.subject} error"
    assert dev["serasoft.execution.log.filename"].startswith("/tmp/fixture-101/logs/")
    assert not any(k in dev for k in ("lock.dir", "db.type", "base.tmp.dir", "serasoft.integrations.db.connection.name"))
    assert not any(SECRET in json.dumps(dev) for SECRET in ("pw-dev", "smtp-dev", "sales-dev\""))
    secrets = {v["name"] for v in json.loads((d / "config/secrets-example.json").read_text())["variables"]}
    assert secrets == {"serasoft.integrations.db.pwd", "serasoft.smtp.mail.psw", "sales.db.password"}
    assert (d / "config/load_sales.properties").read_text().strip().endswith("p_period_type=M")
    pc = json.loads((d / "config/project-config.json").read_text())
    assert pc["config"]["variables"] == []


def test_starterjob_configuration(tmp_path):
    fx = fixture_starterjob(tmp_path)
    assert migrate(fx, "--stop-after", "5").returncode == 0
    d = fx["dest"]
    common = {v["name"]: v["value"] for v in json.loads((d / "config/fixture-starterjob.json").read_text())["variables"]}
    assert common == {"items.per.batch": "10"}
    assert "config/dev-env.json" not in tracked(d)
    secrets = {v["name"] for v in json.loads((d / "config/secrets-example.json").read_text())["variables"]}
    assert "api.token" in secrets
    for f in ("config/fixture-starterjob.json", "config/fixture-starterjob-dev.json"):
        assert "tok-123" not in (d / f).read_text() and "pw-dev" not in (d / f).read_text()


def test_configuration_never_commits_local_credentials(tmp_path):
    """Ignored local files under config/ (credentials of the old setup) stay untracked after phase 5."""
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    (d / ".gitignore").write_text("config/dev-local.json\nconfig/*\n!config/project-config.json\n")
    git(d, "commit", "-qam", "ignore config")
    env_file(d / "config" / "dev-local.json", {"integrations.db.db.password": "local-secret-1"})
    env_file(d / "config" / "old-prod-env.json", {"sales.db.password": "local-secret-2"})
    r = migrate(fx, "--stop-after", "5")
    assert r.returncode == 0, r.stderr
    files = tracked(d)
    assert "config/dev-local.json" not in files and "config/old-prod-env.json" not in files
    assert "config/old-prod-env.json" in r.stderr   # named, left to the operator
    for secret in ("local-secret-1", "local-secret-2", "pw-dev", "pw-prod", "smtp-dev", "sales-prod\""):
        assert subprocess.run(["git", "grep", "-q", secret, "HEAD"], cwd=d).returncode == 1, secret
    assert git(d, "status", "--porcelain", "--untracked-files=no") == ""


def test_common_file_omits_unchanged_1x_defaults(tmp_path):
    fx = fixture_101(tmp_path)
    p = fx["dest"] / "config/project-config.json"
    pc = json.loads(p.read_text())
    pc["config"]["variables"].append({"name": "sales.batch.size", "value": "500"})
    for v in pc["config"]["variables"]:
        if v["name"] == "mail.from.displayname":
            v["value"] = "Sales ETL"
    p.write_text(json.dumps(pc, indent=2) + "\n")
    git(fx["dest"], "commit", "-qam", "x")
    assert migrate(fx, "--stop-after", "5").returncode == 0
    common = {v["name"]: v["value"] for v in json.loads((fx["dest"] / "config/fixture-101.json").read_text())["variables"]}
    assert common == {"sales.batch.size": "500", "serasoft.mail.from.displayname": "Sales ETL"}


def _module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_1x_cfg", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_to_phase_5(fx, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    mod = _module()
    argv = ["--dest", str(fx["dest"]), "--tag", TAG, "--processes", str(fx["csv"])]
    for name, path in fx["envs"].items():
        argv += ["--env", f"{name}={path}"]
    plan = mod.analyse(mod.parse_args(argv))
    for phase in mod.PHASES[:5]:
        phase(plan)
    return plan


def test_root_parameter_credentials_never_in_properties(tmp_path):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    p = d / "main.hwf"
    p.write_text(p.read_text().replace(
        "  </parameters>", "    <parameter>\n      <name>p_db_password</name>\n      <default_value>rootpw-xyz"
        "</default_value>\n      <description/>\n    </parameter>\n    <parameter>\n      <name>p_mail_from</name>\n"
        "      <default_value>${mail.from.email}</default_value>\n      <description/>\n    </parameter>\n"
        "  </parameters>", 1))
    git(d, "commit", "-qam", "x")
    assert migrate(fx, "--stop-after", "5").returncode == 0
    assert subprocess.run(["git", "grep", "-q", "rootpw-xyz", "HEAD"], cwd=d).returncode == 1
    props = (d / "config/load_sales.properties").read_text()
    assert "p_db_password" not in props and "p_period_type=M" in props
    assert "p_mail_from=${serasoft.mail.from.email}" in props   # values rewritten like the workflows
    secrets = {v["name"]: v["value"] for v in json.loads((d / "config/secrets-example.json").read_text())["variables"]}
    assert secrets["p_db_password"] == ""


def test_environment_keeps_defaults_that_override_the_common_file(tmp_path):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    p = d / "config/project-config.json"
    pc = json.loads(p.read_text())
    default = next(v["value"] for v in pc["config"]["variables"] if v["name"] == "mail.from.displayname")
    for v in pc["config"]["variables"]:
        if v["name"] == "mail.from.displayname":
            v["value"] = "CUSTOM"
    p.write_text(json.dumps(pc, indent=2) + "\n")
    git(d, "commit", "-qam", "x")
    env = json.loads(fx["envs"]["dev"].read_text())
    env["variables"].append({"name": "mail.from.displayname", "value": default, "description": ""})
    fx["envs"]["dev"].write_text(json.dumps(env))
    assert migrate(fx, "--stop-after", "5").returncode == 0
    common = {v["name"]: v["value"] for v in json.loads((d / "config/fixture-101.json").read_text())["variables"]}
    dev = {v["name"]: v["value"] for v in json.loads((d / "config/fixture-101-dev.json").read_text())["variables"]}
    prod = {v["name"]: v["value"] for v in json.loads((d / "config/fixture-101-prod.json").read_text())["variables"]}
    assert common["serasoft.mail.from.displayname"] == "CUSTOM"
    assert dev["serasoft.mail.from.displayname"] == default
    assert "serasoft.mail.from.displayname" not in prod


def test_local_config_files_with_special_names_stay_ignored(tmp_path):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    (d / ".gitignore").write_text("config/*\n!config/project-config.json\n")
    git(d, "commit", "-qam", "ignore config")
    env_file(d / "config" / "prod-café.json", {"sales.db.password": "cafe-secret"})
    env_file(d / "config" / "old[1]*?.json", {"sales.db.password": "glob-secret"})
    env_file(d / "config" / "#notes.json", {"sales.db.password": "hash-secret"})
    r = migrate(fx, "--stop-after", "5")
    assert r.returncode == 0, r.stderr
    assert git(d, "status", "--porcelain") == ""
    ignored = set(subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "--others", "--ignored",
                                  "--exclude-standard", "--", "config"], cwd=d, capture_output=True,
                                 text=True).stdout.split("\n"))
    assert {"config/prod-café.json", "config/old[1]*?.json", "config/#notes.json"} <= ignored
    for secret in ("cafe-secret", "glob-secret", "hash-secret"):
        assert subprocess.run(["git", "grep", "-q", secret, "HEAD"], cwd=d).returncode == 1


def test_history_credentials_in_report(tmp_path, monkeypatch):
    plan = _run_to_phase_5(fixture_starterjob(tmp_path), monkeypatch)
    hist = dict(plan.report.history_credentials)
    assert "config/dev-env.json" in hist and "integrations.db.db.password" in hist["config/dev-env.json"]
    assert hist["config/project-config.json"] == ["api.token"]
    assert "tok-123" not in json.dumps(plan.report.history_credentials)
