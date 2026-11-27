#!/usr/bin/env python3
"""Deterministic protocol double. It does not authenticate or enforce a sandbox."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


def emit(value):
    print(json.dumps(value), flush=True)


def notify(method, params):
    emit({"method": method, "params": params})


assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
assert 'shell_environment_policy.set.PYTHONDONTWRITEBYTECODE="1"' in sys.argv
scenario = os.environ["NSTACK_REVIEW_TEST_SCENARIO"]
cwd = Path.cwd()
thread = uuid.uuid4().hex
state = None

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method, params = request["method"], request.get("params", {})
    if method == "initialize":
        response = {}
    elif method == "account/read":
        response = {"account": None if scenario == "unauthenticated" else {"type": "chatgpt"}}
    elif method == "config/read":
        response = {"config": {"mcp_servers": {"external": {}}} if scenario == "mcp" else {}}
    elif method == "model/list":
        assert params["modelProvider"] == "openai"
        model = "gpt-6.2-sol" if params["cursor"] is None else "gpt-6.2-astra"
        response = {"data": [] if scenario == "model" and params["cursor"] else [
            {"model": model, "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]}
        ], "nextCursor": "page-2" if params["cursor"] is None else None}
    elif method == "command/exec":
        policy = params["sandboxPolicy"]
        assert policy["networkAccess"] is False
        if policy["type"] == "readOnly":
            response = {"exitCode": 0, "stdout": "write-denied 13\n", "stderr": ""}
            if scenario == "permission":
                Path(params["command"][-1]).touch()
        else:
            assert policy["excludeSlashTmp"] and policy["excludeTmpdirEnvVar"]
            assert params["env"]["TMPDIR"] in policy["writableRoots"]
            env = dict(os.environ)
            env.pop("PYTHONDONTWRITEBYTECODE")
            env.update(params["env"])
            gate = subprocess.run(params["command"], cwd=params["cwd"], env=env,
                                  text=True, capture_output=True)
            response = {"exitCode": gate.returncode, "stdout": gate.stdout, "stderr": gate.stderr}
    elif method == "thread/start":
        state = params
        assert params["cwd"] == str(cwd) and params["ephemeral"] and params["approvalPolicy"] == "never"
        assert params["modelProvider"] == "openai"
        assert params["config"]["model_reasoning_effort"] == "medium"
        sandbox = {"type": "readOnly", "networkAccess": False}
        if state["sandbox"] == "workspace-write":
            sandbox = {"type": "workspaceWrite", "networkAccess": False, "writableRoots": [str(cwd)],
                       "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}
        response = {
            "thread": {"id": thread, "sessionId": thread, "forkedFromId": None,
                       "parentThreadId": None, "ephemeral": True},
            "cwd": str(cwd), "model": state["model"], "modelProvider": "openai",
            "reasoningEffort": "medium", "approvalPolicy": "never", "sandbox": sandbox,
        }
        if scenario == "wrong-policy" and state["sandbox"] == "read-only":
            response["sandbox"]["type"] = "workspaceWrite"
    elif method == "turn/start":
        emit({"id": request["id"], "result": {"turn": {"id": "turn"}}})
        context = {"threadId": thread, "turnId": "turn"}
        prompt = params["input"][0]["text"]
        target = cwd / "result.txt"
        schema = params["outputSchema"]
        if schema is None:
            assert state["model"] == "gpt-6.2-sol" and state["sandbox"] == "workspace-write"
            subprocess.run([sys.executable, "-c", "import seed; assert seed.VALUE == 'base'"],
                           check=True)
            if "Fix demonstrated findings" in prompt:
                assert "incorrect output" in prompt
                target.write_text("correct\n")
            else:
                target.write_text("incorrect\n")
            message = "implementation transcript marker"
        else:
            assert state["model"] == "gpt-6.2-astra" and state["sandbox"] == "read-only"
            assert "implementation transcript marker" not in prompt
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()
            assert sha in prompt and re.fullmatch("[0-9a-f]{40}", sha)
            findings = []
            if target.read_text() != "correct\n" or scenario == "repeat":
                findings = [{"location": "result.txt", "evidence": "incorrect output",
                             "expected": "correct output", "impact": "wrong user-facing result"}]
            if scenario == "reroute":
                notify("model/rerouted", {**context, "toModel": "another-model"})
            message = json.dumps({"candidate": "0" * 40 if scenario == "sha" else sha,
                                  "verdict": "changes_requested" if findings else "pass",
                                  "findings": findings})
        notify("item/completed", {**context, "item": {"type": "agentMessage", "text": message}})
        notify("thread/tokenUsage/updated", {**context, "tokenUsage": {"total": {"inputTokens": 10}}})
        notify("turn/completed", {**context, "turn": {"id": "turn", "status": "completed", "error": None}})
        continue
    else:
        raise AssertionError(method)
    emit({"id": request["id"], "result": response})
