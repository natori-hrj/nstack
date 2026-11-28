"""Compare the Go core and Python on disposable, credential-free fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from compatibility import FIXTURE, verify

ROOT = Path(__file__).resolve().parents[1]


def pr_case(directory, launcher, scenario, expected_error):
    repo, remote, evidence = (directory / name for name in ("repo", "remote.git", "evidence"))
    repo.mkdir(parents=True)
    home, tools, state = (directory / name for name in ("home", "bin", "state"))
    for path in (home, tools, state):
        path.mkdir()
    git = shutil.which("git")
    env = {
        "PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "file",
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "NSTACK_CONTRACT_SCENARIO": "pass",
        "NSTACK_FIXTURE_GIT": git, "NSTACK_FIXTURE_REMOTE": str(remote),
        "NSTACK_FIXTURE_PR_CASE": scenario, "NSTACK_FIXTURE_PR_STATE": str(state),
    }

    def vcs(*args, cwd=repo):
        return subprocess.check_output([git, "-c", "core.hooksPath=/dev/null", *args],
                                       cwd=cwd, env=env, text=True).strip()

    vcs("init", "-q", "-b", "main")
    value = repo / "value.txt"
    value.write_text("base\n")
    vcs("add", "value.txt")
    vcs("commit", "-qm", "base")
    base = vcs("rev-parse", "HEAD")
    vcs("switch", "-qc", "fixture")
    value.write_text("candidate\n")
    vcs("add", "value.txt")
    vcs("commit", "-qm", "candidate")
    candidate = vcs("rev-parse", "HEAD")
    vcs("clone", "-q", "--bare", "--no-local", str(repo), str(remote))
    vcs("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    initial = None if scenario in ("new", "post-push-failure") else base
    if initial:
        vcs("update-ref", "refs/heads/feature", initial, cwd=remote)
    vcs("remote", "add", "delivery", "https://github.com/fixture/project")
    for name in ("git", "gh"):
        path = tools / name
        shutil.copyfile(ROOT / "tests/fixtures/pr_delivery_tools.py", path)
        path.chmod(0o700)
    env.update(PATH=f"{tools}{os.pathsep}{env['PATH']}",
               NSTACK_FIXTURE_BASE=base, NSTACK_FIXTURE_CANDIDATE=candidate)
    brief = directory / "brief"
    brief.write_text("Verify the candidate file.\n")
    pr = {"explicit": ["--pr-number", "42"], "explicit-ambiguous": ["--pr-number", "42"],
          "explicit-other": ["--pr-number", "99"]}.get(scenario, ["--pr-title", "Fixture"])
    completed = subprocess.run([
        *launcher, "--authorize-host", "--repo", str(repo), "--base", base, "--brief", str(brief),
        "--evidence", str(evidence), "--review-only", "--push", "delivery",
        "--delivery-ref", "refs/heads/feature", "--github-repo", "fixture/project",
        "--pr-base", "main", *pr, "--", sys.executable, "-c",
        "from pathlib import Path; assert Path('value.txt').read_text() == 'candidate\\n'",
    ], cwd=repo, env=env, capture_output=True, text=True, timeout=30)
    artifacts = {path.name: json.loads(path.read_text()) for path in evidence.glob("*.json")}
    status = artifacts["status.json"]
    assert completed.returncode == int(bool(expected_error)), (scenario, completed, status)
    if expected_error:
        assert status["status"] == "blocked" and expected_error in status["error"], status
        status.pop("error")  # Git subprocess diagnostics may differ between runtimes.
        assert "delivery.json" not in artifacts, scenario
    else:
        assert status["status"] == "pass" and status["candidate"] == candidate, status
        assert artifacts["delivery.json"] == {
            "candidate": candidate, "base": base, "ref": "refs/heads/feature",
            "defaultRef": "refs/heads/main", "pr": "https://github.com/fixture/project/pull/42",
        }
    status.pop("elapsedSeconds")
    head = vcs("for-each-ref", "--format=%(objectname)", "refs/heads/feature", cwd=remote)
    expected_head = candidate if not expected_error or scenario in {"post-push-failure", "remote-moved"} else initial
    assert head == (expected_head or ""), (scenario, head, expected_head)
    assert (state / "created").exists() == (scenario == "new"), scenario
    assert vcs("rev-parse", "HEAD") == candidate and vcs("symbolic-ref", "HEAD") == "refs/heads/fixture"
    assert vcs("status", "--porcelain") == "" and value.read_text() == "candidate\n"
    assert vcs("rev-parse", "refs/heads/main", cwd=remote) == base
    return completed.returncode, artifacts, head


def main():
    with TemporaryDirectory(prefix="nstack-go-compat-") as scratch:
        root = Path(scratch)
        binary = root / "go-review"
        subprocess.run(["go", "build", "-o", str(binary), "./tests/fixtures/go-review"], cwd=ROOT, check=True)
        bridge = ROOT / "tests/fixtures/go_review_bridge.py"
        python = [sys.executable, "-B", str(FIXTURE)]
        go = [str(binary), str(bridge), "portable"]
        verify(python)
        verify(go)
        print("G1 portable cases passed on Python and Go", flush=True)
        for name, error in {
            "new": "", "existing": "", "ambiguous": "unique open PR", "wrong-base": "reviewed base",
            "wrong-ref": "authorized branches", "explicit": "", "explicit-other": "authorized PR",
            "explicit-ambiguous": "unique open PR", "remote-moved": "delivery candidate changed",
            "post-push-failure": "gh",  # Push succeeded; PR creation failed.
        }.items():
            expected = pr_case(root / "python" / name, python, name, error)
            actual = pr_case(root / "go" / name, go, name, error)
            assert actual == expected, name
        print("PR delivery evidence and side effects match on Python and Go", flush=True)
        home = root / "protocol-home"
        home.mkdir()
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(root),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "file",
               "PYTHONUTF8": "1"}
        subprocess.run([sys.executable, "-B", str(ROOT / "tests/review_workflow.py"),
                        "--", str(binary), str(bridge), "protocol"], env=env, check=True)


if __name__ == "__main__":
    main()
