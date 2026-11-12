# Hop projects in a subfolder: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a Hop project kept in a subfolder of its Git repository can be created/updated with the template sync and distributed/run by the Serasoft Airflow platform.

**Architecture:** template side, `tools/serasoft-sync.sh --dest` accepts a folder inside a work tree. Platform side (SeraSoft/airflow-dags), an optional `path` per project in `config/hop_projects.yaml` travels as a fourth tab-separated field to the distribution script, which copies only that subfolder into the version folder `<project>@<commit12>-<path with / → ->`; execution is unchanged.

**Tech Stack:** Bash 4+, Python 3, pytest; airflow-dags tests run in `apache/airflow:3.3.2`.

Spec: `docs/superpowers/specs/2026-11-12-project-subfolder-design.md`.

## Global Constraints

- English in code, comments, docs, commits, PRs. No real customer or project names in either repository (use `sales`, `dwh`, `bi`, `hop-template-sub`).
- One task = one commit. Do not push; the controller opens the PRs (one per repository).
- No new dependencies.
- Projects without `path` must behave exactly as today: same task line (three fields), same version folder name, same output lines.
- Version folder with path: `<project>@<commit12>-<path with / replaced by ->` (e.g. `sales@8b11d0aa94c2-etl`).
- `path` rule (Python and Bash): one or more segments separated by `/`, each segment `[A-Za-z0-9][A-Za-z0-9_.-]*`; no `..` anywhere; no leading/trailing `/`; no empty segment.
- Template sync: the uncommitted-changes check stays on the whole work tree.
- Git identity: in `/srv/repositories/airflow-dags` set `git config user.name "Enrico Maria Carmona"` and `git config user.email enricomaria.carmona@serasoft.it` before the first commit (the local value is `test`).

## Issues

| Task | Repository | Issue |
|---|---|---|
| 1 | hop-process-template | `#79` |
| 2 | airflow-dags | `SeraSoft/airflow-dags#61` |
| 3 | airflow-dags | `SeraSoft/airflow-dags#62` |
| 4 | airflow-dags | `SeraSoft/airflow-dags#63` |

## Branches and test commands

- hop-process-template: branch `feat/project-subfolder` (exists, holds the spec). Tests: `python3 -m pytest tests/tools -q` (123 pass before this work).
- airflow-dags (`/srv/repositories/airflow-dags`): branch `feat/hop-project-path` from `main`. Tests (499 pass, 2 skipped before this work):

```bash
cd /srv/repositories/airflow-dags
docker run --rm -e PYTHONPATH=/src -v "$PWD":/src:ro -w /src --entrypoint bash apache/airflow:3.3.2 \
  -c 'pip install -q pytest==9.1.1 apache-airflow-providers-atlassian-jira >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider tests'
```

Single files: replace the final `tests` with the file paths.

---

### Task 1: serasoft-sync.sh accepts a subfolder (hop-process-template, #79)

**Files:**
- Modify: `tools/serasoft-sync.sh:8,17,47-52`
- Modify: `tests/tools/test_serasoft_sync.py`
- Modify: `README.md` (sections "Template updates" and "Running with cron (`hop_runner.sh`)")

- [ ] **Step 1: Write the failing tests** (append to `tests/tools/test_serasoft_sync.py`; also change the message asserted in `test_refuses_non_git_destination` to `"not inside a Git work tree"`)

```python
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
    return [line[3:] for line in status.splitlines() if not line[3:].startswith("etl/")]


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
```

- [ ] **Step 2: Run them, expect failures**

Run: `python3 -m pytest tests/tools/test_serasoft_sync.py -q`
Expected: the new subfolder tests FAIL with `not the root of a Git work tree`; `test_refuses_non_git_destination` FAILS on the new message.

- [ ] **Step 3: Implement** — in `tools/serasoft-sync.sh` replace lines 47-52 with:

