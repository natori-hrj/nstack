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


def exercise(root, fake_bin, scenario, expectation, *, gated=True, budget=2, review_only=False, review_first=False):
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
    if review_only or review_first:
        result_value = "incorrect" if review_first and scenario not in {"review-first-pass", "review-first-detached"} else "correct"
        (repo / "result.txt").write_text(result_value + "\n")
        git(repo, "add", "result.txt")
        git(repo, "commit", "-qm", "review-only candidate")
    initial = git(repo, "rev-parse", "HEAD")
    delivery_branch = "None" if scenario == "delivery-none" else "feature"
    work_branch = "None" if scenario == "work-none" else "authorized-work"
    if scenario.startswith("protected-delivery-"):
        delivery_branch = scenario.removeprefix("protected-delivery-")
        git(remote, "update-ref", "refs/heads/develop/v0.3.0", base)
        git(remote, "symbolic-ref", "HEAD", "refs/heads/develop/v0.3.0")
        git(remote, "update-ref", "-d", "refs/heads/main")
    delivery_ref = f"refs/heads/{delivery_branch}"
    work_ref = f"refs/heads/{work_branch}"
    if scenario == "review-first-detached":
        git(repo, "switch", "--detach", initial)
    if scenario == "review-first-collision":
        git(repo, "branch", "authorized-work")
    if scenario == "remote-default":
        git(repo, "push", str(remote), f"{base}:refs/heads/feature")
        git(remote, "symbolic-ref", "HEAD", "refs/heads/feature")
        git(repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
    if scenario in {"delivery-mismatch", "review-only-fast-forward"}:
        git(repo, "push", str(remote), f"{base}:{delivery_ref}")
    remote_start = git(repo, "ls-remote", "--refs", str(remote), delivery_ref)
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
    local_only = {"review-first-detached", "review-first-no-auth", "local-no-auth"}
    no_work = {"review-first-pass", "review-first-detached", "review-first-no-auth", "local-no-auth"}
    result = subprocess.run([
        sys.executable, "adapters/codex/review.py", "--authorize-host",
        "--repo", str(repo), "--base", base, "--brief", str(brief), "--evidence", str(evidence),
        "--max-remediations", str(budget),
        *([] if scenario in no_work or review_only else ["--work-ref", work_ref]),
        *([] if scenario in local_only else [
            "--push", "origin" if scenario == "destination-changed" else str(remote),
            "--delivery-ref", delivery_ref,
        ]),
        *(["--review-only"] if review_only else []),
        *(["--review-first"] if review_first else []),
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
    remote_ref = git(repo, "ls-remote", "--refs", str(destination), delivery_ref)
    assert git(repo, "ls-remote", "--tags", str(destination)) == ""
    if scenario == "rewritten":
        assert git(repo, "ls-remote", "--refs", str(remote), "refs/heads/feature") == ""
    if expectation:
        assert result.returncode == 1 and expectation in status["error"], (result, status)
        assert remote_ref == remote_start
        if scenario in {
            "review-first-no-auth", "local-no-auth", "review-first-collision", "remote-default",
            "detached-default", "delivery-mismatch", "writer-ref-changed", "destination-changed",
        }:
            assert git(repo, "rev-parse", "HEAD") == initial
            if scenario not in {"writer-ref-changed", "destination-changed"}:
                assert not list(evidence.glob("*-implementation.json"))
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
        if scenario == "review-first-repeat":
            first, second = [json.loads((evidence / f"{i}-review.json").read_text()) for i in (0, 1)]
            assert first["candidate"] != second["candidate"]
            assert list(first["newFindingIds"]) == ["F1", "F2"]
            assert [p["id"] for p in second["review"]["previous"]] == ["F2", "F1"]
            assert [p["status"] for p in second["review"]["previous"]] == ["resolved", "recurring"]
            assert second["review"]["findings"] and second["base"] == first["base"]
            assert second["candidate"] in second["review"]["previous"][1]["evidence"]
            assert "1-review" in second["review"]["previous"][1]["evidence"]
            assert json.loads(second["message"]) == second["review"]
            assert git(repo, "rev-parse", "HEAD^") == initial
        if scenario in {"review-first-missing", "review-first-unknown"}:
            invalid = json.loads((evidence / "1-review.json").read_text())
            assert invalid["candidate"] == git(repo, "rev-parse", "HEAD")
            assert invalid["base"] == base and invalid["validationError"] and invalid["message"]
        if scenario in {"repeat", "review-first-repeat", "review-first-uncertain",
                        "review-first-missing", "review-first-unknown"}:
            assert not (evidence / "2-implementation.json").exists()
        if review_first:
            assert not (evidence / "0-implementation.json").exists()
            if scenario not in {"review-first-repeat", "review-first-two-rounds", "review-first-uncertain",
                                "review-first-missing", "review-first-unknown"}:
                assert git(repo, "rev-parse", "HEAD") == initial
                assert not list(evidence.glob("*-implementation.json"))
            if scenario == "review-first-two-rounds":
                assert sorted(p.name for p in evidence.glob("*-implementation.json")) == [
                    "1-implementation.json", "2-implementation.json",
                ]
                assert len(list(evidence.glob("*-review.json"))) == 3
        return

    assert result.returncode == 0 and status["status"] == "pass", (result, status)
    if scenario != "review-first-detached":
        assert git(repo, "rev-parse", "refs/heads/feature") == initial
    preflight = json.loads((evidence / "preflight.json").read_text())
    assert preflight["disabledMcpServers"] == 1 and preflight["gateScratchWrite"]
    assert preflight["roles"][-1]["sandbox"] == "readOnly"
    first = json.loads((evidence / "0-review.json").read_text())
    if review_only or scenario in {"review-first-pass", "review-first-detached"}:
        assert not list(evidence.glob("*-implementation.json"))
        assert git(repo, "rev-parse", "HEAD") == initial
        assert not git(repo, "for-each-ref", work_ref)
        assert json.loads(first["message"])["verdict"] == "pass"
        if scenario == "review-first-detached":
            assert remote_ref == ""
        else:
            assert remote_ref.split() == [initial, delivery_ref]
        return
    second = json.loads((evidence / "1-review.json").read_text())
    implementation = json.loads((evidence / "1-implementation.json").read_text())
    if review_first:
        assert not (evidence / "0-implementation.json").exists()
        assert first["candidate"] == initial
        assert git(repo, "rev-parse", "HEAD^") == initial
    assert first["base"] == second["base"] == base
    for attempt, review in enumerate((first, second)):
        gate = json.loads((evidence / f"{attempt}-gate.json").read_text())
        assert gate["candidate"] == review["candidate"] and gate["base"] == base
    assert first["candidate"] != second["candidate"] == status["candidate"]
    assert len({first["session"], second["session"], implementation["session"]}) == 3
    assert first["model"] == second["model"] == "gpt-6.2-astra"
    assert implementation["model"] == "gpt-6.2-sol"
    assert json.loads(first["message"])["verdict"] == "changes_requested"
    assert json.loads(second["message"])["verdict"] == "pass"
    assert second["writeProbe"] == "write-denied 13"
    assert remote_ref.split() == [second["candidate"], delivery_ref]
    assert (repo / "result.txt").read_text() == "correct\n"
    assert git(repo, "symbolic-ref", "HEAD") == work_ref


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
            git(repo, "switch", "-qc", "123")
        if value == "unreviewed":
            git(repo, "switch", "-qc", "isolated")
    git(repo, "clone", "-q", "--bare", str(repo), str(remote))
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    candidate = git(repo, "rev-parse", "HEAD")
    start = git(repo, "rev-parse", "HEAD^")
    base = git(repo, "rev-parse", "main")
    args = SimpleNamespace(push=str(remote), github_repo="fixture/project", delivery_ref="refs/heads/123",
                           pr_base="main", pr_title=None, pr_number=456, review_only=False)
    evidence = root / "pr-evidence"
    evidence.mkdir()
    reported_head = "another-branch"
    view_calls = []

    def gh(cwd, github, *command):
        assert cwd == repo and github == "github.com/fixture/project"
        assert command[:2] == ("view", "456")
        remote_tip = git(remote, "rev-parse", "refs/heads/123")
        view_calls.append(remote_tip)
        return json.dumps({"number": 456, "state": "OPEN", "isCrossRepository": False,
                           "headRefName": reported_head, "headRefOid": remote_tip,
                           "baseRefName": "main", "baseRefOid": base,
                           "url": "https://github.com/fixture/project/pull/456"})

    with (patch.object(review_workflow, "delivery_target") as target,
          patch.object(review_workflow, "github_pr", side_effect=gh)):
        target.side_effect = lambda args, repo, name: ((
            "-c", f"remote.{name}.url={remote}", "-c", f"remote.{name}.pushurl={remote}",
        ), "github.com/fixture/project")
        for wrong_base, reason in ((start, "PR diff"), (base, "authorized branches")):
            try:
                review_workflow.Delivery(args, repo, wrong_base, start)
            except ValueError as error:
                assert reason in str(error)
            else:
                raise AssertionError("accepted a mismatched PR")
            assert git(remote, "rev-parse", "refs/heads/123") == start
        reported_head = "123"
        delivery = review_workflow.Delivery(args, repo, base, start)
        delivery.push(candidate, evidence)
    assert git(repo, "symbolic-ref", "HEAD") == "refs/heads/isolated"
    assert git(repo, "rev-parse", "refs/heads/123") == start
    assert git(remote, "rev-parse", "refs/heads/123") == candidate
    assert view_calls[-2:] == [start, candidate]
    record = json.loads((evidence / "delivery.json").read_text())
    assert record["candidate"] == candidate and record["base"] == base
    assert record["pr"] == "https://github.com/fixture/project/pull/456"


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
        exercise(root, fake_bin, "review-first-detached", None, review_first=True)
        exercise(root, fake_bin, "review-first-two-rounds", "remediation budget exhausted", review_first=True)
        exercise(root, fake_bin, "review-first-pass", None, review_first=True)
        exercise(root, fake_bin, "review-first-fix", None, review_first=True)
        exercise(root, fake_bin, "review-first-repeat", "recurs or remains uncertain", review_first=True)
        exercise(root, fake_bin, "review-first-uncertain", "recurs or remains uncertain", review_first=True)
        exercise(root, fake_bin, "review-first-unknown", "unexpected previous", review_first=True)
        exercise(root, fake_bin, "review-first-missing", "assess every previous", review_first=True)
        exercise(root, fake_bin, "review-first-no-auth", "explicit refs/heads/", review_first=True)
        exercise(root, fake_bin, "review-first-collision", "work ref must be new", review_first=True)
        exercise(root, fake_bin, "remote-default", "remote default", review_first=True)
        for branch in ("main", "master", "trunk"):
            exercise(root, fake_bin, f"protected-delivery-{branch}", "isolated feature branch", review_only=True)
        exercise(root, fake_bin, "delivery-mismatch", "starting candidate", review_first=True)
        exercise(root, fake_bin, "delivery-none", None, review_only=True)
        exercise(root, fake_bin, "work-none", None, review_first=True)
        exercise(root, fake_bin, "local-no-auth", "explicit refs/heads/")
        exercise(root, fake_bin, "writer-ref-changed", "work ref or candidate changed")
        exercise(root, fake_bin, "destination-changed", "effective delivery destination changed")
        exercise(root, fake_bin, "review-first-zero", "remediation budget exhausted", review_first=True, budget=0)
        exercise(root, fake_bin, "review-first-gate", "quality gate failed", review_first=True, gated=False)
        exercise(root, fake_bin, "review-first-blocked", "review blocked", review_first=True)
        exercise(root, fake_bin, "review-only", None, review_only=True)
        exercise(root, fake_bin, "review-only-fast-forward", None, review_only=True)
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
        exercise(root, fake_bin, "repeat", "recurs or remains uncertain")
        exercise(root, fake_bin, "budget", "remediation budget exhausted", budget=0)
        exercise(root, fake_bin, "dirty", "dirty checkout")
        exercise(root, fake_bin, "gate", "quality gate failed", gated=False)
    print("host review CLI: remediation, exact SHA push and fail-closed protocol cases verified")
