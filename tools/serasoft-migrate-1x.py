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
                    r"Internal\.Pipeline\.Filename\.Directory)\}[/\\]([^<>\"'\s;,&]+)")
DEPLOYMENT_FILES = ("Dockerfile", ".gitlab-ci.yml", "Jenkinsfile", "docker-compose.yml", "docker-compose.yaml")
ROOT_PARAMS = {"p_base_process_name", "p_logfile_name", "p_process_code"}
IS_ACTIVE = {"y": "Y", "true": "Y", "1": "Y", "yes": "Y", "n": "N", "false": "N", "0": "N", "no": "N"}
CSV_COLUMNS = ("kind", "id", "short_name", "description", "is_active", "event_category_id", "event_type", "name")


CURRENT_PHASE = ""   # "phase N (title): " while a phase runs, to name it in errors


def fail(message):
    print(f"ERROR: {CURRENT_PHASE}{message}", file=sys.stderr)
    sys.exit(1)


def read_text(path):
    """UTF-8 text with its line endings unchanged (CRLF files stay CRLF)."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except UnicodeDecodeError as e:
        fail(f"{path}: not UTF-8 text ({e})")


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


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
    local_config_ignored: list = field(default_factory=list)
    history_credentials: list = field(default_factory=list)   # (file, credential names): rotate them
    check_by_hand: list = field(default_factory=list)   # (moved file not rewritten, what it still contains)
    variables: list = field(default_factory=list)       # (written file, origin, ["old → new"], [project names])

    def manual(self):
        return any([self.customised, self.unresolved, self.removed_refs, self.events, self.paths, self.deployment,
                    self.history_credentials, self.old_env_files_removed, self.params_without_default,
                    self.unknown_processes, self.local_config_ignored, self.check_by_hand])


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
    processes_csv: str = ""


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
    rel = rel.replace("\\", "/")
    if var == "PROJECT_HOME":
        target = os.path.normpath(rel)
    else:
        target = os.path.normpath(os.path.join(os.path.dirname(old_file), rel))
    return None if target.startswith("..") else target


def find_root_workflows(dest, files):
    roots = []
    for path in sorted(f for f in files if "/" not in f and f.endswith(".hwf")):
        try:
            root = ET.parse(dest / path).getroot()
        except ET.ParseError as e:
            fail(f"{path}: invalid XML ({e})")
        targets = [(a.findtext("filename") or "").strip().replace("\\", "/") for a in root.iter("action")
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
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        fail(f"{path}: cannot read the CSV ({e})")
    if not rows or not set(CSV_COLUMNS) <= set(reader.fieldnames or []):
        fail(f"{path}: not an export of tools/serasoft-migrate-1x-export.sql")
    for r in rows:
        if r["kind"] == "process":
            if r["short_name"] in processes:
                fail(f"{path}: process {r['short_name']} appears more than once")
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
    for tag in REFERENCE_TAGS:
        if subprocess.run(["git", "-C", str(TEMPLATE_REPO), "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
                          capture_output=True).returncode != 0:
            fail(f"tags 1.0 and 1.0.1 are needed in {TEMPLATE_REPO}: git fetch --tags")
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
        if name in envs:
            fail(f"--env {spec}: environment {name} given more than once")
        try:
            json.loads(p.read_text(encoding="utf-8"))["variables"]
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            fail(f"--env {spec}: not a Hop environment file")
        envs[name] = p
    processes, categories, subcategories = read_csv(args.processes)

    roots = find_root_workflows(dest, files)
    if not roots:
        fail("no root workflow calling src/pre/main_pre_job.hwf")
    for r in roots:
        if not r.short_name:
            fail(f"{r.path}: empty p_base_process_name default")
        if r.short_name == "template":
            fail(f"{r.path} is the unchanged template sample (p_base_process_name=template): "
                 "remove it or set its process name")
        if r.short_name not in processes:
            fail(f"{r.path}: process {r.short_name} is not in {args.processes}")
        if r.params_without_default:
            report.params_without_default.append((r.short_name, r.params_without_default))
        active = (processes[r.short_name].get("is_active") or "").strip().lower()
        if active not in IS_ACTIVE:
            fail(f"{args.processes}: process {r.short_name} has is_active={active!r} (expected Y/N, true/false, 1/0, yes/no)")
        processes[r.short_name]["is_active"] = IS_ACTIVE[active]
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
                sig = logic_signature(read_text(dest / f))
                if refs and all(logic_signature(ref) != sig for ref in refs):
                    report.customised.append(f)
            except ET.ParseError:
                report.customised.append(f)

    moves, owners = {}, {}
    def add_move(old, new, owner=None):
        if old in moves and moves[old] != new:
            names = sorted({n for n in (owners.get(old), owner) if n})
            fail(f"{old} belongs to more than one process ({', '.join(names)}): "
                 "a 1.0.x process folder can be migrated for one root workflow only")
        if new in moves.values() or new in files:
            fail(f"two sources for {new} (one of them {old}); check the processes {sorted(r.short_name for r in roots)}")
        moves[old] = new
        owners[old] = owner
    for r in roots:
        target_dir = f"src/project/main/{r.short_name}"
        old_dir = os.path.dirname(r.target)
        if old_dir == "src/main":
            add_move(r.target, f"{target_dir}/start.hwf", r.short_name)
            for f in sorted(files):
                if os.path.dirname(f) == "src/main" and f != r.target and f not in TEMPLATE_1X_FILES:
                    add_move(f, f"{target_dir}/{os.path.basename(f)}", r.short_name)
        else:
            for f in sorted(f for f in files if f.startswith(old_dir + "/")):
                new = f"{target_dir}/{f[len(old_dir) + 1:]}"
                if f == r.target:
                    new = f"{target_dir}/start.hwf"
                add_move(f, new, r.short_name)
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
        old_pc = json.loads(read_text(dest / "config/project-config.json"))
    for f in sorted(files):
        if os.path.basename(f) in DEPLOYMENT_FILES or f.endswith("hop-config.json"):
            report.deployment.append(f)
    project = args.project or dest.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", project):
        fail(f"invalid project name {project}")
    return Plan(dest, args.tag, project, args.db, files, roots, processes, categories, subcategories,
                moves, removals, equivalents, old_pc, envs, report, str(Path(args.processes).resolve()))


def commit(plan, message):
    git(plan.dest, "add", "-A")
    git(plan.dest, "commit", "-q", "--allow-empty", "-m", message)


def phase_structure(plan):
    git(plan.dest, "checkout", "-q", "-b", f"migration/template-{plan.tag}")
    for old, new in sorted(plan.moves.items()):
        (plan.dest / new).parent.mkdir(parents=True, exist_ok=True)
        git(plan.dest, "mv", old, new)
        plan.report.moved.append((old, new))
    commit(plan, f"Migration: project structure for template {plan.tag}")


def count(plan, kind, n=1):
    plan.report.rewrites[kind] = plan.report.rewrites.get(kind, 0) + n


def rewrite_refs(plan, text, old_file):
    def repl(m):
        target = resolve_ref(m.group(1), m.group(2), old_file)
        if target is None:
            plan.report.unresolved.append((old_file, m.group(0)))
            return m.group(0)
        if target in plan.moves:
            new = plan.moves[target]
        elif target in plan.equivalents:
            new = plan.equivalents[target]
        elif target in plan.removals:
            plan.report.removed_refs.append((old_file, m.group(0)))
            return m.group(0)
        elif target in plan.files:
            new = target
        else:
            plan.report.unresolved.append((old_file, m.group(0)))
            return m.group(0)
        new = "${PROJECT_HOME}/" + new
        if new != m.group(0):
            count(plan, "paths")
        return new
    return REF_RE.sub(repl, text)


EVENT_FIELDS = ("event_subcategory_id", "gravity")


def event_steps(root):
    """Transforms writing integrations_log_events, each with the upstream transforms naming its key fields."""
    upstream = {}
    for hop in root.iter("hop"):
        upstream.setdefault((hop.findtext("to") or "").strip(), set()).add((hop.findtext("from") or "").strip())
    transforms = {(t.findtext("name") or "").strip(): t for t in root.iter("transform")}
    steps = []
    for name, t in sorted(transforms.items()):
        table = (t.findtext("table") or "").strip().strip('"[]`').lower()
        if table.rsplit(".", 1)[-1].strip('"[]`') != "integrations_log_events":
            continue
        seen, todo, sources = set(), [name], []
        while todo:
            for prev in sorted(upstream.get(todo.pop(), ())):
                if prev in seen:
                    continue
                seen.add(prev)
                todo.append(prev)
                el = transforms.get(prev)
                if el is not None and any((e.text or "").strip() in EVENT_FIELDS for e in el.iter()):
                    sources.append(prev)
        steps.append((name, f"{', '.join(EVENT_FIELDS)} from: {', '.join(sorted(sources)) or 'not found upstream'}"))
    return steps


OLD_PATH_RE = re.compile(r"\bsrc[/\\](main|pre|post|commons)[/\\]")


def check_by_hand(plan, path, f):
    """Moved files the tool does not rewrite (.sql, .properties, ...) that still name old variables or paths."""
    try:
        with open(f, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (UnicodeDecodeError, OSError):
        return   # binary or not UTF-8: not checked
    found = []
    if rewrite_vars(text)[1]:
        found.append("template 1.0.x variables")
    if REF_RE.search(text) or OLD_PATH_RE.search(text):
        found.append("1.0.x paths")
    if found:
        plan.report.check_by_hand.append((path, " and ".join(found) + ": check by hand"))


def phase_rewrites(plan):
    reverse = {new: old for old, new in plan.moves.items()}
    current = set(git(plan.dest, "ls-files").split("\n")) - {""}
    removed = set(plan.removals)
    for path in sorted(current):
        old = reverse.get(path, path)
        if old in removed:     # old template files and root workflows: removed in phase 3
            continue
        f = plan.dest / path
        if not (path.endswith((".hwf", ".hpl")) or (path.startswith("metadata/") and path.endswith(".json"))):
            if old != path:
                check_by_hand(plan, path, f)
            continue
        text = read_text(f)
        new = rewrite_refs(plan, text, old)
        new, n = rewrite_vars(new)
        count(plan, "variables", n)
        new, n = re.subn(r"<connection>\s*integrations_db\s*</connection>",
                         "<connection>${serasoft.integrations.db.connection.name}</connection>", new)
        count(plan, "connections", n)
        steps = []
        if path.endswith(".hpl"):
            try:
                steps = event_steps(ET.fromstring(new))
            except ET.ParseError:
                plan.report.unresolved.append((path, "not a valid XML file"))
        for name, sources in steps:
            plan.report.events.append((path, name, sources))
        if (not steps and path.endswith((".hwf", ".hpl")) and not path.startswith("src/template/")
                and "integrations_log_events" in new.lower()):
            plan.report.events.append((path, "-", "integrations_log_events named in SQL or another step: check by hand"))
        if new != text:
            write_text(f, new)
    commit(plan, f"Migration: paths and variables for template {plan.tag}")


def phase_removal(plan):
    present = [f for f in plan.removals if (plan.dest / f).exists()]
    if present:
        git(plan.dest, "rm", "-q", *present)
    commit(plan, "Migration: remove template 1.0.x")


SEED_FILES = ("db/sqlite/data/integrations_db", "db/sqlite/data/integrations_db.config",
              "db/sqlite/data/integrations_db.logs")


def phase_template(plan):
    if git(plan.dest, "status", "--porcelain"):
        fail("unexpected changes before the sync")
    out = run([str(TEMPLATE_REPO / "tools" / "serasoft-sync.sh"), "--tag", plan.tag, "--dest", str(plan.dest)])
    manifest = (plan.dest / "SERASOFT_MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    owned = [line.split(None, 1)[1].lstrip("*") for line in manifest if line.strip()]
    seeds = [p for p in SEED_FILES if (plan.dest / p).exists()]
    # template files hidden by the project .gitignore must be committed all the same
    git(plan.dest, "add", "-f", "--", *owned, *seeds, "SERASOFT_VERSION", "SERASOFT_MANIFEST.sha256")
    run([str(plan.dest / "tools" / "serasoft-verify.sh")], cwd=plan.dest)
    commit(plan, f"Migration: hop-process-template {plan.tag}")
    return out


def env_entry(name, value, description):
    return {"name": name, "value": value, "description": description}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_variables(path):
    return json.loads(read_text(path))["variables"]


def gitignore_entry(rel):
    """An anchored .gitignore pattern matching exactly the file rel (glob characters and trailing spaces escaped)."""
    escaped = re.sub(r"([\\*?\[])", r"\\\1", rel)
    stripped = escaped.rstrip(" ")
    return "/" + stripped + "\\ " * (len(escaped) - len(stripped))


def credential_names(variables):
    return [v["name"] for v in variables if SECRET_RE.search(v["name"]) and (v.get("value") or "")]


IGNORED_CONFIG = {"config", "config/", "/config", "/config/", "config/*", "/config/*", "config/**", "/config/**"}


def phase_config(plan):
    d, p = plan.dest, plan.project
    defaults = {}
    for f in ("config/template-env.json", f"config/template-{plan.db}.json"):
        for v in read_variables(d / f):
            defaults[v["name"]] = v.get("value", "")
    old_defaults = {}   # template 1.0.x defaults: a value equal to one of them was not customised
    for tag in REFERENCE_TAGS:
        for v in json.loads(template_show(tag, "config/project-config.json") or "{}").get("config", {}).get("variables", []):
            old_defaults.setdefault(v["name"], set()).add(v.get("value", "") or "")
    secrets = []

    def add_secret(name):
        if name not in secrets:
            secrets.append(name)

    def classify_into(variables, origin, target, overridden=()):
        """Template names mapped, obsolete and runtime names dropped, credentials only named (secrets).
        A template default is omitted unless it overrides a name of an earlier layer (overridden).
        The names carried over into target are listed in the report."""
        out, mapped, project = [], [], []
        plan.report.variables.append((target, origin, mapped, project))
        for v in variables:
            name, value = v["name"], v.get("value", "") or ""
            kind, new = classify(name)
            if kind == "drop":
                continue
            if kind == "runtime":
                plan.report.runtime_dropped.append((origin, name))
                continue
            if kind == "secret":
                add_secret(new)
                continue
            default = kind == "template" and new not in overridden
            if default and value in old_defaults.get(name, ()):
                continue
            value, _ = rewrite_vars(value)
            if default and defaults.get(new) == value:
                continue
            if PATH_RE.match(value):
                plan.report.paths.append((origin, new, value))
            out.append(env_entry(new, value, f"From {name} ({origin})"))
            if kind == "template":
                mapped.append((name, new))
            else:
                project.append(name)
        return out

    template_pc = template_show(plan.tag, "config/project-config.json")
    if template_pc is None:
        fail(f"config/project-config.json not found in tag {plan.tag}")
    (d / "config").mkdir(parents=True, exist_ok=True)
    write_text(d / "config/project-config.json", template_pc)
    written = ["config/project-config.json", f"config/{p}.json", "config/secrets-example.json"]
    old_vars = (plan.old_project_config or {}).get("config", {}).get("variables", [])
    common = classify_into(old_vars, "config/project-config.json", f"config/{p}.json")
    write_json(d / f"config/{p}.json", {"variables": common})
    common_names = {v["name"] for v in common}
    if credential_names(old_vars):
        plan.report.history_credentials.append(("config/project-config.json", credential_names(old_vars)))
    for r in plan.roots:
        params = {}
        for k, v in r.params.items():
            if SECRET_RE.search(k):
                add_secret(k)    # a credential default: named only, never written
            else:
                params[k] = rewrite_vars(v)[0]
        if params:
            lines = [f"# Defaults of the extra parameters of {r.path} (template 1.0.x);",
                     "# override per execution with p_process_params (README.md, Process parameters)."]
            lines += [f"{k}={v}" for k, v in params.items()]
            write_text(d / f"config/{r.short_name}.properties", "\n".join(lines) + "\n")
            plan.report.variables.append((f"config/{r.short_name}.properties", r.path, [], list(params)))
            written.append(f"config/{r.short_name}.properties")
    runtime = {
        "serasoft.execution.log.filename": f"/tmp/{p}/logs/execution_log_${{p_base_process_name}}_"
                                           "${serasoft.project.main.workflow}_${v_process_run_timestamp}.log",
        "serasoft.execution.file.name": f"/tmp/{p}/temp/execution_file_${{p_base_process_name}}_"
                                        "${serasoft.project.main.workflow}_${v_process_run_timestamp}.csv",
    }
    tracked_files = set(git(d, "ls-files").split("\n"))
    for env, path in sorted(plan.envs.items()):
        old_env_vars = read_variables(path)
        variables = [v for v in classify_into(old_env_vars, f"{env} environment", f"config/{p}-{env}.json",
                                              common_names)
                     if v["name"] not in runtime]
        variables += [env_entry(k, v, "Writable path outside the read-only project folder") for k, v in runtime.items()]
        # Remove the old file first: it may sit at the path of the generated one.
        rel = Path(os.path.relpath(path, d)).as_posix()
        if not rel.startswith("..") and rel in tracked_files:
            git(d, "rm", "-q", "--", rel)
            plan.report.old_env_files_removed.append(rel)
            if credential_names(old_env_vars):
                plan.report.history_credentials.append((rel, credential_names(old_env_vars)))
        write_json(d / f"config/{p}-{env}.json", {"variables": variables})
        written += [f"config/{p}-{env}.json", f"config/env/{env}.list"]
        (d / "config/env").mkdir(parents=True, exist_ok=True)
        write_text(d / f"config/env/{env}.list",
            f"# Hop environment files for {env}, in load order: a later file overrides an earlier one.\n"
            f"# Read by the Serasoft Airflow platform; cron: tools/serasoft-register-env.sh --env {env}\n"
            f"config/template-env.json\nconfig/template-{plan.db}.json\nconfig/{p}.json\nconfig/{p}-{env}.json\n"
            f"/run/secrets/{p}_{env}\n")
    write_json(d / "config/secrets-example.json",
               {"variables": [env_entry(n, "", f"Credential: set it in the Docker secret {p}_<env>") for n in secrets]})
    plan.report.secrets = secrets
    gi = d / ".gitignore"
    lines = read_text(gi).splitlines() if gi.exists() else []
    lines = [line for line in lines if line.strip() not in IGNORED_CONFIG]
    lines += ["", "# Template 3.x: config/ is distributed and must be committed",
              "!config/", "!config/**", "config/*-local.json", "config/*secret*.json", "!config/secrets-example.json"]
    write_text(gi, "\n".join(lines) + "\n")
    # Local files under config/ that the old .gitignore hid (often with credentials) must never be
    # committed: they stay on disk, ignored by name.
    local = sorted(set(git(d, "ls-files", "-z", "--others", "--exclude-standard", "--", "config").split("\0"))
                   - set(written) - {""})
    if local:
        lines += ["", "# Local files of the 1.0.x setup, left out of the repository by the migration",
                  *map(gitignore_entry, local)]
        write_text(gi, "\n".join(lines) + "\n")
        print(f"WARNING: local files under config/ not committed (ignored by name in .gitignore): "
              f"{' '.join(local)}", file=sys.stderr)
        plan.report.local_config_ignored = local
    git(d, "add", "-f", "--", ".gitignore", *written)
    git(d, "commit", "-q", "-m", "Migration: configuration for the Serasoft Airflow platform")


def sql(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


TEMPLATE_EVENT_ROWS = {"SYS001", "SYSGE001"}   # seeded by db/liquibase/master.xml


def write_seed(plan):
    """db/seed/<project>_config.sql: plain INSERT ... SELECT ... WHERE NOT EXISTS, valid on PostgreSQL,
    SQL Server and SQLite (config attached as a schema, like the integrations_db_sqlite connection)."""
    p = plan.project
    lines = [f"-- Template configuration rows for {p}, generated by tools/serasoft-migrate-1x.py from the",
             "-- 1.0.x export. Run after `liquibase update` with db/liquibase/master.xml. Idempotent."]
    if plan.db == "sqlite":
        lines.append("-- SQLite: run on db/sqlite/data/integrations_db with integrations_db.config attached AS config.")
    lines.append("")
    for r in plan.roots:
        row = plan.processes[r.short_name]
        lines.append("INSERT INTO config.integrations_processes (id, short_name, description, project, is_active, is_running)\n"
                     f"SELECT {sql(r.short_name)}, {sql(r.short_name)}, {sql(row.get('description') or '')}, {sql(p)}, "
                     f"{sql((row.get('is_active') or 'Y')[:1])}, 'N'\n"
                     f"WHERE NOT EXISTS (SELECT 1 FROM config.integrations_processes WHERE id = {sql(r.short_name)});\n")
    for c in plan.categories:
        if c["id"] in TEMPLATE_EVENT_ROWS:
            continue
        lines.append(f"INSERT INTO config.events_categories (id, type, name)\nSELECT {sql(c['id'])}, "
                     f"{sql((c.get('event_type') or 'E')[:1])}, {sql(c['name'])}\n"
                     f"WHERE NOT EXISTS (SELECT 1 FROM config.events_categories WHERE id = {sql(c['id'])});\n")
    for s in plan.subcategories:
        if s["id"] in TEMPLATE_EVENT_ROWS:
            continue
        lines.append(f"INSERT INTO config.events_subcategories (id, event_category_id, name)\nSELECT {sql(s['id'])}, "
                     f"{sql(s['event_category_id'])}, {sql(s['name'])}\n"
                     f"WHERE NOT EXISTS (SELECT 1 FROM config.events_subcategories WHERE id = {sql(s['id'])});\n")
    (plan.dest / "db/seed").mkdir(parents=True, exist_ok=True)
    write_text(plan.dest / f"db/seed/{p}_config.sql", "\n".join(lines).rstrip("\n") + "\n")


def md_item(item):
    """A report line: a string, or a tuple whose list members are joined."""
    if isinstance(item, str):
        return f"- `{item}`"
    return "- " + " · ".join(", ".join(f"`{x}`" for x in i) if isinstance(i, (list, tuple)) else f"`{i}`"
                             for i in item)


def md_section(title, items):
    return [f"## {title}", ""] + ([md_item(i) for i in items] if items else ["None."]) + [""]


def write_report(plan, exit_code):
    p, rep = plan.project, plan.report
    md = [f"# Migration report: {p} → hop-process-template {plan.tag}", "",
          f"Generated by `tools/serasoft-migrate-1x.py`. Exit code: {exit_code}"
          f" ({'manual work below' if exit_code == 2 else 'no manual work'}).", "",
          "## Inputs", "", f"- Template tag: `{plan.tag}`", f"- Database: `{plan.db}`",
          f"- Process export: `{Path(plan.processes_csv).name}`"]
    md += [f"- Environment `{name}`: `{Path(path).name}`" for name, path in sorted(plan.envs.items())] + [""]
    md += md_section("Process map (root workflow · process · 1.0.x entry · new entry)",
                     [(r.path, r.short_name, r.target, f"src/project/main/{r.short_name}/start.hwf") for r in plan.roots])
    md += md_section("Processes of the export without a root workflow (not seeded)", rep.unknown_processes)
    md += md_section("Moved files", rep.moved)
    md += ["## Rewrites", ""] + ([f"- {k}: {v}" for k, v in sorted(rep.rewrites.items())] or ["None."]) + [""]
    md += md_section("Possibly customised template 1.0.x files (compare with tag 1.0.1)", rep.customised)
    md += md_section("Unresolved file references", rep.unresolved)
    md += md_section("References to removed template files without a 3.x equivalent", rep.removed_refs)
    md += md_section("Steps writing template events directly: replace with EventsTraceTransform "
                     "(categories and subcategories are in the seed)", rep.events)
    md += md_section(f"Variables with filesystem paths: use a writable path or /tmp/{p}", rep.paths)
    md += ["## Variables carried over (names only: file · origin · template names mapped · project names)", ""]
    md += [f"- `{target}` · {origin} · mapped: "
           + (", ".join(f"`{old}` → `{new}`" for old, new in mapped) or "none") + " · project: "
           + (", ".join(f"`{n}`" for n in project) or "none")
           for target, origin, mapped, project in rep.variables] or ["None."]
    md += [""]
    md += md_section("Moved files not rewritten that still name 1.0.x variables or paths", rep.check_by_hand)
    md += md_section("Runtime variables not carried over", rep.runtime_dropped)
    md += md_section("Extra root-workflow parameters without default (not carried over)", rep.params_without_default)
    md += md_section(f"Credentials (config/secrets-example.json, Docker secret {p}_<env>)", rep.secrets)
    md += md_section("Old environment files with credentials removed from the repository", rep.old_env_files_removed)
    md += md_section("Credentials still in the Git history (file · variable names): rotate them",
                     rep.history_credentials)
    md += md_section("Local files under config/ kept out of Git (ignored by name in .gitignore)",
                     rep.local_config_ignored)
    md += md_section("Deployment files probably not needed with the platform", rep.deployment)
    md += ["## Operator checklist", "",
           f"- [ ] Docker secrets `{p}_<env>` with the variables of `config/secrets-example.json`",
           "- [ ] Integrations database: `liquibase update` (db/liquibase/master.xml), then "
           f"`db/seed/{p}_config.sql`",
           "- [ ] DAG and `config/hop_projects.yaml` entry, or `tools/serasoft-register-env.sh` for cron",
           "- [ ] Rotate the credentials found in the old environment files and in the Git history",
           "- [ ] Cut-over: stop the old deployment before the first run of the new one", ""]
    (plan.dest / "docs").mkdir(exist_ok=True)
    write_text(plan.dest / "docs/migration-report.md", "\n".join(md).rstrip("\n") + "\n")


def phase_seed_report(plan):
    exit_code = 2 if plan.report.manual() else 0
    write_seed(plan)
    write_report(plan, exit_code)
    # The project's own .gitignore may hide docs/ or db/: force-add what this phase generates.
    git(plan.dest, "add", "-f", "--", f"db/seed/{plan.project}_config.sql", "docs/migration-report.md")
    commit(plan, "Migration: DB seed and report")
    return exit_code


PHASES = [phase_structure, phase_rewrites, phase_removal, phase_template, phase_config, phase_seed_report]
PHASE_TITLES = ["project structure", "paths and variables", "removal of template 1.0.x", "template sync",
                "platform configuration", "DB seed and report"]


def parse_args(argv):
    p = argparse.ArgumentParser(description="Migrate a template 1.0.x project (see README.md).")
    p.add_argument("--dest", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--processes", required=True)
    p.add_argument("--env", action="append", required=True, metavar="NAME=FILE")
    p.add_argument("--project")
    p.add_argument("--db", default="postgresql", choices=["postgresql", "mssql", "sqlite"])
    p.add_argument("--stop-after", type=int, default=6, choices=range(7), metavar="PHASE",
                   help="stop after this phase (0 = analysis only, 6 = complete; default 6)")
    try:
        return p.parse_args(argv)
    except SystemExit as e:
        sys.exit(64 if e.code else 0)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    plan = analyse(args)
    print(f"analysis OK: {len(plan.roots)} process(es), {len(plan.moves)} move(s), {len(plan.removals)} removal(s)")
    global CURRENT_PHASE
    exit_code = 0
    for number, (phase, title) in enumerate(zip(PHASES, PHASE_TITLES), 1):
        if number > args.stop_after:
            break
        print(f"phase {number}: {title}", flush=True)
        CURRENT_PHASE = f"phase {number} ({title}): "
        exit_code = phase(plan) or 0
        CURRENT_PHASE = ""
        print(f"phase {number} done")
    if args.stop_after == len(PHASES):
        print(f"OK serasoft-migrate-1x project={plan.project} processes={len(plan.roots)} exit={exit_code}")
        print(f"report: {plan.dest / 'docs/migration-report.md'}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