```bash
[[ -d "$dest" ]] || die "$dest is not a directory"
dest="$(cd "$dest" && pwd -P)"
# The project is --dest: the root of a work tree or a folder inside one.
top="$(git -C "$dest" rev-parse --show-toplevel 2>/dev/null)" \
  || die "$dest is not inside a Git work tree"
template_root="$(cd "$upstream" && pwd -P)"
[[ "$dest" != "$template_root" && "$dest" != "$template_root"/* ]] \
  || die "--dest is the template itself or a folder inside it"
# Whole work tree: the sync diff must be reviewable on its own.
[[ -z "$(git -C "$top" status --porcelain)" ]] || die "$top has uncommitted changes"
```

and in the header comment (line 8) and in `usage` (line 17) replace `--dest <project repository>` with `--dest <project folder: a Git repository or a folder inside one>`.

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/tools -q`
Expected: all pass (123 + 5 new = 128).

- [ ] **Step 5: README** — in "Template updates", insert before `### Checking a project`:

````markdown
### Projects in a subfolder

A Hop project may live in a subfolder of its repository (e.g. `etl/`, next to other content). Give that folder as `--dest`: the template files, `SERASOFT_VERSION` and `SERASOFT_MANIFEST.sha256` go there, nothing outside it is touched. The sync still refuses a work tree with uncommitted changes anywhere, so that its diff can be reviewed on its own:

```
tools/serasoft-sync.sh --tag 3.4.0 --dest ../myrepo/etl
```

Run the verify from the subfolder (in CI: `cd etl && tools/serasoft-verify.sh`). On the Serasoft Airflow platform, set `path: etl` for the project in `config/hop_projects.yaml` (SeraSoft/airflow-dags): the distribution copies only that subfolder.
````

and in "Running with cron (`hop_runner.sh`)" insert before the bullet that starts with ``- Each `/run/secrets/<name>` line``:

```markdown
- A project in a subfolder of its repository (see "Projects in a subfolder") has not been tried with `hop_runner.sh`.
```

- [ ] **Step 6: Commit**

```bash
git add tools/serasoft-sync.sh tests/tools/test_serasoft_sync.py README.md
git commit -m "serasoft-sync.sh: projects in a subfolder of a Git repository"
```

---

### Task 2: `path` in hop_projects.yaml (airflow-dags, #61)

**Files:**
- Modify: `serasoft_airflow/distribution.py` (`_KEYS`, new `_PATH`, `load_projects`, `deploy_list`, `_prepare`)
- Modify: `tests/test_distribution_config.py`, `tests/test_distribution_dag.py`

**Interfaces:**
- Produces: `deploy_list(projects, env, only=None) -> list[tuple[str, str, str, str]]` = `(name, repo, ref, path)`, `path == ""` when not set. `SERASOFT_HOP_DEPLOY_PROJECTS` line: `name\trepo\tref` without path, `name\trepo\tref\tpath` with path.

- [ ] **Step 1: Create the branch and set the identity**

```bash
cd /srv/repositories/airflow-dags
git checkout -b feat/hop-project-path
git config user.name "Enrico Maria Carmona"
git config user.email enricomaria.carmona@serasoft.it
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_distribution_config.py` change `test_load_and_pick_the_environment_ref` to expect 4-tuples (`("dwh", "https://gitlab.example.lan/etl/dwh.git", "develop", "")` etc.) and append:

