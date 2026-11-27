"""Exercise the exact host CLI using a deterministic Codex protocol double."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def exercise(root, fake_bin, scenario, expectation, *, gated=True, budget=2, review_only=False):
    directory = root / scenario
    directory.mkdir()
    source = directory / "source"
    repo = directory / "repo"
    remote = directory / "remote.git"
    source.mkdir()
    git(source, "init", "-qb", "main")
    git(source, "config", "user.name", "Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    git(source, "config", "commit.gpgsign", "false")
    (source / "seed.py").write_text('VALUE = "base"\n')
    shutil.copytree(ROOT / "adapters", source / "adapters")
    git(source, "add", ".")
    git(source, "commit", "-qm", "base")
    base = git(source, "rev-parse", "HEAD")
    git(source, "clone", "-q", "--bare", "--no-local", str(source), str(remote))
    git(source, "clone", "-q", "--no-local", str(remote), str(repo))
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "switch", "-qc", "feature")
    if review_only:
        (repo / "result.txt").write_text("correct\n")
        git(repo, "add", "result.txt")
        git(repo, "commit", "-qm", "review-only candidate")
    initial = git(repo, "rev-parse", "HEAD")
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == ""
    if scenario == "dirty":
        (repo / "user-file").write_text("preserve this file\n")
    destination = remote
    if scenario == "success":
        git(repo, "config", "push.followTags", "true")
        git(repo, "tag", "-am", "unapproved tag", "unapproved", base)
    if scenario == "rewritten":
        destination = directory / "effective.git"
        git(source, "clone", "-q", "--bare", str(source), str(destination))
        git(repo, "config", f"url.{destination}.pushInsteadOf", str(remote))
    if scenario == "detached-default":
        git(remote, "update-ref", "--no-deref", "HEAD", base)
        git(remote, "update-ref", "refs/remotes/origin/main", base)
        git(remote, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        assert "refs/remotes/origin/HEAD" in git(repo, "ls-remote", "--symref", str(remote), "HEAD")
    if scenario in {"assume-unchanged", "skip-worktree"}:
        git(repo, "update-index", f"--{scenario}", "seed.py")
        (repo / "seed.py").write_text("concealed modification\n")
        assert git(repo, "status", "--porcelain") == ""
    brief = directory / "brief"
    brief.write_text("The result.txt output must be correct.\n")
    evidence = directory / "evidence"
    home = directory / "codex-home"
    home.mkdir()
    config = home / "config.toml"
    original = '[mcp_servers."external.tool"]\ncommand = "false"\n'
    config.write_text(original)
    env = dict(os.environ, CODEX_HOME=str(home), PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
               NSTACK_REVIEW_TEST_SCENARIO=scenario)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)
    result = subprocess.run([
        sys.executable, "adapters/codex/review.py", "--authorize-host",
        "--repo", str(repo), "--base", base, "--brief", str(brief), "--evidence", str(evidence),
        "--max-remediations", str(budget), "--push", str(remote),
        *(["--review-only"] if review_only else []),
        "--", sys.executable, "-c",
        f"import seed; assert seed.VALUE == 'base'; raise SystemExit({0 if gated else 1})",
    ], cwd=repo, env=env, capture_output=True, text=True, timeout=30)
    status = json.loads((evidence / "status.json").read_text())
    assert config.read_text() == original
    assert not list(repo.rglob("__pycache__"))
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == (
        "?? user-file" if scenario == "dirty" else ""
    )
    assert git(repo, "diff", "--name-only", base, "HEAD") in ("", "result.txt")
    remote_ref = git(repo, "ls-remote", "--refs", str(destination), "refs/heads/feature")
    assert git(repo, "ls-remote", "--tags", str(destination)) == ""
    if scenario == "rewritten":
        assert git(repo, "ls-remote", "--refs", str(remote), "refs/heads/feature") == ""
    if expectation:
        assert result.returncode == 1 and expectation in status["error"], (result, status)
        assert remote_ref == ""
        if scenario in {"unauthenticated", "permission", "model", "mcp-forced", "gate-scratch", "wrong-policy"}:
            assert git(repo, "rev-parse", "HEAD") == base
        if scenario == "review-only-changes":
            review = json.loads((evidence / "0-review.json").read_text())
            assert review["review"]["verdict"] == status["status"] == "changes_requested"
            assert status["candidate"] == review["candidate"]
            assert not list(evidence.glob("*-implementation.json"))
        if scenario in {"assume-unchanged", "skip-worktree"}:
            assert not (evidence / "request.json").exists()
            assert (repo / "seed.py").read_text() == "concealed modification\n"
        if scenario == "repeat":
            assert not (evidence / "2-implementation.json").exists()
        return

    assert result.returncode == 0 and status["status"] == "pass", (result, status)
    preflight = json.loads((evidence / "preflight.json").read_text())
    assert preflight["disabledMcpServers"] == 1 and preflight["gateScratchWrite"]
    assert preflight["roles"][-1]["sandbox"] == "readOnly"
    first = json.loads((evidence / "0-review.json").read_text())
    if review_only:
        assert not (evidence / "0-implementation.json").exists()
        assert json.loads(first["message"])["verdict"] == "pass"
        assert remote_ref.split() == [initial, "refs/heads/feature"]
        return
    second = json.loads((evidence / "1-review.json").read_text())
    implementation = json.loads((evidence / "1-implementation.json").read_text())
    assert first["candidate"] != second["candidate"] == status["candidate"]
    assert len({first["session"], second["session"], implementation["session"]}) == 3
    assert first["model"] == second["model"] == "gpt-6.2-astra"
    assert implementation["model"] == "gpt-6.2-sol"
    assert json.loads(first["message"])["verdict"] == "changes_requested"
    assert json.loads(second["message"])["verdict"] == "pass"
    assert second["writeProbe"] == "write-denied 13"
    assert remote_ref.split() == [second["candidate"], "refs/heads/feature"]
    assert (repo / "result.txt").read_text() == "correct\n"


def verify_pr_delivery(root):
    sys.path.insert(0, str(ROOT / "adapters"))
    import review_workflow

    repo = root / "pr-repo"
    repo.mkdir()
    remote = root / "pr-remote.git"
    git(repo, "init", "-qb", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    for value in ("first", "unreviewed", "reviewed"):
        (repo / value).write_text(value)
        git(repo, "add", value)
        git(repo, "commit", "-qm", value)
        if value == "first":
            git(repo, "switch", "-qc", "feature")
    git(repo, "clone", "-q", "--bare", str(repo), str(remote))
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    git(remote, "update-ref", "-d", "refs/heads/feature")
    candidate = git(repo, "rev-parse", "HEAD")
    reviewed_base = git(repo, "rev-parse", "HEAD^")
    actual_base = git(repo, "rev-parse", "main")
    args = SimpleNamespace(push=str(remote), github_repo="fixture/project",
                           pr_base="main", pr_title="Fixture")
    evidence = root / "pr-evidence"
    evidence.mkdir()
    # Simulate GitHub's API, using real Git refs and merge-base computation.
    with patch.object(review_workflow, "delivery_target", return_value=(str(remote), ())):
        try:
            review_workflow.deliver(args, repo, reviewed_base, candidate, evidence)
        except ValueError as error:
            assert "PR diff does not match" in str(error)
        else:
            raise AssertionError("delivery accepted an unreviewed PR diff")
        assert git(remote, "for-each-ref", "refs/heads/feature") == ""

        real_run = subprocess.run
        reported_base = reviewed_base

        def gh(argv, **kwargs):
            if argv[0] != "gh":
                return real_run(argv, **kwargs)
            if argv[2] == "list":
                result = [{"isCrossRepository": False}]
            else:
                result = {"isCrossRepository": False, "headRefOid": candidate,
                          "baseRefName": "main", "baseRefOid": reported_base, "url": "fixture-pr"}
            return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")

        with patch.object(review_workflow.subprocess, "run", side_effect=gh):
            try:
                review_workflow.deliver(args, repo, actual_base, candidate, evidence)
            except ValueError as error:
                assert "PR diff does not match" in str(error)
            else:
                raise AssertionError("GitHub-reported diff was not verified")
            assert not (evidence / "delivery.json").exists()
            reported_base = actual_base
            review_workflow.deliver(args, repo, actual_base, candidate, evidence)
        record = json.loads((evidence / "delivery.json").read_text())
        assert record["candidate"] == candidate and record["base"] == actual_base
        assert record["pr"] == "fixture-pr"



def verify_real_config(root):
    home = root / "mcp-home"
    home.mkdir()
    config = home / "config.toml"
    original = ('[mcp_servers.tool]\ncommand = "false"\n'
                '[mcp_servers."tool.with.dot"]\ncommand = "false"\n'
                '[mcp_servers.disabled]\ncommand = "false"\nenabled = false\n')
    config.write_text(original)
    probe = """
