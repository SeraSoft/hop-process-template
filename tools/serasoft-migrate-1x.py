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
    local_config_ignored: list = field(default_factory=list)

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
        try:
            root = ET.parse(dest / path).getroot()
        except ET.ParseError as e:
            fail(f"{path}: invalid XML ({e})")
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
        if r.short_name == "template":
            fail(f"{r.path} is the unchanged template sample (p_base_process_name=template): "
                 "remove it or set its process name")
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
        old_pc = json.loads((dest / "config/project-config.json").read_text())
    for f in sorted(files):
        if os.path.basename(f) in DEPLOYMENT_FILES or f.endswith("hop-config.json"):
            report.deployment.append(f)
    project = args.project or dest.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", project):
        fail(f"invalid project name {project}")
    return Plan(dest, args.tag, project, args.db, files, roots, processes, categories, subcategories,
                moves, removals, equivalents, old_pc, envs, report)


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
        count(plan, "paths")
        return "${PROJECT_HOME}/" + new
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
        if (t.findtext("table") or "").strip() != "integrations_log_events":
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


def phase_rewrites(plan):
    reverse = {new: old for old, new in plan.moves.items()}
    current = set(git(plan.dest, "ls-files").split("\n")) - {""}
    removed = set(plan.removals)
    for path in sorted(current):
        old = reverse.get(path, path)
        if old in removed:     # old template files and root workflows: removed in phase 3
            continue
        if not (path.endswith((".hwf", ".hpl")) or (path.startswith("metadata/") and path.endswith(".json"))):
            continue
        f = plan.dest / path
        text = f.read_text()
        new = rewrite_refs(plan, text, old)
        new, n = rewrite_vars(new)
        count(plan, "variables", n)
        new, n = re.subn(r"<connection>\s*integrations_db\s*</connection>",
                         "<connection>${serasoft.integrations.db.connection.name}</connection>", new)
        count(plan, "connections", n)
        if path.endswith(".hpl"):
            try:
                for name, sources in event_steps(ET.fromstring(new)):
                    plan.report.events.append((path, name, sources))
            except ET.ParseError:
                plan.report.unresolved.append((path, "not a valid XML file"))
        if new != text:
            f.write_text(new)
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
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_variables(path):
    return json.loads(path.read_text(encoding="utf-8"))["variables"]


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

    def classify_into(variables, origin):
        """Template names mapped, obsolete and runtime names dropped, credentials only named (secrets)."""
        out = []
        for v in variables:
            name, value = v["name"], v.get("value", "") or ""
            kind, new = classify(name)
            if kind == "drop":
                continue
            if kind == "runtime":
                plan.report.runtime_dropped.append((origin, name))
                continue
            if kind == "secret":
                if new not in secrets:
                    secrets.append(new)
                continue
            if kind == "template" and value in old_defaults.get(name, ()):
                continue
            value, _ = rewrite_vars(value)
            if kind == "template" and defaults.get(new) == value:
                continue
            if PATH_RE.match(value):
                plan.report.paths.append((origin, new, value))
            out.append(env_entry(new, value, f"From {name} ({origin})"))
        return out

    template_pc = template_show(plan.tag, "config/project-config.json")
    if template_pc is None:
        fail(f"config/project-config.json not found in tag {plan.tag}")
    (d / "config").mkdir(parents=True, exist_ok=True)
    (d / "config/project-config.json").write_text(template_pc, encoding="utf-8")
    written = ["config/project-config.json", f"config/{p}.json", "config/secrets-example.json"]
    old_vars = (plan.old_project_config or {}).get("config", {}).get("variables", [])
    write_json(d / f"config/{p}.json", {"variables": classify_into(old_vars, "config/project-config.json")})
    for r in plan.roots:
        if r.params:
            lines = [f"# Defaults of the extra parameters of {r.path} (template 1.0.x);",
                     "# override per execution with p_process_params (README.md, Process parameters)."]
            lines += [f"{k}={v}" for k, v in r.params.items()]
            (d / f"config/{r.short_name}.properties").write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(f"config/{r.short_name}.properties")
    runtime = {
        "serasoft.execution.log.filename": f"/tmp/{p}/logs/execution_log_${{p_base_process_name}}_"
                                           "${serasoft.project.main.workflow}_${v_process_run_timestamp}.log",
        "serasoft.execution.file.name": f"/tmp/{p}/temp/execution_file_${{p_base_process_name}}_"
                                        "${serasoft.project.main.workflow}_${v_process_run_timestamp}.csv",
    }
    tracked_files = set(git(d, "ls-files").split("\n"))
    for env, path in sorted(plan.envs.items()):
        variables = [v for v in classify_into(read_variables(path), f"{env} environment")
                     if v["name"] not in runtime]
        variables += [env_entry(k, v, "Writable path outside the read-only project folder") for k, v in runtime.items()]
        write_json(d / f"config/{p}-{env}.json", {"variables": variables})
        written += [f"config/{p}-{env}.json", f"config/env/{env}.list"]
        (d / "config/env").mkdir(parents=True, exist_ok=True)
        (d / f"config/env/{env}.list").write_text(
            f"# Hop environment files for {env}, in load order: a later file overrides an earlier one.\n"
            f"# Read by the Serasoft Airflow platform; cron: tools/serasoft-register-env.sh --env {env}\n"
            f"config/template-env.json\nconfig/template-{plan.db}.json\nconfig/{p}.json\nconfig/{p}-{env}.json\n"
            f"/run/secrets/{p}_{env}\n", encoding="utf-8")
        rel = Path(os.path.relpath(path, d)).as_posix()
        if not rel.startswith("..") and rel in tracked_files:
            git(d, "rm", "-q", "--", rel)
            plan.report.old_env_files_removed.append(rel)
    write_json(d / "config/secrets-example.json",
               {"variables": [env_entry(n, "", f"Credential: set it in the Docker secret {p}_<env>") for n in secrets]})
    plan.report.secrets = secrets
    gi = d / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    lines = [line for line in lines if line.strip() not in IGNORED_CONFIG]
    lines += ["", "# Template 3.x: config/ is distributed and must be committed",
              "!config/", "!config/**", "config/*-local.json", "config/*secret*.json", "!config/secrets-example.json"]
    gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Local files under config/ that the old .gitignore hid (often with credentials) must never be
    # committed: they stay on disk, ignored by name.
    local = sorted(set(git(d, "ls-files", "--others", "--exclude-standard", "--", "config").split("\n"))
                   - set(written) - {""})
    if local:
        lines += ["", "# Local files of the 1.0.x setup, left out of the repository by the migration", *local]
        gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"WARNING: local files under config/ not committed (ignored by name in .gitignore): "
              f"{' '.join(local)}", file=sys.stderr)
        plan.report.local_config_ignored = local
    git(d, "add", "-f", "--", ".gitignore", *written)
    git(d, "commit", "-q", "-m", "Migration: configuration for the Serasoft Airflow platform")


PHASES = [phase_structure, phase_rewrites, phase_removal, phase_template, phase_config]   # phase 6 added by Task 4


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
    for number, phase in enumerate(PHASES, 1):
        if number > args.stop_after:
            break
        phase(plan)
        print(f"phase {number} done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