```python
WITH_PATH = """
sales:
  repo: https://gitlab.example.lan/etl/mono.git
  path: etl
  ref: {dev: develop}
sales-hop:
  repo: https://gitlab.example.lan/etl/mono.git
  path: tools/hop.v2
  ref: {dev: develop}
"""


def test_path_carried_by_deploy_list(tmp_path):
    projects = d.load_projects(_write(tmp_path, WITH_PATH))
    assert d.deploy_list(projects, "dev") == [
        ("sales", "https://gitlab.example.lan/etl/mono.git", "develop", "etl"),
        ("sales-hop", "https://gitlab.example.lan/etl/mono.git", "develop", "tools/hop.v2"),
    ]


@pytest.mark.parametrize("path", ["'..'", "a/../b", "/etl", "etl/", "a//b", ".x", "a/.b", "'a b'", "''", "1", "[etl]"])
def test_invalid_path(tmp_path, path):
    text = f"dwh:\n  repo: https://x/y.git\n  path: {path}\n  ref: {{dev: main}}\n"
    with pytest.raises(ValueError, match="path"):
        d.load_projects(_write(tmp_path, text))
```

In `tests/test_distribution_dag.py` append:

```python
PATH_YAML = YAML + """
sales:
  repo: https://gitlab.example.lan/etl/mono.git
  path: etl
  ref: {ci: main, dev: develop}
"""
MONO = "https://gitlab.example.lan/etl/mono.git"


@pytest.mark.parametrize("backend", BACKENDS)
def test_path_is_the_fourth_field(monkeypatch, tmp_path, backend):
    _, t = _task(_lib(monkeypatch, backend), _yaml(tmp_path, PATH_YAML))
    _prepare(t)
    assert _env(t)["SERASOFT_HOP_DEPLOY_PROJECTS"] == f"bi\t{BI}\tmain\ndwh\t{DWH}\tdevelop\nsales\t{MONO}\tmain\tetl"


@pytest.mark.parametrize("backend", BACKENDS)
def test_branch_in_dev_keeps_the_path(monkeypatch, tmp_path, backend):
    _, t = _task(_lib(monkeypatch, backend, SERASOFT_ENV="dev"), _yaml(tmp_path, PATH_YAML))
    _prepare(t, progetto="sales", ref="feature/x")
    assert _env(t)["SERASOFT_HOP_DEPLOY_PROJECTS"] == f"sales\t{MONO}\tfeature/x\tetl"
```

- [ ] **Step 3: Run them, expect failures** (test command with `tests/test_distribution_config.py tests/test_distribution_dag.py`): `allowed keys`, 3-tuples.

- [ ] **Step 4: Implement** in `serasoft_airflow/distribution.py`:

```python
_KEYS = {"repo", "ref", "path"}
# project folder inside the repository: segments with the name rule, separated by '/'
_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*")
```

in `load_projects`, after the `repo` checks:

```python
        sub = spec.get("path")
        if sub is not None and (not isinstance(sub, str) or not _PATH.fullmatch(sub) or ".." in sub):
            raise ValueError(f"{path}: {name}: 'path' must be a folder of the repository "
                             f"(segments of letters, digits, '_', '.', '-' separated by '/'): {sub!r}")
```

`deploy_list` appends `(name, projects[name]["repo"], ref, projects[name].get("path") or "")` and its docstring becomes `"""(name, repo, ref, path) of the projects with a ref for the environment, in name order; path '' when not set."""`. Update the module docstring line `project -> https repository and ref per environment` to `project -> https repository, optional path of the project folder and ref per environment`.

In `_prepare`:

```python
        if ref:
            lines = [(progetto, projects[progetto]["repo"], ref, projects[progetto].get("path") or "")]
        else:
            lines = deploy_list(projects, environment, only=progetto or None)
        env = task.job_env if hasattr(task, "job_env") else task.environment
        # fourth field only with a path: lines without path stay as before
        env[ENV_PROJECTS] = "\n".join("\t".join(line if line[3] else line[:3]) for line in lines)
        env[ENV_MODE] = "ref" if ref else "current"
        task.log.info("Progetti da distribuire (%s): %s", env[ENV_MODE],
                      ", ".join(f"{n}@{r}" for n, _, r, _ in lines) or "none")
```

