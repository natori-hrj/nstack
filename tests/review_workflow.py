"""Exercise the exact host CLI using a deterministic Codex protocol double."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def exercise(root, fake_bin, scenario, expectation, *, gated=True, budget=2, review_only=False):
    directory = root / scenario
    directory.mkdir()
    repo = directory / "repo"
    remote = directory / "remote.git"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "seed").write_text("base\n")
    git(repo, "add", "seed")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "clone", "-q", "--bare", str(repo), str(remote))
    git(repo, "switch", "-qc", "feature")
    if review_only:
        (repo / "result.txt").write_text("correct\n")
        git(repo, "add", "result.txt")
        git(repo, "commit", "-qm", "review-only candidate")
    initial = git(repo, "rev-parse", "HEAD")
    brief = directory / "brief"
    brief.write_text("The result.txt output must be correct.\n")
    evidence = directory / "evidence"
    env = dict(os.environ, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
               NSTACK_REVIEW_TEST_SCENARIO=scenario)
    result = subprocess.run([
        sys.executable, "-B", str(ROOT / "adapters/codex/review.py"), "--authorize-host",
        "--repo", str(repo), "--base", base, "--brief", str(brief), "--evidence", str(evidence),
        "--max-remediations", str(budget), "--push", str(remote),
        *(["--review-only"] if review_only else []),
        "--", sys.executable, "-c", f"raise SystemExit({0 if gated else 1})",
    ], env=env, capture_output=True, text=True, timeout=30)
    status = json.loads((evidence / "status.json").read_text())
    remote_ref = git(repo, "ls-remote", "--refs", str(remote), "refs/heads/feature")
    if expectation:
        assert result.returncode == 1 and expectation in status["error"], (result, status)
        assert remote_ref == ""
        if scenario in {"unauthenticated", "permission", "model", "mcp"}:
            assert git(repo, "rev-parse", "HEAD") == base
        if scenario == "repeat":
            assert not (evidence / "2-implementation.json").exists()
        return

    assert result.returncode == 0 and status["status"] == "pass", (result, status)
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


if __name__ == "__main__":
    with TemporaryDirectory(prefix="nstack-review-test-") as temporary:
        root = Path(temporary)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        command = fake_bin / "codex"
        shutil.copyfile(ROOT / "tests/fixtures/review_app_server.py", command)
        command.chmod(0o700)
        exercise(root, fake_bin, "success", None)
        exercise(root, fake_bin, "review-only", None, review_only=True)
        exercise(root, fake_bin, "unauthenticated", "no authenticated account")
        exercise(root, fake_bin, "model", "absent from the active model catalog")
        exercise(root, fake_bin, "permission", "permitted writing")
        exercise(root, fake_bin, "mcp", "disable MCP servers")
        exercise(root, fake_bin, "wrong-policy", "unexpected sandbox policy")
        exercise(root, fake_bin, "sha", "does not match the candidate")
        exercise(root, fake_bin, "reroute", "reported a model reroute")
        exercise(root, fake_bin, "repeat", "same independent findings")
        exercise(root, fake_bin, "budget", "remediation budget exhausted", budget=0)
        exercise(root, fake_bin, "gate", "quality gate failed", gated=False)
    print("host review CLI: remediation, exact SHA push and fail-closed protocol cases verified")
