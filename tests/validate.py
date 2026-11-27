"""Offline distribution and disposable Git workflow checks (Python 3.11+)."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def git(cwd, *args):
    return run("git", "-c", "core.hooksPath=/dev/null", *args, cwd=cwd).stdout.strip()


def verify_catalog():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    assert manifest["name"] == "nstack" and manifest["version"] == "0.3.0"
    skills = ROOT / manifest["skills"]
    names = set()
    for path in skills.glob("*/SKILL.md"):
        text = path.read_text()
        assert text.startswith("---\n")
        assert re.search(rf"^name: {path.parent.name}$", text, re.M)
        assert re.search(r"^description: .+", text, re.M)
        names.add(path.parent.name)
        for relative in re.findall(r"\]\((\.\.?/[^)#]+)", text):
            assert (path.parent / relative).is_file(), (path, relative)
    assert len(names) == 26
    assert {"natori-mode", "setup-nstack"} <= names
    assert {"poteto-mode", "setup-pstack"}.isdisjoint(names)
    assert {path.stem for path in (ROOT / "examples/agents").glob("*.toml")} == {
        "nstack_implement", "nstack_security", "nstack_review",
    }
    for path in (ROOT / "examples/agents").glob("*.toml"):
        config = tomllib.loads(path.read_text())
        assert config["name"] == path.stem and config["model"]
        if path.stem == "nstack_review":
            assert "sandbox_mode" not in config
            assert "read-only parent" in config["developer_instructions"]
    swarm = (skills / "swarm/SKILL.md").read_text()
    assert "Codex" not in swarm and "active harness adapter" in swarm
    assert "Git worktree" in swarm and "without granting sibling write access" in swarm
    return names


def verify_discovery(repo, home, snapshot, names):
    messages = [
        {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "pstack-test", "version": "0.1"}}},
        {"method": "initialized"},
        {"id": 2, "method": "skills/list", "params": {"cwds": [str(repo)]}},
    ]
    with subprocess.Popen(
        ["env", f"CODEX_HOME={home}", "codex", "app-server", "--strict-config"],
        cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True,
    ) as server:
        try:
            import select

            for message in messages:
                server.stdin.write(json.dumps(message) + "\n")
                server.stdin.flush()
                if "id" not in message:
                    continue
                for _ in range(50):
                    assert select.select([server.stdout], [], [], 5)[0], "Codex response timed out"
                    response = json.loads(server.stdout.readline())
                    if response.get("id") == message["id"]:
                        assert "result" in response, response
                        break
                else:
                    raise AssertionError("Codex response missing")
            paths = {}
            for entry in response["result"]["data"]:
                for skill in entry["skills"]:
                    if skill["enabled"]:
                        paths.setdefault(skill["name"], []).append(Path(skill["path"]).resolve())
            for name in names:
                expected = home / "nstack" / "snapshots" / snapshot / "skills" / name / "SKILL.md"
                assert paths.get(name) == [expected], (name, paths.get(name))
            assert {"poteto-mode", "setup-pstack"}.isdisjoint(paths)
        finally:
            server.terminate()


def verify_install(repo, directory, names):
    home = directory / "codex-home"

    def install(action, snapshot, source=ROOT, check=True):
        return run("python3", str(source / "adapters/codex/install.py"), "--home",
                   str(home), action, snapshot, cwd=repo, check=check)

    legacy = home / "skills" / "natori-mode"
    legacy.mkdir(parents=True)
    old_text = "---\nname: natori-mode\ndescription: legacy\n---\n"
    (legacy / "SKILL.md").write_text(old_text)
    custom = home / "agents" / "nstack_implement.toml"
    custom.parent.mkdir()
    custom.write_text('name = "nstack_implement"\nmodel = "personal-model"\n')

    install("stage", "first")
    install("stage", "first")
    conflict = install("activate", "first", check=False)
    assert conflict.returncode == 1 and "move existing skill" in conflict.stderr
    assert (legacy / "SKILL.md").read_text() == old_text
    legacy.rename(directory / "legacy-backup")
    legacy.symlink_to(directory / "legacy-backup", target_is_directory=True)
    conflict = install("activate", "first", check=False)
    assert conflict.returncode == 1 and "move existing skill" in conflict.stderr
    legacy.unlink()
    install("activate", "first")
    verify_discovery(repo, home, "first", names)
    alias = home / "skills" / "custom-alias"
    alias.mkdir()
    for name in ('"natori-mode" # quoted alias', "'natori-mode'", ">-\n  natori-mode"):
        (alias / "SKILL.md").write_text(f"---\nname: {name}\ndescription: collision\n---\n")
        conflict = install("activate", "first", check=False)
        assert conflict.returncode == 1 and "move existing skill" in conflict.stderr
    alias.rename(directory / "alias-backup")

    next_source = directory / "new-source"
    for name in ("skills", "examples", "adapters", "docs"):
        shutil.copytree(ROOT / name, next_source / name)
    for name in ("LICENSE", "LICENSE-upstream", "README.md", "README.ja.md"):
        shutil.copy2(ROOT / name, next_source / name)
    skill = "natori-mode/SKILL.md"
    with (next_source / "skills" / skill).open("a") as changed:
        changed.write("\nUpgrade marker.\n")
    conflict = install("stage", "first", next_source, check=False)
    assert conflict.returncode == 1 and "different files" in conflict.stderr
    install("stage", "second", next_source)
    live = home / "skills" / "nstack-managed" / skill
    assert "Upgrade marker." not in live.read_text()
    install("activate", "second")
    verify_discovery(repo, home, "second", names)
    assert "Upgrade marker." in live.read_text()
    install("activate", "first")
    verify_discovery(repo, home, "first", names)
    assert "Upgrade marker." not in live.read_text()
    assert custom.read_text() == 'name = "nstack_implement"\nmodel = "personal-model"\n'


def verify_roles(directory):
    adapter = ROOT / "adapters/codex"
    standard = ROOT / "examples/agents/nstack_security.toml"
    optional = adapter / "optional/nstack_security_daybreak.toml"
    effort = [{"reasoningEffort": "medium"}]
    normal = {"model": "gpt-6.2-sol", "supportedReasoningEfforts": effort}
    special = {"model": "gpt-daybreak-blue-latest", "modelSpecialty": "cyber",
               "hidden": True, "supportedReasoningEfforts": effort}

    def check_role(role, entries, *args):
        return subprocess.run(["python3", str(adapter / "check_role.py"), str(role), *args],
                              input=json.dumps({"data": entries}), text=True, capture_output=True)

    assert check_role(standard, [normal, special]).returncode == 0
    missing = check_role(standard, [special])
    assert missing.returncode == 1 and "absent" in missing.stderr
    denied = check_role(optional, [normal, special], "--daybreak-selected")
    assert denied.returncode == 1 and "does not advertise" in denied.stderr
    special["availableAccessPrograms"] = {"cyber": ["daybreakBlue"]}
    opt_in = check_role(optional, [normal, special])
    assert opt_in.returncode == 1 and "explicitly select" in opt_in.stderr
    enabled = check_role(optional, [normal, special], "--daybreak-selected")
    assert enabled.returncode == 0 and "provider response unverified" in enabled.stdout

    custom = directory / "personal-role.toml"
    custom.write_text('name = "nstack_implement"\n')
    personal = {"model": "custom-model", "supportedReasoningEfforts": effort}
    result = check_role(custom, [personal], "--inherited-model", "custom-model",
                        "--inherited-effort", "medium")
    assert result.returncode == 0 and "custom-model advertised" in result.stdout
    result = check_role(custom, [personal], "--inherited-model", "custom-model",
                        "--inherited-effort", "high")
    assert result.returncode == 1 and "reasoning effort high" in result.stderr


def verify_worktrees(repo, directory):
    (repo / "value.py").write_text("def total(a, b):\n    return a - b\n")
    (repo / "check.py").write_text("from value import total\nassert total(2, 3) == 5\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    base = git(repo, "rev-parse", "HEAD")
    fix, docs, review = (directory / name for name in ("fix", "docs", "review"))
    for target in (fix, docs, review):
        git(repo, "worktree", "add", "--detach", str(target), base)
    # Independent reviewer reproduces the original contract failure.
    result = run("python3", "-B", "check.py", cwd=review, check=False)
    assert result.returncode == 1 and "AssertionError" in result.stderr

    def fix_bug():
        (fix / "value.py").write_text("def total(a, b):\n    return a + b\n")
        run("python3", "-B", "check.py", cwd=fix)

    def write_docs():
        (docs / "README.md").write_text("total adds two numbers.\n")
        assert (docs / "README.md").read_text().startswith("total adds")

    with ThreadPoolExecutor(2) as workers:
        tasks = [workers.submit(task) for task in (fix_bug, write_docs)]
        for task in tasks:
            task.result(timeout=10)
    assert git(fix, "status", "--porcelain") == "M value.py"
    assert git(docs, "status", "--porcelain") == "?? README.md"
    assert git(review, "status", "--porcelain") == git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD") == base
    assert git(repo, "remote") == ""


if __name__ == "__main__":
    names = verify_catalog()
    with TemporaryDirectory(prefix="pstack-test-") as temporary:
        directory = Path(temporary)
        repo = directory / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        verify_install(repo, directory, names)
        verify_roles(directory)
        verify_worktrees(repo, directory)
    workflow = run(sys.executable, "-B", str(ROOT / "tests/review_workflow.py"), cwd=ROOT)
    print(workflow.stdout.strip())
    print(f"{len(names)} skills discovered; install/upgrade/rollback, role preflight and isolated Git fixture verified")