- [ ] **Step 5: Run the whole suite** (test command). Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add serasoft_airflow/distribution.py tests/test_distribution_config.py tests/test_distribution_dag.py
git commit -m "feat: optional path of the Hop project in hop_projects.yaml"
```

---

### Task 3: distribution script copies only the subfolder (airflow-dags, #62)

**Files:**
- Modify: `serasoft_airflow/hop.py` (`check_line`, `deploy_one`, main loop of `_DISTRIBUTION`)
- Modify: `tests/test_distribution_script.py`

**Interfaces:**
- Consumes: task lines from Task 2 (`name\trepo\tref[\tpath]`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_distribution_script.py`)

```python
def _mono(tmp_path: Path, name="mono") -> tuple[Path, Path]:
    """Repository with the project in etl/ (and a copy in etl2/), plus a file outside."""
    work, bare = tmp_path / f"{name}-work", tmp_path / f"{name}.git"
    for sub in ("etl", "etl2"):
        (work / sub / "config/env").mkdir(parents=True)
        (work / sub / "main.hwf").write_text(f"{sub} v1")
        (work / sub / "config/env/lab.list").write_text("config/template-env.json\n")
    (work / "reporting").mkdir()
    (work / "reporting/report.sql").write_text("select 1")
    _git(work, "init", "-q", "-b", "main")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "v1")
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    return work, bare


def test_path_distributes_only_the_subfolder(tmp_path):
    work, bare = _mono(tmp_path)
    dest = tmp_path / "share"
    dest.mkdir()
    head = _git(work, "rev-parse", "HEAD")[:12]
    r = _deploy(dest, [("sales", f"file://{bare}", "main", "etl")])
    assert r.returncode == 0, r.stdout + r.stderr
    d = f"sales@{head}-etl"
    assert (dest / "sales.current").read_text().strip() == d
    assert (dest / d / "main.hwf").read_text() == "etl v1"
    assert (dest / d / "config/env/lab.list").is_file()
    assert not (dest / d / "reporting").exists() and not (dest / d / "etl").exists()
    assert f"sales updated (none) -> {head}-etl" in r.stdout
    r = _deploy(dest, [("sales", f"file://{bare}", "main", "etl")])
    assert f"sales unchanged {head}-etl" in r.stdout


def test_path_change_on_the_same_commit_is_a_new_version(tmp_path):
    work, bare = _mono(tmp_path)
    dest = tmp_path / "share"
    dest.mkdir()
    head = _git(work, "rev-parse", "HEAD")[:12]
    _deploy(dest, [("sales", f"file://{bare}", "main", "etl")])
    r = _deploy(dest, [("sales", f"file://{bare}", "main", "etl2")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dest / "sales.current").read_text().strip() == f"sales@{head}-etl2"
    assert (dest / f"sales@{head}-etl2/main.hwf").read_text() == "etl2 v1"
    assert (dest / f"sales@{head}-etl/main.hwf").read_text() == "etl v1"


def test_path_missing_in_the_commit(tmp_path):
    work, bare = _mono(tmp_path)
    _, bare_bi = _repo(tmp_path, "bi")
    dest = tmp_path / "share"
    dest.mkdir()
    r = _deploy(dest, [("sales", f"file://{bare}", "main", "nope"), ("bi", f"file://{bare_bi}", "main")])
    assert r.returncode == 1
    assert "path 'nope' not found" in r.stdout and "bi updated" in r.stdout
    assert not (dest / "sales.current").exists()
    assert not [p for p in dest.iterdir() if p.name.startswith("sales")]


def test_path_symlink_outside_the_repository(tmp_path):
    work, bare = _mono(tmp_path)
    (work / "out").symlink_to("/etc")
    _git(work, "add", "out")
    _git(work, "commit", "-q", "-m", "link")
    _git(work, "push", "-q", "origin", "HEAD:main")
    dest = tmp_path / "share"
    dest.mkdir()
    r = _deploy(dest, [("sales", f"file://{bare}", "main", "out")])
    assert r.returncode == 1
    assert "path 'out' not found" in r.stdout
    assert not [p for p in dest.iterdir() if p.name.startswith("sales")]


def test_two_projects_from_the_same_repository(tmp_path):
    work, bare = _mono(tmp_path)
    dest = tmp_path / "share"
    dest.mkdir()
    head = _git(work, "rev-parse", "HEAD")[:12]
    r = _deploy(dest, [("sales", f"file://{bare}", "main", "etl"), ("sales2", f"file://{bare}", "main", "etl2")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dest / "sales.current").read_text().strip() == f"sales@{head}-etl"
    assert (dest / "sales2.current").read_text().strip() == f"sales2@{head}-etl2"


def test_ref_mode_with_path(tmp_path):
    work, bare = _mono(tmp_path)
    _git(work, "checkout", "-q", "-b", "feature/x")
    (work / "etl/main.hwf").write_text("etl feature")
    _git(work, "commit", "-q", "-am", "feature")
    _git(work, "push", "-q", "origin", "HEAD:feature/x")
    feat = _git(work, "rev-parse", "HEAD")[:12]
    dest = tmp_path / "share"
    dest.mkdir()
    r = _deploy(dest, [("sales", f"file://{bare}", "feature/x", "etl")], mode="ref")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dest / "sales@feature-x.ref").read_text().strip() == f"sales@{feat}-etl"
    assert (dest / f"sales@{feat}-etl/main.hwf").read_text() == "etl feature"


@pytest.mark.parametrize("sub", ["../x", "/etl", "etl/", "a//b", ".x", "a/.b", "a..b", "a b"])
def test_invalid_path_line(tmp_path, sub):
    _, bare = _mono(tmp_path)
    _, bare_bi = _repo(tmp_path, "bi")
    dest = tmp_path / "share"
    dest.mkdir()
    r = _deploy(dest, [("sales", f"file://{bare}", "main", sub), ("bi", f"file://{bare_bi}", "main")])
    assert r.returncode == 1
    assert "invalid path" in r.stdout and "bi updated" in r.stdout
    assert not [p for p in dest.iterdir() if p.name.startswith("sales")]
```

