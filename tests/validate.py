"""Offline distribution and disposable Git workflow checks (Python 3.11+)."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def git(cwd, *args):
    return run("git", "-c", "core.hooksPath=/dev/null", *args, cwd=cwd).stdout.strip()


def verify_catalog():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
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
    for path in (ROOT / "examples/agents").glob("*.toml"):
        config = tomllib.loads(path.read_text())
        assert config["name"] == path.stem and config["model"]
        if path.stem == "pstack_review":
            assert "sandbox_mode" not in config
            assert "read-only parent" in config["developer_instructions"]
    return names


def verify_discovery(repo, directory, names):
    home = directory / "home"
    home.mkdir()
    shutil.copytree(ROOT / "skills", home / "skills")
    shutil.copytree(ROOT / "examples/agents", home / "agents")
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
            found = {skill["name"] for entry in response["result"]["data"]
                     for skill in entry["skills"] if skill["enabled"]}
            assert names <= found, names - found
        finally:
            server.terminate()


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
        verify_discovery(repo, directory, names)
        verify_worktrees(repo, directory)
    print(f"{len(names)} skills discovered; isolated review and two local tasks verified")
