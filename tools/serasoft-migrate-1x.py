#!/usr/bin/env python3
"""Migrate a hop-process-template 1.0.x project to the template tag given with --tag and to the
Serasoft Airflow platform layout: one commit per phase on migration/template-<tag>, a report in
docs/migration-report.md. Run from a checkout of hop-process-template that has the tag (and 1.0.1).
It never pushes. See README.md, "Migrating a template 1.0.x project".

Exit codes: 0 complete, 2 complete with manual work (see the report), 1 stopped, 64 usage error."""
import argparse
import csv
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

TEMPLATE_REPO = Path(__file__).resolve().parents[1]
REFERENCE_TAG = "1.0.1"
REFERENCE_TAGS = ("1.0", REFERENCE_TAG)   # a template file matching either tag is not customised

# Template files of tags 1.0 and 1.0.1 (same paths in both).
TEMPLATE_1X_FILES = [
    "config/project-config.json", "db/postgresql_integrationsdb_model_ddl.sql", "main.hwf",
    "metadata/config/project-config.json", "metadata/pipeline-run-configuration/local.json",
    "metadata/rdbms/integrations_db.json", "metadata/workflow-run-configuration/local.json",
    "src/commons/tools/init_date_dim.hpl", "src/commons/tools/locks/check_lock_variable.hpl",
    "src/commons/tools/locks/clear_synchro_lock.hwf", "src/commons/tools/locks/create_lock_variable.hpl",
    "src/commons/tools/mail_sender.hwf", "src/commons/tools/mail_sender_with_attachment.hwf",
    "src/commons/tools/prepare_feedback_text_based_on_result.hpl", "src/commons/tools/send_feeback_mail.hwf",
    "src/main/starter_job.hwf", "src/post/logging/check_for_soft_errors.hpl", "src/post/post_job_error.hwf",
    "src/post/post_job_success.hwf", "src/post/update_process_reference.hpl",
    "src/pre/init/create_new_hop_process_instance.hpl", "src/pre/init/dummy_init_stuff.hwf",
    "src/pre/init/init_sys_variables.hpl", "src/pre/main_pre_job.hwf",
]
KEPT_FOR_LATER = {"config/project-config.json", "main.hwf", "src/main/starter_job.hwf"}

_SERASOFT = [
    "hop.user", "hop.program.name", "sys.unhandled.exception.subcategory.generic",
    "integrations.db.config.schema", "integrations.db.log.schema", "integrations.db.connection.name",
    "email.success.feedback.enabled", "email.fail.feedback.enabled", "email.application.error.feedback.enabled",
    "email.notactive.feedback.enabled", "email.lock.feedback.enabled", "mail.isauthenticated", "mail.isgmail",
    "smtp.mail.host", "smtp.mail.port", "smtp.mail.user", "smtp.mail.psw", "smtp.trusted.hosts",
    "smtp.check.server.identity", "mail.from.displayname", "mail.from.email", "mail.subject", "mail.subject.error",
    "mail.subject.success", "mail.subject.lock", "mail.subject.application.error", "mail.subject.notactive",
    "default.mail.destination.addresses", "success.mail.destination.addresses", "errors.mail.destination.addresses",
    "lock.mail.destination.addresses", "notactive.mail.destination.addresses",
    "application.error.mail.destination.addresses", "success.mail.text", "error.mail.text", "lock.mail.text",
    "application.error.mail.text", "notactive.mail.text",
]
TEMPLATE_VARS = {n: "serasoft." + n for n in _SERASOFT}
TEMPLATE_VARS.update({
    "integrations.db.db.host": "serasoft.integrations.db.host", "integrations.db.db.name": "serasoft.integrations.db.name",
    "integrations.db.db.port": "serasoft.integrations.db.port", "integrations.db.db.user": "serasoft.integrations.db.user",
    "integrations.db.db.password": "serasoft.integrations.db.pwd", "integrations.db.db.pwd": "serasoft.integrations.db.pwd",
})
RUNTIME_VARS = {
    "v_process_id": "v_process_instance_id", "v_job_run_timestamp": "v_process_run_timestamp",
    "v_job_run_date": "v_process_run_date", "terminated.successfully": "v_terminated_successfully",
    "p_logfile_name": "p_log_filename", "v_last_job_run_timestamp": "v_last_instance_start_timestamp",
}
DROPPED_VARS = {"base.tmp.dir", "lock.dir", "db.type", "hop.project.code", "enable.db.availability.check",
                "default.max.down", "mail.attachment.name.error", "success.email.default.text",
                "error.email.default.text", "integrations.db.connection.name"}