(`test_first_distribution_and_unchanged` and the other existing tests are the no-path regression.)

- [ ] **Step 2: Run them, expect failures** (test command with `tests/test_distribution_script.py`): the version folder is `sales@<commit>` with the whole repository; no `invalid path`.

- [ ] **Step 3: Implement** in `serasoft_airflow/hop.py` (`_DISTRIBUTION`):

`check_line`:

```bash
check_line() {  # $1 name, $2 repo, $3 ref, $4 path (empty = whole repository)
  case "$1" in [!A-Za-z0-9]*|*..*|*[!A-Za-z0-9_.-]*) echo "invalid name: '$1'"; return 1 ;; esac
  case "$3" in ''|[!A-Za-z0-9]*|*..*|*[!A-Za-z0-9_./-]*) echo "invalid ref: '$3'"; return 1 ;; esac
  case "$2" in ''|-*|*[[:space:]]*) echo "invalid repository: '$2'"; return 1 ;; esac
  case "$4" in
    '') ;;
    [!A-Za-z0-9]*|*/|*/[!A-Za-z0-9]*|*..*|*[!A-Za-z0-9_./-]*) echo "invalid path: '$4'"; return 1 ;;
  esac
}
```

`deploy_one`: signature comment `# $1 name, $2 repo, $3 ref, $4 path (validated); run in a subshell`, add `sub=${4-}` to the `local` line (`local name=$1 repo=$2 ref=$3 sub=${4-} refs commit short dir pointer cur old src real root`), then replace `dir="$name@$short"` with:

```bash
  dir="$name@$short"
  # project in a subfolder: the path is part of the version (a path change is a new version)
  if [ -n "$sub" ]; then dir="$dir-${sub//\//-}"; fi
  if [ "$cur" = "$dir" ] && [ -d "$dest/$dir" ]; then echo "$name unchanged ${dir#"$name@"}"; return 0; fi
```

