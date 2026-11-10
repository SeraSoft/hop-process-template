"""Builders of template 1.0.x fixture projects for tests/tools/test_serasoft_migrate_1x.py.

Every fixture starts from `git archive 1.0.1` of this repository (the template itself),
then adds project files written here. Names are neutral on purpose."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def write(base, rel, text):
    path = Path(base) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _action(name, typ, x, y, extra=""):
    return (f"    <action>\n      <name>{name}</name>\n      <description/>\n      <type>{typ}</type>\n"
            f"      <attributes/>\n{extra}      <parallel>N</parallel>\n      <xloc>{x}</xloc>\n"
            f"      <yloc>{y}</yloc>\n      <attributes_hac/>\n    </action>\n")


START = _action("START", "SPECIAL", 100, 100,
                "      <DayOfMonth>1</DayOfMonth>\n      <hour>12</hour>\n      <intervalMinutes>60</intervalMinutes>\n"
                "      <intervalSeconds>0</intervalSeconds>\n      <minutes>0</minutes>\n      <repeat>N</repeat>\n"
                "      <schedulerType>0</schedulerType>\n      <weekDay>1</weekDay>\n")


def log_action(name, message, x=300):
    return _action(name, "WRITE_TO_LOG", x, 100,
                   f"      <loglevel>Basic</loglevel>\n      <logmessage>{message}</logmessage>\n      <logsubject>{name}</logsubject>\n")


def pipeline_action(name, filename, x=500):
    return _action(name, "PIPELINE", x, 100,
                   f"      <filename>{filename}</filename>\n      <loglevel>Basic</loglevel>\n      <parameters>\n"
                   f"        <pass_all_parameters>Y</pass_all_parameters>\n      </parameters>\n"
                   f"      <run_configuration>local</run_configuration>\n      <wait_until_finished>Y</wait_until_finished>\n")


def workflow(name, actions, chain):
    hops = "".join(f"    <hop>\n      <from>{a}</from>\n      <to>{b}</to>\n      <enabled>Y</enabled>\n"
                   f"      <evaluation>Y</evaluation>\n      <unconditional>{'Y' if a == 'START' else 'N'}</unconditional>\n    </hop>\n"
                   for a, b in zip(chain, chain[1:]))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<workflow>\n  <name>{name}</name>\n'
            f"  <name_sync_with_filename>N</name_sync_with_filename>\n  <description/>\n  <extended_description/>\n"
            f"  <workflow_version/>\n  <parameters>\n  </parameters>\n  <actions>\n{START}{''.join(actions)}  </actions>\n"
            f"  <hops>\n{hops}  </hops>\n  <notepads>\n  </notepads>\n  <attributes/>\n</workflow>\n")


def pipeline(name, transforms, order):
    hops = "".join(f"    <hop>\n      <from>{a}</from>\n      <to>{b}</to>\n      <enabled>Y</enabled>\n    </hop>\n"
                   for a, b in zip(order, order[1:]))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<pipeline>\n  <info>\n    <name>{name}</name>\n'
            f"    <name_sync_with_filename>Y</name_sync_with_filename>\n    <description/>\n    <extended_description/>\n"
            f"    <pipeline_version/>\n    <pipeline_type>Normal</pipeline_type>\n    <parameters>\n    </parameters>\n"
            f"  </info>\n  <notepads>\n  </notepads>\n  <order>\n{hops}  </order>\n{''.join(transforms)}"
            f"  <transform_error_handling>\n  </transform_error_handling>\n  <attributes/>\n</pipeline>\n")


def transform(name, typ, x, extra=""):
    return (f"  <transform>\n    <name>{name}</name>\n    <type>{typ}</type>\n    <description/>\n"
            f"    <distribute>Y</distribute>\n    <custom_distribution/>\n    <copies>1</copies>\n"
            f"    <partitioning>\n      <method>none</method>\n      <schema_name/>\n    </partitioning>\n{extra}"
            f"    <attributes/>\n    <GUI>\n      <xloc>{x}</xloc>\n      <yloc>100</yloc>\n    </GUI>\n  </transform>\n")


def dummy_pipeline(name):
    return pipeline(name, [transform("Dummy", "Dummy", 100)], ["Dummy"])


EVENT_PIPELINE = pipeline("write_event", [
    transform("Event fields", "Constant", 100,
              "    <fields>\n      <field>\n        <name>event_subcategory_id</name>\n        <type>String</type>\n"
              "        <nullif>APPDT001</nullif>\n      </field>\n      <field>\n        <name>gravity</name>\n"
              "        <type>Integer</type>\n        <nullif>5</nullif>\n      </field>\n    </fields>\n"),
    transform("Ins integrations_log_events", "TableOutput", 300,
              "    <connection>${integrations.db.connection.name}</connection>\n    <schema>${integrations.db.log.schema}</schema>\n"
              "    <table>integrations_log_events</table>\n"),
], ["Event fields", "Ins integrations_log_events"])

SALES_CONNECTION = json.dumps({
    "rdbms": {"POSTGRESQL": {"databaseName": "${sales.db.name}", "pluginId": "POSTGRESQL", "accessType": 0,
                             "hostname": "${sales.db.host}", "password": "${sales.db.password}",
                             "pluginName": "PostgreSQL", "port": "5432", "attributes": {},
                             "manualUrl": "", "username": "${sales.db.user}"}},
    "name": "sales_db"}, indent=2) + "\n"


def env_file(path, variables):
    write(path.parent, path.name, json.dumps(
        {"variables": [{"name": n, "value": v, "description": ""} for n, v in variables.items()]}, indent=2) + "\n")
    return path


def old_env(target):
    return {
        "base.tmp.dir": "/opt/data/tmp", "lock.dir": "${base.tmp.dir}/.lock", "db.type": "PostgreSQL",
        "hop.user": "hopuser",
        "integrations.db.connection.name": "integrations_db",
        "integrations.db.db.host": f"db-{target}.example.invalid", "integrations.db.db.name": "integrations_db",
        "integrations.db.db.port": "5432", "integrations.db.db.user": "writer",
        "integrations.db.db.password": f"pw-{target}",
        "mail.from.email": "etl@example.invalid", "mail.subject": "[${p_base_process_name}]",
        "mail.subject.error": "${mail.subject} error",
        "smtp.mail.host": "smtp.example.invalid", "smtp.mail.psw": f"smtp-{target}",
        "sales.db.host": f"sales-{target}.example.invalid", "sales.db.name": "sales", "sales.db.user": "reader",
        "sales.db.password": f"sales-{target}", "sales.export.dir": "/opt/data/export",
    }


CSV_HEADER = "kind,id,short_name,description,is_active,event_category_id,event_type,name\n"
CSV_EVENTS = ("category,SYS001,,,,,E,SYSTEM EXCEPTION\ncategory,APP001,,,,,E,APPLICATION EXCEPTION\n"
              "subcategory,SYSGE001,,,,SYS001,,GENERIC ERROR\nsubcategory,APPDT001,,,,APP001,,DATA ERROR\n")


def _from_tag(dest):
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "1.0.1"], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)


def _commit(dest):
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "1.0.x project")


def root_workflow(dest, name, short_name, target, extra_params=None):
    """A copy of the 1.0.1 main.hwf for one process, saved as <name> at the project root."""
    text = subprocess.run(["git", "-C", str(ROOT), "show", "1.0.1:main.hwf"], check=True,
                          capture_output=True, text=True).stdout
    text = text.replace("<default_value>template</default_value>", f"<default_value>{short_name}</default_value>")
    text = text.replace("${PROJECT_HOME}/src/main/starter_job.hwf", target)
    for pname, default in (extra_params or {}).items():
        text = text.replace("  </parameters>",
                            f"    <parameter>\n      <name>{pname}</name>\n      <default_value>{default}</default_value>\n"
                            f"      <description/>\n    </parameter>\n  </parameters>", 1)
    write(dest, name, text)


def fixture_101(tmp):
    """Tag 1.0.1, main.hwf for process load_sales calling src/main/load_sales_folder/start.hwf."""
    dest = Path(tmp) / "fixture-101"
    _from_tag(dest)
    root_workflow(dest, "main.hwf", "load_sales", "${PROJECT_HOME}/src/main/load_sales_folder/start.hwf",
                  {"p_period_type": "M", "p_no_default": ""})
    write(dest, "src/main/load_sales_folder/start.hwf", workflow("start", [
        log_action("Log", "LOADSALES period=${p_period_type} id=${v_process_id} from=${mail.from.email}"),
        pipeline_action("Read", "${PROJECT_HOME}/src/main/load_sales_folder/read_sales.hpl"),
    ], ["START", "Log", "Read"]))
    write(dest, "src/main/load_sales_folder/read_sales.hpl", dummy_pipeline("read_sales"))
    write(dest, "src/main/load_sales_folder/write_event.hpl", EVENT_PIPELINE)
    write(dest, "metadata/rdbms/sales_db.json", SALES_CONNECTION)
    write(dest, "Dockerfile", "FROM apache/hop:2.16.0\n")
    _commit(dest)
    envs = {e: env_file(Path(tmp) / f"old-{e}-env.json", old_env(e)) for e in ("dev", "prod")}
    csv_file = write(tmp, "export-101.csv", CSV_HEADER + "process,11,load_sales,Load sales,Y,,,\n"
                     + "process,12,orphan_proc,No root workflow,Y,,,\n" + CSV_EVENTS)
    return {"dest": dest, "csv": csv_file, "envs": envs}


def fixture_pre101(tmp):
    """Pre-1.0.1 references (${Internal.Entry.Current.Folder}), two root workflows, a shared folder,
    folders named differently from the short names, no main.hwf."""
    dest = Path(tmp) / "fixture-pre101"
    _from_tag(dest)
    (dest / "main.hwf").unlink()
    for f in [p for p in dest.rglob("*.h*") if p.suffix in (".hwf", ".hpl")]:
        f.write_text(f.read_text().replace("${PROJECT_HOME}/src/", "${Internal.Entry.Current.Folder}/src/"))
    root_workflow(dest, "load_a.hwf", "proc_a", "${PROJECT_HOME}/src/main/folder_a/start.hwf")
    root_workflow(dest, "load_b.hwf", "proc_b", "${PROJECT_HOME}/src/main/folder_b/start.hwf")
    for f in ("load_a.hwf", "load_b.hwf"):
        p = dest / f
        p.write_text(p.read_text().replace("${PROJECT_HOME}/src/pre/", "${Internal.Entry.Current.Folder}/src/pre/")
                     .replace("${PROJECT_HOME}/src/post/", "${Internal.Entry.Current.Folder}/src/post/")
                     .replace("${PROJECT_HOME}/src/commons/", "${Internal.Entry.Current.Folder}/src/commons/"))
    write(dest, "src/main/folder_a/start.hwf", workflow("start", [
        log_action("Log", "PROCA id=${v_process_id}"),
        pipeline_action("Init", "${PROJECT_HOME}/src/main/commons/init.hpl"),
    ], ["START", "Log", "Init"]))
    write(dest, "src/main/folder_b/start.hwf", workflow("start", [
        log_action("Log", "PROCB ts=${v_job_run_timestamp}"),
        pipeline_action("Init", "${Internal.Entry.Current.Folder}/../commons/init.hpl"),
    ], ["START", "Log", "Init"]))
    write(dest, "src/main/commons/init.hpl", dummy_pipeline("init"))
    _commit(dest)
    envs = {e: env_file(Path(tmp) / f"pre-{e}-env.json", old_env(e)) for e in ("dev", "prod")}
    csv_file = write(tmp, "export-pre101.csv", CSV_HEADER + "process,a1,proc_a,Process A,Y,,,\n"
                     + "process,b1,proc_b,Process B,N,,,\n" + CSV_EVENTS)
    return {"dest": dest, "csv": csv_file, "envs": envs}


def fixture_starterjob(tmp):
    """main.hwf calling starter_job.hwf, process files directly in src/main/, a project folder in
    src/commons/, variables in config/project-config.json, an environment file with credentials in the repository."""
    dest = Path(tmp) / "fixture-starterjob"
    _from_tag(dest)
    root_workflow(dest, "main.hwf", "sj_proc", "${PROJECT_HOME}/src/main/starter_job.hwf")
    write(dest, "src/main/starter_job.hwf", workflow("starter_job", [
        log_action("Log", "SJPROC batch=${items.per.batch}"),
        pipeline_action("Step", "${PROJECT_HOME}/src/main/step.hpl"),
        pipeline_action("Helper", "${PROJECT_HOME}/src/commons/extra/helper.hpl", 700),
    ], ["START", "Log", "Step", "Helper"]))
    write(dest, "src/main/step.hpl", dummy_pipeline("step"))
    write(dest, "src/commons/extra/helper.hpl", dummy_pipeline("helper"))
    pc = json.loads((dest / "config/project-config.json").read_text())
    pc["config"]["variables"] = [{"name": "items.per.batch", "value": "10"},
                                 {"name": "v_job_run_date", "value": "20260101"},
                                 {"name": "api.token", "value": "tok-123"}]
    write(dest, "config/project-config.json", json.dumps(pc, indent=2) + "\n")
    env_file(dest / "config" / "dev-env.json", old_env("dev"))
    _commit(dest)
    csv_file = write(tmp, "export-sj.csv", CSV_HEADER + "process,sj,sj_proc,Starter job process,Y,,,\n" + CSV_EVENTS)
    return {"dest": dest, "csv": csv_file, "envs": {"dev": dest / "config" / "dev-env.json"}}