SECRET_RE = re.compile(r"password|pwd|psw|secret|token", re.IGNORECASE)
PATH_RE = re.compile(r"^(/|[A-Za-z]:[\\/])")
REF_RE = re.compile(r"\$\{(PROJECT_HOME|Internal\.Entry\.Current\.Folder|Internal\.Workflow\.Filename\.Folder|"
                    r"Internal\.Pipeline\.Filename\.Directory)\}/([^<>\"'\s;,]+)")
DEPLOYMENT_FILES = ("Dockerfile", ".gitlab-ci.yml", "Jenkinsfile", "docker-compose.yml", "docker-compose.yaml")
ROOT_PARAMS = {"p_base_process_name", "p_logfile_name", "p_process_code"}
CSV_COLUMNS = ("kind", "id", "short_name", "description", "is_active", "event_category_id", "event_type", "name")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"{' '.join(map(str, cmd))} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def git(dest, *args):
    return run(["git", "-C", str(dest), *args]).strip()


def template_show(tag, path):
    r = subprocess.run(["git", "-C", str(TEMPLATE_REPO), "show", f"{tag}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def template_files(tag):
    return set(run(["git", "-C", str(TEMPLATE_REPO), "ls-tree", "-r", "--name-only", tag]).split())


@dataclass
class RootWorkflow:
    path: str
    short_name: str
    target: str
    params: dict = field(default_factory=dict)
    params_without_default: list = field(default_factory=list)


@dataclass
class Report:
    customised: list = field(default_factory=list)
    unknown_processes: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    removed_refs: list = field(default_factory=list)
    events: list = field(default_factory=list)
    paths: list = field(default_factory=list)
    deployment: list = field(default_factory=list)
    runtime_dropped: list = field(default_factory=list)
    secrets: list = field(default_factory=list)
    params_without_default: list = field(default_factory=list)
    moved: list = field(default_factory=list)
    rewrites: dict = field(default_factory=dict)
    old_env_files_removed: list = field(default_factory=list)

    def manual(self):
        return any([self.customised, self.unresolved, self.removed_refs, self.events, self.paths, self.deployment])


@dataclass
class Plan:
    dest: Path
    tag: str
    project: str
    db: str
    files: set
    roots: list
    processes: dict
    categories: list
    subcategories: list
    moves: dict
    removals: list
    equivalents: dict
    old_project_config: dict
    envs: dict
    report: Report


def var_replace(text, mapping):
    """Replace ${old} and %%old%% references of every mapped variable; returns (text, count)."""
    count = 0
    for old in sorted(mapping, key=len, reverse=True):
        pattern = re.compile(r"(\$\{|%%)" + re.escape(old) + r"(\}|%%)")
        text, n = pattern.subn(lambda m: m.group(1) + mapping[old] + m.group(2), text)
        count += n
    return text, count


def rewrite_vars(text):
    return var_replace(text, {**TEMPLATE_VARS, **RUNTIME_VARS})


def classify(name):
    if name in DROPPED_VARS:
        return "drop", name
    mapped = TEMPLATE_VARS.get(name, name)
    if SECRET_RE.search(name):
        return "secret", mapped
    if name in TEMPLATE_VARS:
        return "template", mapped
    if name.startswith(("v_", "p_")):
        return "runtime", name
    return "project", name


def logic_signature(text):
    """Actions/transforms (type, SQL, referenced file name) and hops, independent of paths and layout."""
    root = ET.fromstring(text)
    sig = []
    for tag in ("action", "transform"):
        for el in root.iter(tag):
            fname = (el.findtext("filename") or "").strip()
            sig.append((tag, (el.findtext("name") or "").strip(), (el.findtext("type") or "").strip(),
                        " ".join((el.findtext("sql") or "").split()), PurePosixPath(fname).name))
    for hop in root.iter("hop"):
        sig.append(("hop", (hop.findtext("from") or "").strip(), (hop.findtext("to") or "").strip(),
                    (hop.findtext("enabled") or "").strip(), (hop.findtext("evaluation") or "").strip()))
    return sorted(sig)


def resolve_ref(var, rel, old_file):
    if var == "PROJECT_HOME":
        target = os.path.normpath(rel)
    else:
        target = os.path.normpath(os.path.join(os.path.dirname(old_file), rel))
    return None if target.startswith("..") else target


def find_root_workflows(dest, files):
    roots = []
    for path in sorted(f for f in files if "/" not in f and f.endswith(".hwf")):
        root = ET.parse(dest / path).getroot()
        targets = [(a.findtext("filename") or "").strip() for a in root.iter("action")
                   if (a.findtext("type") or "") == "WORKFLOW"]
        if not any(t.endswith("src/pre/main_pre_job.hwf") for t in targets):
            continue
        main = [t for t in targets if "/src/main/" in t]
        if len(main) != 1:
            fail(f"{path}: cannot find the process workflow (actions calling src/main/: {main})")
        m = REF_RE.search(main[0])
        target = resolve_ref(m.group(1), m.group(2), path) if m else None
        if not target or target not in files:
            fail(f"{path}: the process workflow {main[0]} does not exist")
        params, short_name, no_default = {}, "", []
        for p in root.iter("parameter"):
            name = (p.findtext("name") or "").strip()
            default = (p.findtext("default_value") or "").strip()
            if name == "p_base_process_name":
                short_name = default
            elif name not in ROOT_PARAMS:
                if default:
                    params[name] = default
                else:
                    no_default.append(name)
        roots.append(RootWorkflow(path, short_name, target, params, no_default))
    return roots


def read_csv(path):
    processes, categories, subcategories = {}, [], []
    try:
        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        fail(f"{path}: cannot read the CSV ({e})")
    if not rows or not set(CSV_COLUMNS) <= set(reader.fieldnames or []):
        fail(f"{path}: not an export of tools/serasoft-migrate-1x-export.sql")
    for r in rows:
        if r["kind"] == "process":
            processes[r["short_name"]] = r
        elif r["kind"] == "category":
            categories.append(r)
        elif r["kind"] == "subcategory":
            subcategories.append(r)
    return processes, categories, subcategories


def analyse(args):
    dest = Path(args.dest).resolve()
    if git(dest, "rev-parse", "--show-toplevel") != str(dest):
        fail(f"{dest} is not the root of a Git work tree")
    if git(dest, "status", "--porcelain"):
        fail(f"{dest} has uncommitted changes")
    branch = f"migration/template-{args.tag}"
    if subprocess.run(["git", "-C", str(dest), "rev-parse", "--verify", "--quiet", branch],
                      capture_output=True).returncode == 0:
        fail(f"branch {branch} already exists in {dest}")
    if run(["git", "-C", str(TEMPLATE_REPO), "cat-file", "-t", f"refs/tags/{args.tag}"]).strip() != "tag":
        fail(f"tag {args.tag} is not an annotated tag of {TEMPLATE_REPO}")
    files = set(git(dest, "ls-files").split("\n")) - {""}
    if "src/pre/main_pre_job.hwf" not in files:
        fail(f"{dest} is not a template 1.0.x project (no src/pre/main_pre_job.hwf)")
    report = Report()
    envs = {}
    for spec in args.env:
        name, _, path = spec.partition("=")
        p = Path(path).resolve()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not p.is_file():
            fail(f"--env {spec}: expected <name>=<existing file>")
        try:
            json.loads(p.read_text())["variables"]
        except (ValueError, KeyError, TypeError):
            fail(f"--env {spec}: not a Hop environment file")
        envs[name] = p
    processes, categories, subcategories = read_csv(args.processes)

    roots = find_root_workflows(dest, files)
    if not roots:
        fail("no root workflow calling src/pre/main_pre_job.hwf")
    for r in roots:
        if not r.short_name:
            fail(f"{r.path}: empty p_base_process_name default")
        if r.short_name not in processes:
            fail(f"{r.path}: process {r.short_name} is not in {args.processes}")
        if r.params_without_default:
            report.params_without_default.append((r.short_name, r.params_without_default))
    report.unknown_processes = sorted(set(processes) - {r.short_name for r in roots})

    entries = {r.target for r in roots}
    template_present = [f for f in TEMPLATE_1X_FILES if f in files]
    removals = [f for f in template_present if f not in KEPT_FOR_LATER]
    removals += [r.path for r in roots if r.path not in removals]
    if "src/main/starter_job.hwf" in files and "src/main/starter_job.hwf" not in entries:
        removals.append("src/main/starter_job.hwf")
    root_paths = {r.path for r in roots}   # project copies of main.hwf by design
    for f in removals:
        if f.endswith((".hwf", ".hpl")) and f in TEMPLATE_1X_FILES and f not in root_paths:
            refs = [t for t in (template_show(tag, f) for tag in REFERENCE_TAGS) if t]
            try:
                sig = logic_signature((dest / f).read_text())
                if refs and all(logic_signature(ref) != sig for ref in refs):
                    report.customised.append(f)
            except ET.ParseError:
                report.customised.append(f)

    moves = {}
    def add_move(old, new):
        if new in moves.values() or new in files:
            fail(f"two sources for {new} (one of them {old}); check the processes {sorted(r.short_name for r in roots)}")
        moves[old] = new
    for r in roots:
        target_dir = f"src/project/main/{r.short_name}"
        old_dir = os.path.dirname(r.target)
        if old_dir == "src/main":
            add_move(r.target, f"{target_dir}/start.hwf")
            for f in sorted(files):
                if os.path.dirname(f) == "src/main" and f != r.target and f not in TEMPLATE_1X_FILES:
                    add_move(f, f"{target_dir}/{os.path.basename(f)}")
        else:
            for f in sorted(f for f in files if f.startswith(old_dir + "/")):
                new = f"{target_dir}/{f[len(old_dir) + 1:]}"
                if f == r.target:
                    new = f"{target_dir}/start.hwf"
                add_move(f, new)
    removed = set(removals)
    for f in sorted(files):
        if f in moves or f in removed or f in KEPT_FOR_LATER:
            continue
        if f.startswith("src/"):
            rest = f[len("src/"):]
            if rest.startswith("main/"):          # src/main/<x> not used by a root workflow
                rest = rest[len("main/"):]
            if rest.startswith("commons/"):       # src/commons/<x> and src/main/commons/<x>
                rest = rest[len("commons/"):]
            add_move(f, f"src/project/commons/{rest}")
        elif f.startswith("tools/"):
            add_move(f, f"src/project/{f}")

    tag_files = template_files(args.tag)
    equivalents = {f: "src/template/" + f[len("src/"):] for f in TEMPLATE_1X_FILES
                   if f.startswith("src/") and "src/template/" + f[len("src/"):] in tag_files}
    old_pc = None
    if "config/project-config.json" in files:
        old_pc = json.loads((dest / "config/project-config.json").read_text())
    for f in sorted(files):
        if os.path.basename(f) in DEPLOYMENT_FILES or f.endswith("hop-config.json"):
            report.deployment.append(f)
    project = args.project or dest.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", project):
        fail(f"invalid project name {project}")
    return Plan(dest, args.tag, project, args.db, files, roots, processes, categories, subcategories,
                moves, removals, equivalents, old_pc, envs, report)


def parse_args(argv):
    p = argparse.ArgumentParser(description="Migrate a template 1.0.x project (see README.md).")
    p.add_argument("--dest", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--processes", required=True)
    p.add_argument("--env", action="append", required=True, metavar="NAME=FILE")
    p.add_argument("--project")
    p.add_argument("--db", default="postgresql", choices=["postgresql", "mssql", "sqlite"])
    try:
        return p.parse_args(argv)
    except SystemExit as e:
        sys.exit(64 if e.code else 0)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    plan = analyse(args)
    # Phases 1-6: added by the following tasks.
    print(f"analysis OK: {len(plan.roots)} process(es), {len(plan.moves)} move(s), {len(plan.removals)} removal(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