(the existing `if [ "$cur" = "$dir" ] ...` line is replaced by the last one above). After `rm -rf -- "$work/src/.git"` add:

```bash
    src="$work/src"
    if [ -n "$sub" ]; then
      # the subfolder must exist in the commit and stay inside the repository (no symlink out)
      root=$(cd -- "$work/src" && pwd -P) && real=$(cd -- "$work/src/$sub" 2>/dev/null && pwd -P) \
        && case "$real/" in "$root"/?*) true ;; *) false ;; esac \
        || { echo "path '$sub' not found in $repo at $short"; return 1; }
      src="$real"
    fi
```

and change the copy from `cp -R -- "$work/src/." "$tmp/"` to `cp -R -- "$src/." "$tmp/"`. Change the final line `old=${cur#"$name@"}` / `echo "$name updated ${old:-(none)} -> $short"` to `echo "$name updated ${old:-(none)} -> ${dir#"$name@"}"` (unchanged output without path).

Main loop:

```bash
while IFS=$'\t' read -r name repo ref sub; do
  [ -n "${name:-}" ] || continue
  rc=0
  out=$(check_line "$name" "$repo" "$ref" "${sub:-}") && { out=$(deploy_one "$name" "$repo" "$ref" "${sub:-}" < /dev/null) || rc=$?; } || rc=1
```

The script goes through Jinja: do not write `{#` (see the existing comment); `${sub//\//-}` and `${dir#"$name@"}` are fine (`test_script_without_jinja_delimiters` checks it).

- [ ] **Step 4: Run the whole suite** (test command). Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add serasoft_airflow/hop.py tests/test_distribution_script.py
git commit -m "feat: distribute only the project subfolder (path) as <project>@<commit>-<path>"
```

---

### Task 4: docs and lab check (airflow-dags, #63)

**Files:**
- Modify: `README.md` (distribution bullets), `config/hop_projects.yaml.example`, `docs/dag-author-guide.md` ("Project versions"), `config/hop_projects.yaml` (lab)
- Create: `docs/superpowers/specs/2026-11-12-hop-project-path-design.md`, `dags/lab/lab_hop_sottocartella.py`

- [ ] **Step 1: README** — after the bullet starting `- **Project list**:` insert:

```markdown
- **Project in a subfolder**: optional `path` (e.g. `path: etl`): the Hop project is that folder of the repository and only it is copied; the version folder is `<project>@<commit12>-<path with / → ->` (e.g. `sales@8b11d0aa94c2-etl`), so a change of `path` is a new version. Several projects can come from the same repository with different paths. A path missing in the commit (or leaving the repository through a symlink) fails that project.
```

- [ ] **Step 2: `config/hop_projects.yaml.example`** — add after the `# ref  =` comment lines:

```yaml
# path = optional: folder of the repository holding the Hop project (default:
#        the whole repository); the version folder becomes <project>@<commit>-<path>.
```

and at the end:

```yaml
sales:
  repo: https://gitlab.cliente.it/etl/analytics.git
  path: etl
  ref: {dev: develop, test: test, prod: main}
```

- [ ] **Step 3: `docs/dag-author-guide.md`** — after the sentence ending `(one Git ref per environment).` add: `A project kept in a subfolder of its repository has a \`path\` there (e.g. \`path: etl\`): its versions are named \`<project>@<commit>-etl\`.`

- [ ] **Step 4: Lab** — append to `config/hop_projects.yaml`:

```yaml
# Project in a subfolder (spec 2026-11-12): the repository holds the project in
# etl/ and a copy in etl2/ (lab check, step 4).
hop-template-sub:
  repo: https://gitea:3000/etl/hop-template-sub.git
  path: etl
  ref: {lab: main}
```

