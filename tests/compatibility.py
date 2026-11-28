"""Run shared black-box review fixtures against an argv prefix (Python by default)."""
import argparse
import json
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "portable_review.py"


def exercise(directory, command, scenario):
    repo = directory / "repo"
    repo.mkdir(parents=True)
    home = directory / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "file",
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
        "NSTACK_CONTRACT_SCENARIO": scenario,
    }

    def git(*args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args],
                                       cwd=repo, env=env, text=True).strip()

    git("init", "-q", "-b", "fixture")
    value = repo / "value.txt"
    value.write_text("base\n")
    git("add", "value.txt")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    value.write_text("candidate\n")
    git("add", "value.txt")
    git("commit", "-qm", "candidate")
    start = git("rev-parse", "HEAD")
    brief = directory / "brief.md"
    brief.write_text("Review this candidate against the fixture contract.\n")
    evidence = directory / "evidence"
    mode = {
        "review-first": ["--review-first"],
        "implementation": ["--work-ref", "refs/heads/fixture-work"],
    }.get(scenario, ["--review-only"])
    expected_value = "implemented\n" if scenario == "implementation" else "candidate\n"
    gate = [
        sys.executable, "-B", "-c",
        f"from pathlib import Path; assert Path('value.txt').read_text() == {expected_value!r}; "
        f"raise SystemExit({7 if scenario == 'gate-failed' else 0})",
    ]
    result = subprocess.run([
        *command, *([] if scenario == "unauthorized" else ["--authorize-host"]),
        "--repo", str(repo), "--base", base, "--brief", str(brief), "--evidence", str(evidence),
        *mode, "--", *gate,
    ], cwd=repo, env=env, capture_output=True, text=True, timeout=30)

    def record(name):
        return json.loads((evidence / f"{name}.json").read_text())

    assert git("status", "--porcelain", "--untracked-files=all") == "", scenario
    candidate = git("rev-parse", "HEAD")
    expected_refs = [f"{start} refs/heads/fixture"]
    if scenario == "implementation":
        expected_refs.append(f"{candidate} refs/heads/fixture-work")
        assert git("symbolic-ref", "HEAD") == "refs/heads/fixture-work", scenario
        assert git("rev-parse", "HEAD^") == start and candidate != start, scenario
    else:
        assert candidate == start, scenario
        assert git("symbolic-ref", "--quiet", "HEAD") == "refs/heads/fixture", scenario
    assert git("show-ref").splitlines() == expected_refs and value.read_text() == expected_value, scenario
    if scenario == "unauthorized":
        assert result.returncode == 2 and "--authorize-host" in result.stderr, result
        assert not evidence.exists(), scenario
        return

    expected = {
        "pass": (0, "pass"), "review-first": (0, "pass"), "implementation": (0, "pass"),
        "changes-requested": (1, "changes_requested"), "wrong-sha": (1, "blocked"),
        "gate-failed": (1, "blocked"), "missing-capability": (1, "blocked"),
    }
    exit_code, state = expected[scenario]
    status = record("status")
    assert (result.returncode, status["status"]) == (exit_code, state), (scenario, result, status)
    if state != "blocked":
        assert status["candidate"] == candidate, status
    request = record("request")
    assert request["adapter"] == "portable-fixture", request
    assert request["start"] == start and request["base"] == base and request["gate"] == gate, request
    assert request["reviewOnly"] == (mode == ["--review-only"]), request
    assert request["reviewFirst"] == (scenario == "review-first") and request["maxRemediations"] == 2, request
    if scenario == "implementation":
        implementation = record("0-implementation")
        assert implementation["start"] == start and implementation["base"] == base, implementation
        assert implementation["workRef"] == "refs/heads/fixture-work", implementation
        assert implementation["model"] == "gpt-6.2-sol" and implementation["effort"] == "medium", implementation
    else:
        assert not list(evidence.glob("*-implementation.json")), scenario
    assert not (evidence / "delivery.json").exists(), scenario
    if scenario == "missing-capability":
        assert "required read-only capability" in status["error"], status
        assert not list(evidence.glob("*-gate.json")) and not list(evidence.glob("*-review.json")), scenario
        return
    gated = record("0-gate")
    assert gated["candidate"] == candidate and gated["base"] == base, gated
    assert gated["exitCode"] == (7 if scenario == "gate-failed" else 0), gated
    if scenario == "gate-failed":
        assert "quality gate failed" in status["error"] and not list(evidence.glob("*-review.json")), status
        return
    review = record("0-review")
    assert review["candidate"] == candidate and review["base"] == base, review
    assert review["session"] and review["model"] == "gpt-6.2-astra" and review["effort"] == "medium", review
    if scenario == "implementation":
        assert implementation["session"] and review["session"] != implementation["session"], review
    if scenario == "wrong-sha":
        assert "does not match the candidate" in review["validationError"] and "review" not in review, review
    else:
        verdict = review["review"]
        assert verdict == json.loads(review["message"]), review
        assert verdict["candidate"] == candidate and verdict["verdict"] == state, review
        findings = verdict.get("findings")
        if scenario == "changes-requested":
            assert isinstance(findings, list) and len(findings) == 1, review
            finding = findings[0]
            assert isinstance(finding, dict) and set(finding) == {
                "location", "evidence", "expected", "impact",
            }, review
            assert all(isinstance(value, str) and value.strip() for value in finding.values()), review
        else:
            assert findings == [], review
        if scenario in ("review-first", "implementation"):
            assert verdict.get("previous") == [], review


def verify(command=None):
    if not command:
        command = [sys.executable, "-B", str(FIXTURE)]
    scenarios = ("unauthorized", "pass", "review-first", "implementation", "changes-requested", "wrong-sha",
                 "gate-failed", "missing-capability")
    with TemporaryDirectory(prefix="nstack-contract-") as temporary:
        for scenario in scenarios:
            exercise(Path(temporary) / scenario, command, scenario)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, usage="%(prog)s [-- command [arg ...]]")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    command = parser.parse_args().command
    verify(command[1:] if command[:1] == ["--"] else command)
    print("Portable v0.3.0 review contract verified")
