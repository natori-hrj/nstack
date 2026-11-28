#!/usr/bin/env python3
"""Local-only Git and GitHub CLI doubles for the PR delivery matrix."""
import json
import os
from pathlib import Path
import subprocess
import sys

TARGET = "https://github.com/fixture/project"
PR_URL = TARGET + "/pull/42"
REMOTE = os.environ["NSTACK_FIXTURE_REMOTE"]
GIT = os.environ["NSTACK_FIXTURE_GIT"]


def git(argv):
    # Keep the logical destination for remote -v validation. Only network
    # operations against that logical destination are redirected.
    if "ls-remote" in argv or "push" in argv:
        argv = [
            value.removesuffix(TARGET) + REMOTE
            if value.startswith("remote.nstack-delivery-") and value.endswith("=" + TARGET)
            else value
            for value in argv
        ]
    os.execv(GIT, [GIT, *argv])


def gh(argv):
    assert argv[:1] == ["pr"] and argv[-2:] == ["--repo", "github.com/fixture/project"], argv
    action, args = argv[1], argv[2:-2]
    scenario = os.environ["NSTACK_FIXTURE_PR_CASE"]
    state = Path(os.environ["NSTACK_FIXTURE_PR_STATE"])
    created, viewed = state / "created", state / "viewed"
    existing = scenario not in {"new", "post-push-failure"}
    if action == "list":
        assert args == ["--state", "open", "--head", "feature", "--limit", "100",
                        "--json", "number,isCrossRepository"], args
        rows = [{"number": 42, "isCrossRepository": False}] if existing or created.exists() else []
        if scenario in {"ambiguous", "explicit-ambiguous"}:
            rows.append({"number": 43, "isCrossRepository": False})
        rows.append({"number": 90, "isCrossRepository": True})
        print(json.dumps(rows))
        return
    if action == "create":
        assert not existing and not created.exists()
        assert args == ["--draft", "--head", "feature", "--base", "main",
                        "--title", "Fixture", "--body", ""], args
        if scenario == "post-push-failure":
            raise SystemExit(1)
        created.touch(exist_ok=False)
        print(PR_URL)
        return
    assert action == "view" and args[:2] == ["42", "--json"], argv
    tip = subprocess.check_output([GIT, "-C", REMOTE, "rev-parse", "refs/heads/feature"], text=True).strip()
    if scenario == "remote-moved" and not viewed.exists():
        subprocess.run([GIT, "-C", REMOTE, "update-ref", "refs/heads/feature",
                        os.environ["NSTACK_FIXTURE_CANDIDATE"], tip], check=True)
    viewed.touch()
    print(json.dumps({
        "number": 42, "url": PR_URL, "state": "OPEN", "isCrossRepository": False,
        "headRefName": "wrong" if scenario == "wrong-ref" else "feature", "headRefOid": tip,
        "baseRefName": "main",
        "baseRefOid": os.environ["NSTACK_FIXTURE_CANDIDATE" if scenario == "wrong-base" else "NSTACK_FIXTURE_BASE"],
    }))


if __name__ == "__main__":
    {"git": git, "gh": gh}[Path(sys.argv[0]).name](sys.argv[1:])