from pathlib import Path
from review_adapter import CodexAdapter, enabled_mcp
cwd = Path.cwd()
adapter = CodexAdapter(20)
with adapter.connection(cwd, cwd / "normal") as server:
    config = server.request("config/read", {"cwd": str(cwd)})["config"]
    assert set(enabled_mcp(config)) == {"tool", "tool.with.dot"}
with adapter.isolated(cwd, cwd / "isolated") as (server, count):
    config = server.request("config/read", {"cwd": str(cwd)})["config"]
    assert count == 2 and not enabled_mcp(config)
    assert config["mcp_servers"]["tool.with.dot"]["command"] == "false"
"""
    subprocess.run([sys.executable, "-B", "-c", probe], cwd=root,
                   env={**os.environ, "CODEX_HOME": str(home),
                        "PYTHONPATH": str(ROOT / "adapters/codex")}, check=True)
    assert config.read_text() == original


if __name__ == "__main__":
    with TemporaryDirectory(prefix="nstack-review-test-") as temporary:
        root = Path(temporary)
        verify_real_config(root)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        command = fake_bin / "codex"
        shutil.copyfile(ROOT / "tests/fixtures/review_app_server.py", command)
        command.chmod(0o700)
        exercise(root, fake_bin, "success", None)
        exercise(root, fake_bin, "review-only", None, review_only=True)
        exercise(root, fake_bin, "review-only-changes", "requested changes in review-only mode", review_only=True)
        exercise(root, fake_bin, "rewritten", None)
        exercise(root, fake_bin, "detached-default", "cannot verify a non-default remote branch")
        exercise(root, fake_bin, "assume-unchanged", "checkout has index flags")
        exercise(root, fake_bin, "skip-worktree", "checkout has index flags")
        verify_pr_delivery(root)
        exercise(root, fake_bin, "unauthenticated", "no authenticated account")
        exercise(root, fake_bin, "model", "absent from the active model catalog")
        exercise(root, fake_bin, "permission", "permitted writing")
        exercise(root, fake_bin, "mcp-forced", "MCP overrides did not take effect")
        exercise(root, fake_bin, "gate-scratch", "could not verify quality gate scratch writes")
        exercise(root, fake_bin, "wrong-policy", "unexpected sandbox policy")
        exercise(root, fake_bin, "sha", "does not match the candidate")
        exercise(root, fake_bin, "reroute", "reported a model reroute")
        exercise(root, fake_bin, "repeat", "same independent findings")
        exercise(root, fake_bin, "budget", "remediation budget exhausted", budget=0)
        exercise(root, fake_bin, "dirty", "dirty checkout")
        exercise(root, fake_bin, "gate", "quality gate failed", gated=False)
    print("host review CLI: remediation, exact SHA push and fail-closed protocol cases verified")
