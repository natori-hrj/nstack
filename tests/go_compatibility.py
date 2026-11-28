"""Compare the Go core and Python on disposable, credential-free fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from compatibility import FIXTURE, verify
from validate import verify_roles

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


def verify_role_toml(directory, native):
    directory.mkdir()
    home = directory / "home"
    tools = directory / "bin"
    home.mkdir()
    tools.mkdir()
    codex = tools / "codex"
    codex.write_text('#!/bin/sh\n: > "$CODEX_HOME/unexpected-dispatch"\nexit 99\n')
    codex.chmod(0o700)
    env = {
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}", "HOME": str(home),
        "CODEX_HOME": str(home), "PYTHONUTF8": "1",
    }
    role = directory / "role.toml"
    python = (sys.executable, "-B", str(ROOT / "adapters/codex/check_role.py"))
    go = (str(native), "check-role")
    optional = "nstack_security_daybreak"
    catalog = json.dumps({"data": [
        {"model": "configured", "supportedReasoningEfforts": [{"reasoningEffort": "high"}]},
        {"model": "inherited", "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]},
        {"model": "optional", "hidden": True, "modelSpecialty": "cyber",
         "availableAccessPrograms": {"cyber": ["daybreakBlue"]},
         "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]},
    ]})
    name = 'name = "review"\n'
    configured = 'model = "configured"\nmodel_reasoning_effort = "high"\n'
    # Each available model advertises a single effort, so a successful
    # check verifies the selected effort as well as the reported model.
    cases = [
        ("canonical", name + configured, "inherited", (), "review: configured", ""),
        ("uppercase model", name + 'MODEL = "configured"\nmodel_reasoning_effort = "high"\n', "absent", (), "",
         "absent is absent"),
        ("uppercase effort", name + 'MODEL_REASONING_EFFORT = "high"\n', "inherited", (),
         "review: inherited", ""),
        ("uppercase name", 'NAME = "review"\n', "inherited", (), "", ""),
        ("mixed case", name + '"MoDeL" = "configured"\nModel_Reasoning_Effort = "high"\n',
         "inherited", (), "review: inherited", ""),
        ("canonical and aliases", name + configured + 'NAME = "other"\nMODEL = "inherited"\n'
         'MODEL_REASONING_EFFORT = "medium"\n', "inherited", (), "review: configured", ""),
        ("unknown keys", name + 'unrecognized = 42\nMODE = false\n', "inherited", (),
         "review: inherited", ""),
        ("inherited", name, "inherited", (), "review: inherited", ""),
        ("inherited model and explicit effort", name + 'model_reasoning_effort = "high"\n',
         "inherited", (), "", "does not advertise reasoning effort high"),
        ("explicit model and inherited effort", name + 'model = "configured"\n',
         "inherited", (), "", "does not advertise reasoning effort medium"),
        ("invalid model type", name + 'model = 42\n', "inherited", (), "", ""),
        ("invalid effort type", name + 'model_reasoning_effort = 42\n', "inherited", (), "", ""),
        ("empty explicit model", name + 'model = ""\n', "inherited", (), "",
         "resolve the inherited model"),
        ("unknown model", name + 'model = "missing"\n', "inherited", (), "", "missing is absent"),
        ("duplicate canonical keys", name + configured + '"model" = "inherited"\n',
         "inherited", (), "", ""),
        ("duplicate ignored keys", name + 'MODEL = "inherited"\n"MODEL" = "configured"\n',
         "inherited", (), "", ""),
        ("nested tables", name + '[role]\nname = "other"\nmodel = "configured"\n'
         'model_reasoning_effort = "high"\n', "inherited", (), "review: inherited", ""),
        ("nested alias", name + 'MODEL.value = "configured"\n', "inherited", (),
         "review: inherited", ""),
        ("nested canonical key is invalid", name + 'model.value = "configured"\n',
         "inherited", (), "", ""),
        ("literal dotted key is not a table", name + '"model.value" = "configured"\n',
         "inherited", (), "review: inherited", ""),
        ("case alias cannot grant access", name + f'NAME = "{optional}"\nmodel = "optional"\n',
         "inherited", ("--daybreak-selected",), "", "requires the optional defensive role"),
        ("case alias cannot remove opt-in", f'name = "{optional}"\nNAME = "review"\n'
         'model = "optional"\n', "inherited", (), "", "explicitly select"),
        ("canonical optional role opt-in", f'name = "{optional}"\nmodel = "optional"\n',
         "inherited", ("--daybreak-selected",), f"{optional}: optional", ""),
    ]
    for label, source, inherited, extra, expected, error in cases:
        role.write_text(source)
        args = [str(role), "--inherited-model", inherited, "--inherited-effort", "medium", *extra]
        for launcher in (python, go):
            run = subprocess.run([*launcher, *args], cwd=directory, env=env, input=catalog,
                                 text=True, capture_output=True, timeout=10)
            detail = (label, launcher, run)
            if expected:
                assert run.returncode == 0 and not run.stderr, detail
                assert run.stdout == f"{expected} advertised (provider response unverified)\n", detail
            else:
                assert run.returncode == 1 and not run.stdout, detail
                assert run.stderr.startswith("role unavailable: ") and error in run.stderr, detail
            assert role.read_text() == source and not list(home.iterdir()), detail
            assert set(directory.iterdir()) == {home, tools, role} and set(tools.iterdir()) == {codex}, detail
    print(f"Codex role TOML: {len(cases)} Python/Go cases verified", flush=True)


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
        native = root / "nstack-codex"
        subprocess.run(["go", "build", "-o", str(native), "./cmd/nstack-codex"], cwd=ROOT, check=True)
        verify_roles(root)
        verify_roles(root, (str(native), "check-role"))
        print("Codex role preflight fixtures passed on Python and Go", flush=True)
        verify_role_toml(root / "role-toml", native)
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(root),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ALLOW_PROTOCOL": "file",
               "PYTHONUTF8": "1"}
        subprocess.run([sys.executable, "-B", str(ROOT / "tests/review_workflow.py"),
                         "--go-native", "--", str(native), "review"], env=env, check=True)


if __name__ == "__main__":
    main()