Create `dags/lab/lab_hop_sottocartella.py` as a copy of `dags/lab/lab_hop_distribuito.py` with: docstring first line `lab_hop_sottocartella — acceptance test of a Hop project in a subfolder (spec 2026-11-12): like lab_hop_distribuito, on hop-template-sub (path etl in config/hop_projects.yaml).`, `dag_id="lab_hop_sottocartella"`, `params={"processo": Param("default", enum=["default"])}`, tags `["lab", "hop", "collaudo", "distribuzione"]`, `project="hop-template-sub"`; everything else unchanged.

- [ ] **Step 5: Spec** — create `docs/superpowers/specs/2026-11-12-hop-project-path-design.md`:

````markdown
# Design: Hop projects in a subfolder (path in hop_projects.yaml)

Status: approved
Date: 2026-11-12
Full design (both repositories): SeraSoft/hop-process-template `docs/superpowers/specs/2026-11-12-project-subfolder-design.md`

## Decisions

| # | Decision |
|---|---|
| 1 | Optional `path` per project in `config/hop_projects.yaml`; only that subfolder is copied to the share |
| 2 | Several projects from the same repository (different `path`) |
| 3 | Version folder `<project>@<commit12>-<path with / → ->`: a `path` change is a new version, version folders stay immutable |
| 4 | Fourth tab-separated field of `SERASOFT_HOP_DEPLOY_PROJECTS` only when `path` is set: lines and folders of projects without `path` unchanged |
| 5 | Execution (`run_hop_workflow`) unchanged: the version folder is the project |
| 6 | Release `v1.8.0` |

## Lab check (Swarm, lab machine)

Prerequisites: lab up (Gitea, Swarm, share), template `3.4.0` tag available.

1. Test repository in the lab's Gitea, `etl/hop-template-sub`:
   ```
   git init hop-template-sub && cd hop-template-sub
   <template checkout>/tools/serasoft-sync.sh --tag 3.4.0 --dest "$PWD/etl"   # after a first empty commit
   ```
   add to `etl/` the same project files as `hop-template-dist` (test process `default`, `config/env/lab.list`, project environment file), copy `etl/` to `etl2/`, add `reporting/README.md`, commit, push to `https://gitea:3000/etl/hop-template-sub.git`.
2. Trigger `mnt_distribuzione_hop` with `progetto=hop-template-sub`.
   Expected in the log: `hop-template-sub updated (none) -> <commit12>-etl`; on the share `hop-template-sub@<commit12>-etl/` (with `main.hwf`, `config/`, no `reporting/`, no `etl2/`) and `hop-template-sub.current` naming it.
3. Trigger `lab_hop_sottocartella` (backend swarm, then ssh). Expected: success; log `[serasoft] project hop-template-sub version hop-template-sub@<commit12>-etl` and `hop rc=0`.
4. Set `path: etl2` in `config/hop_projects.yaml`, trigger `mnt_distribuzione_hop` again. Expected: `-> <commit12>-etl2`, pointer moved, `…-etl` still on the share; `lab_hop_sottocartella` runs on `…-etl2`. Set `path: etl` back.
5. Report the logs of steps 2-4.
````

- [ ] **Step 6: Run the whole suite** (test command; `test_standards` covers the new lab DAG). Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add README.md config/hop_projects.yaml.example config/hop_projects.yaml docs/dag-author-guide.md \
  docs/superpowers/specs/2026-11-12-hop-project-path-design.md dags/lab/lab_hop_sottocartella.py
git commit -m "docs: Hop projects in a subfolder (path), lab check"
```

---

## After the tasks (controller)

- hop-process-template: final review, push `feat/project-subfolder`, PR closing #79 (the spec and this plan are on that branch). Tag `3.4.0` only when the user asks.
- airflow-dags: final review, push `feat/hop-project-path`, PR closing #61, #62, #63. Tag `v1.8.0` only when the user asks.
- Lab check: the user runs the procedure of the airflow-dags spec; outputs compared with the expected results.
