"""Tests for tools/serasoft-migrate-1x.py on fixture 1.0.x projects (tests/tools/fixtures_1x.py)."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from fixtures_1x import (GIT_ENV, ROOT, _action, env_file, fixture_101, fixture_pre101, fixture_starterjob, git, log_action,
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


def test_full_migration(fx):
    r = migrate(fx)
    assert r.returncode in (0, 2), r.stderr
    d = fx["dest"]
    assert git(d, "status", "--porcelain") == ""
    assert len(git(d, "log", "--format=%s", "main..HEAD").split("\n")) == 6
    assert subprocess.run(["tools/serasoft-verify.sh"], cwd=d, capture_output=True).returncode == 0
    report = (d / "docs/migration-report.md").read_text()
    for r_ in ("Process map", "Operator checklist"):
        assert r_ in report
    seed = next((d / "db/seed").glob("*_config.sql")).read_text()
    assert "INSERT INTO config.integrations_processes" in seed and "WHERE NOT EXISTS" in seed
    assert "SYSGE001" not in seed
    old = ("${PROJECT_HOME}/src/pre/", "${PROJECT_HOME}/src/post/", "${PROJECT_HOME}/src/main/",
           "${v_process_id}", "${mail.", "${integrations.db.db.", "Internal.Entry.Current.Folder}/src/")
    for f in d.rglob("*.h*"):
        if f.suffix in (".hwf", ".hpl") and "src/template" not in str(f):
            text = f.read_text()
            assert not any(o in text for o in old), (f, [o for o in old if o in text])


def test_report_and_exit_code_101(tmp_path):
    fx = fixture_101(tmp_path)
    r = migrate(fx)
    assert r.returncode == 2, r.stderr          # event step, Dockerfile, path variable
    report = (fx["dest"] / "docs/migration-report.md").read_text()
    assert "write_event.hpl" in report and "Ins integrations_log_events" in report
    assert "Dockerfile" in report and "sales.export.dir" in report
    assert "orphan_proc" in report and "p_no_default" in report
    seed = (fx["dest"] / "db/seed/fixture-101_config.sql").read_text()
    assert "'load_sales'" in seed and "'APPDT001'" in seed and "'APP001'" in seed


def test_report_lists_local_files_history_credentials_and_event_sources(tmp_path):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    (d / ".gitignore").write_text("config/*\n!config/project-config.json\n")
    git(d, "commit", "-qam", "ignore config")
    env_file(d / "config" / "old-prod-env.json", {"sales.db.password": "local-secret-1"})
    r = migrate(fx)
    assert r.returncode == 2, r.stderr
    report = (d / "docs/migration-report.md").read_text(encoding="utf-8")
    assert "`config/old-prod-env.json`" in report
    assert "`config/project-config.json` · `integrations.db.db.pwd`" in report   # credentials in the history
    assert "event_subcategory_id, gravity from: Event fields" in report
    assert "local-secret-1" not in report and "pw-dev" not in report
    assert r.stdout.strip().splitlines()[-2].startswith("OK serasoft-migrate-1x project=fixture-101 processes=1 exit=2")
    assert r.stdout.strip().endswith("docs/migration-report.md")


def test_seed_escapes_quotes(tmp_path):
    fx = fixture_101(tmp_path)
    fx["csv"].write_text(fx["csv"].read_text().replace("Load sales", "Load O'Brien's sales"))
    assert migrate(fx).returncode == 2
    seed = (fx["dest"] / "db/seed/fixture-101_config.sql").read_text()
    assert "'Load O''Brien''s sales'" in seed


# --- Fix round: manual-work exit code, robust rewrites and I/O ---

def _run_phases(fx, monkeypatch, n):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    mod = _module()
    argv = ["--dest", str(fx["dest"]), "--tag", TAG, "--processes", str(fx["csv"])]
    for name, path in fx["envs"].items():
        argv += ["--env", f"{name}={path}"]
    plan = mod.analyse(mod.parse_args(argv))
    for phase in mod.PHASES[:n]:
        phase(plan)
    return mod, plan


def test_manual_work_includes_open_items():
    mod = _module()
    assert not mod.Report().manual()
    for name in ("history_credentials", "old_env_files_removed", "params_without_default",
                 "unknown_processes", "local_config_ignored", "check_by_hand"):
        assert mod.Report(**{name: [("x", ["y"])]}).manual(), name


def test_exit_code_2_when_only_history_credentials(tmp_path, monkeypatch):
    mod, plan = _run_phases(fixture_101(tmp_path), monkeypatch, 5)
    history = plan.report.history_credentials
    assert history
    plan.report = mod.Report(history_credentials=history)
    assert mod.phase_seed_report(plan) == 2
    assert "Exit code: 2" in (plan.dest / "docs/migration-report.md").read_text(encoding="utf-8")


def _seed_db(seed):
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.execute("ATTACH DATABASE ':memory:' AS config")
    c.executescript(
        "CREATE TABLE config.integrations_processes (id varchar(48) PRIMARY KEY NOT NULL, short_name varchar(32) "
        "NOT NULL, description varchar(1024), project varchar(64) NOT NULL, is_active char(1) DEFAULT 'Y' NOT NULL, "
        "is_running char(1) DEFAULT 'N' NOT NULL);\n"
        "CREATE TABLE config.events_categories (id varchar(48) PRIMARY KEY NOT NULL, type char(1) NOT NULL, "
        "name varchar(64) NOT NULL);\n"
        "CREATE TABLE config.events_subcategories (id varchar(48) PRIMARY KEY NOT NULL, event_category_id "
        "varchar(48) NOT NULL, name varchar(64) NOT NULL);\n")
    c.executescript(seed)
    c.executescript(seed)   # idempotent
    return {t: c.execute(f"SELECT * FROM config.{t} ORDER BY id").fetchall()
            for t in ("integrations_processes", "events_categories", "events_subcategories")}


def test_seed_runs_twice_on_sqlite_and_files_end_with_newline(tmp_path):
    fx = fixture_101(tmp_path)
    assert migrate(fx).returncode == 2
    d = fx["dest"]
    seed = (d / "db/seed/fixture-101_config.sql").read_text(encoding="utf-8")
    assert seed.endswith(";\n") and (d / "docs/migration-report.md").read_text(encoding="utf-8").endswith("\n")
    assert _seed_db(seed) == {
        "integrations_processes": [("load_sales", "load_sales", "Load sales", "fixture-101", "Y", "N")],
        "events_categories": [("APP001", "E", "APPLICATION EXCEPTION")],
        "events_subcategories": [("APPDT001", "APP001", "DATA ERROR")]}


@pytest.mark.parametrize("value,expected", [("true", "Y"), ("YES", "Y"), ("1", "Y"),
                                            ("n", "N"), ("False", "N"), ("0", "N"), ("no", "N")])
def test_is_active_normalised(tmp_path, value, expected):
    fx = fixture_101(tmp_path)
    fx["csv"].write_text(fx["csv"].read_text().replace("Load sales,Y,", f"Load sales,{value},"))
    r = migrate(fx)
    assert r.returncode == 2, r.stderr
    rows = _seed_db((fx["dest"] / "db/seed/fixture-101_config.sql").read_text(encoding="utf-8"))
    assert rows["integrations_processes"][0][4] == expected


def test_is_active_invalid_stops(tmp_path):
    fx = fixture_101(tmp_path)
    head = git(fx["dest"], "rev-parse", "HEAD")
    fx["csv"].write_text(fx["csv"].read_text().replace("Load sales,Y,", "Load sales,maybe,"))
    r = migrate(fx)
    assert r.returncode == 1 and "load_sales" in r.stderr and "is_active" in r.stderr
    assert git(fx["dest"], "rev-parse", "HEAD") == head and git(fx["dest"], "branch", "--show-current") == "main"


def test_report_lists_variables_by_name_per_file(tmp_path):
    fx = fixture_101(tmp_path)
    assert migrate(fx).returncode == 2
    report = (fx["dest"] / "docs/migration-report.md").read_text(encoding="utf-8")
    section = report.split("## Variables carried over", 1)[1].split("\n## ", 1)[0]
    dev = next(line for line in section.splitlines() if "`config/fixture-101-dev.json`" in line)
    assert "`integrations.db.db.host` → `serasoft.integrations.db.host`" in dev
    assert "`sales.db.host`" in dev and "`sales.export.dir`" in dev
    props = next(line for line in section.splitlines() if "`config/load_sales.properties`" in line)
    assert "`p_period_type`" in props
    assert "db-dev.example.invalid" not in section and "/opt/data/export" not in section


def test_references_with_backslashes_and_xml_entities(tmp_path, monkeypatch):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    write(d, "src/main/load_sales_folder/win.hwf", workflow("win", [
        log_action("Log", "call &quot;${PROJECT_HOME}/src/main/load_sales_folder/read_sales.hpl&quot;"),
        pipeline_action("Read", "${PROJECT_HOME}\\src\\main\\load_sales_folder\\read_sales.hpl"),
    ], ["START", "Log", "Read"]))
    git(d, "add", "-A")
    git(d, "commit", "-qm", "x")
    _, plan = _run_phases(fx, monkeypatch, 2)
    text = (d / "src/project/main/load_sales/win.hwf").read_text(encoding="utf-8")
    assert "&quot;${PROJECT_HOME}/src/project/main/load_sales/read_sales.hpl&quot;" in text
    assert "<filename>${PROJECT_HOME}/src/project/main/load_sales/read_sales.hpl</filename>" in text
    assert plan.report.unresolved == []


def test_event_writers_found_in_sql_and_schema_qualified_tables(tmp_path, monkeypatch):
    from fixtures_1x import _action
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    write(d, "src/main/load_sales_folder/ev_schema.hpl", pipeline("ev_schema", [
        transform("Ins events", "TableOutput", 100, "    <table>logs.integrations_log_events</table>\n")],
        ["Ins events"]))
    write(d, "src/main/load_sales_folder/ev_sql.hwf", workflow("ev_sql", [
        _action("Sql", "SQL", 300, 100, "      <sql>INSERT INTO logs.INTEGRATIONS_LOG_EVENTS (id) VALUES ('x');\n"
                "DELETE FROM logs.integrations_log_events WHERE 1 = 0</sql>\n")], ["START", "Sql"]))
    git(d, "add", "-A")
    git(d, "commit", "-qm", "x")
    _, plan = _run_phases(fx, monkeypatch, 2)
    paths = [e[0] for e in plan.report.events]
    assert sorted(paths) == ["src/project/main/load_sales/ev_schema.hpl", "src/project/main/load_sales/ev_sql.hwf",
                             "src/project/main/load_sales/write_event.hpl"]
    assert ("src/project/main/load_sales/ev_schema.hpl", "Ins events",
            "event_subcategory_id, gravity from: not found upstream") in plan.report.events


def test_paths_counter_counts_changed_references_only(tmp_path, monkeypatch):
    base = fixture_101(tmp_path / "a")
    _, plan = _run_phases(base, monkeypatch, 2)
    expected = plan.report.rewrites["paths"]
    fx = fixture_101(tmp_path / "b")
    write(fx["dest"], "src/main/load_sales_folder/keep.hwf", workflow("keep", [
        pipeline_action("Conn", "${PROJECT_HOME}/metadata/rdbms/sales_db.json")], ["START", "Conn"]))
    git(fx["dest"], "add", "-A")
    git(fx["dest"], "commit", "-qm", "x")
    _, plan = _run_phases(fx, monkeypatch, 2)
    assert plan.report.rewrites["paths"] == expected


def test_failed_phase_is_named(tmp_path, monkeypatch, capsys):
    fx = fixture_101(tmp_path)
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    mod = _module()
    mod.PHASES[1] = lambda plan: mod.run(["false"])   # fresh module: no restore needed
    argv = ["--dest", str(fx["dest"]), "--tag", TAG, "--processes", str(fx["csv"])]
    for name, path in fx["envs"].items():
        argv += ["--env", f"{name}={path}"]
    with pytest.raises(SystemExit) as e:
        mod.main(argv)
    assert e.value.code == 1
    out, err = capsys.readouterr()
    assert "phase 1: project structure" in out and "phase 2: paths and variables" in out
    assert err.startswith("ERROR: phase 2 (paths and variables): false failed")


def test_crlf_files_keep_their_line_endings(tmp_path, monkeypatch):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    start = d / "src/main/load_sales_folder/start.hwf"
    original = start.read_bytes().replace(b"\n", b"\r\n")
    start.write_bytes(original)
    git(d, "commit", "-qam", "crlf")
    _run_phases(fx, monkeypatch, 2)
    new = (d / "src/project/main/load_sales/start.hwf").read_bytes()
    old_lines, new_lines = original.split(b"\r\n"), new.split(b"\r\n")
    assert len(old_lines) == len(new_lines) and b"\n" not in b"".join(new_lines)
    changed = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    assert len(changed) == 2 and all(b"${" in a for a, _ in changed)   # the log message and the pipeline path


def test_other_moved_files_with_old_references_are_reported(tmp_path, monkeypatch):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    sql = "SELECT '${integrations.db.db.host}';\n"
    write(d, "src/main/load_sales_folder/query.sql", sql)
    write(d, "src/main/load_sales_folder/notes.txt", "see ${PROJECT_HOME}/src/main/load_sales_folder/start.hwf\n")
    write(d, "src/main/load_sales_folder/plain.properties", "batch=10\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "x")
    _, plan = _run_phases(fx, monkeypatch, 2)
    assert [p for p, _ in plan.report.check_by_hand] == ["src/project/main/load_sales/notes.txt",
                                                        "src/project/main/load_sales/query.sql"]
    assert (d / "src/project/main/load_sales/query.sql").read_text() == sql


@pytest.mark.parametrize("n", [1, 2])
def test_stop_after_1_and_2(tmp_path, n):
    fx = fixture_101(tmp_path)
    r = migrate(fx, "--stop-after", str(n))
    assert r.returncode == 0, r.stderr
    d = fx["dest"]
    assert git(d, "status", "--porcelain") == ""
    assert len(git(d, "log", "--format=%s", "main..HEAD").split("\n")) == n


def test_old_env_file_at_the_generated_path_is_replaced(tmp_path):
    """--project dev with the old file config/dev-env.json: the generated file takes its path."""
    fx = fixture_starterjob(tmp_path)
    d = fx["dest"]
    fx["envs"] = {"env": d / "config" / "dev-env.json"}   # generated file: config/dev-env.json
    r = migrate(fx, "--project", "dev")
    assert r.returncode in (0, 2), r.stderr
    assert "pw-dev" not in (d / "config/dev-env.json").read_text()
    assert "`config/dev-env.json`" in (d / "docs/migration-report.md").read_text()


def test_env_file_without_credentials_is_not_in_history_report(tmp_path, monkeypatch):
    fx = fixture_starterjob(tmp_path)
    d = fx["dest"]
    env_file(d / "config" / "dev-env.json", {"sales.db.host": "h.example.invalid"})
    git(d, "commit", "-qam", "env without credentials")
    plan = _run_to_phase_5(fx, monkeypatch)
    assert "config/dev-env.json" in plan.report.old_env_files_removed
    assert "config/dev-env.json" not in dict(plan.report.history_credentials)


def test_report_and_seed_committed_even_if_gitignore_ignores_docs_and_db(tmp_path):
    fx = fixture_101(tmp_path)
    d = fx["dest"]
    (d / ".gitignore").write_text("docs\ndb\n")
    git(d, "add", "-f", ".gitignore")
    git(d, "commit", "-qm", "ignore docs")
    r = migrate(fx)
    assert r.returncode in (0, 2), r.stderr
    assert git(d, "ls-files", "docs/migration-report.md") != ""
    assert "db/seed/fixture-101_config.sql" in tracked(d)
    assert git(d, "status", "--porcelain", "--untracked-files=no") == ""


def test_reports_set_variables_loading_the_process_properties(tmp_path):
    fx = fixture_starterjob(tmp_path)
    d = fx["dest"]
    load = ("      <fields>\n</fields>\n      <file_variable_type>ROOT_WORKFLOW</file_variable_type>\n"
            "      <filename>{}</filename>\n      <replacevars>Y</replacevars>\n")
    write(d, "src/main/starter_job.hwf", workflow("starter_job", [
        log_action("Log", "SJPROC batch=${items.per.batch}"),
        _action("Load Process Variables", "SET_VARIABLES", 600, 100,
                load.format("${Internal.Entry.Current.Folder}/../../config/sj_proc.properties")),
        _action("Load Other Variables", "SET_VARIABLES", 700, 100, load.format("${PROJECT_HOME}/config/other.properties")),
    ], ["START", "Log", "Load Process Variables", "Load Other Variables"]))
    git(d, "commit", "-qam", "process loads its own properties")
    r = migrate(fx)
    assert r.returncode == 2, r.stderr
    report = (d / "docs/migration-report.md").read_text()
    assert ("- `src/project/main/sj_proc/start.hwf` · `Load Process Variables` · `config/sj_proc.properties`"
            in report)
    assert "Load Other Variables" not in report
