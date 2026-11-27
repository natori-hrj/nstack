"""Codex 0.172 app-server adapter for the host review workflow."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import uuid

from check_role import check


DISABLED_FEATURES = ("apps", "plugins", "hooks", "memories", "multi_agent", "multi_agent_v2")


def enabled_mcp(config):
    return [name for name, settings in (config["mcp_servers"] or {}).items()
            if settings.get("enabled", True)]


def verify_config(config):
    if enabled_mcp(config):
        raise ValueError("Codex orchestration MCP overrides did not take effect")
    if (any(config["features"].get(flag) is not False for flag in DISABLED_FEATURES)
            or config["web_search"] != "disabled"):
        raise ValueError("Codex orchestration feature overrides did not take effect")


class AppServer:
    def __init__(self, process, timeout):
        self.process = process
        self.deadline = time.monotonic() + timeout
        self.request_id = 0
        self.buffer = b""

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def receive(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("Codex app-server timed out")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError("Codex app-server stopped; see the private stderr log")
                self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        message = json.loads(line)
        if message.get("method") == "model/rerouted":
            raise ValueError("Codex reported a model reroute")
        if "method" in message and "id" in message:
            raise ValueError(f"unsupported Codex server request: {message['method']}")
        if message.get("method") == "error":
            raise ValueError("Codex reported a turn error")
        return message

    def request(self, method, params, observe=lambda message: None):
        self.request_id += 1
        requested = self.request_id
        self.send({"id": requested, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("id") == requested:
                if "error" in message:
                    raise ValueError(f"Codex {method} failed: {message['error'].get('message')}")
                return message["result"]
            observe(message)


class CodexAdapter:
    name = "codex-app-server"

    def __init__(self, timeout):
        self.timeout = timeout

    @contextmanager
    def connection(self, cwd, evidence, overrides=()):
        command = ["codex", "app-server"]
        for flag in DISABLED_FEATURES:
            command.extend(("--disable", flag))
        command.extend((
            "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
            "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
            "-c", "sandbox_workspace_write.network_access=false",
            "-c", 'shell_environment_policy.set.PYTHONDONTWRITEBYTECODE="1"',
            "-c", 'web_search="disabled"',
        ))
        command.extend(overrides)
        with evidence.with_suffix(".stderr").open("xb") as errors:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=errors,
                                       start_new_session=True)
            try:
                server = AppServer(process, self.timeout)
                server.request("initialize", {"clientInfo": {"name": "nstack-review", "version": "0.3.0"}})
                server.send({"method": "initialized"})
                yield server
            finally:
                # Kill the private subprocess group, including any unfinished local commands.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdin.close()
                process.stdout.close()

    @contextmanager
    def isolated(self, cwd, evidence):
        # Discovery does not start a thread, execute tools, or load MCP sessions.
        with self.connection(cwd, evidence.with_name(evidence.name + "-config")) as server:
            config = server.request("config/read", {"cwd": str(cwd)})["config"]
            names = enabled_mcp(config)
            if not names:
                verify_config(config)
                yield server, 0
                return

        # An inline table preserves literal names (including dots) across TOML layers.
        entries = ", ".join(f"{json.dumps(name, ensure_ascii=False)} = {{ enabled = false }}"
                            for name in sorted(names))
        with self.connection(cwd, evidence, ("-c", f"mcp_servers={{ {entries} }}")) as server:
            verify_config(server.request("config/read", {"cwd": str(cwd)})["config"])
            yield server, len(names)

    @contextmanager
    def server(self, cwd, evidence):
        with self.isolated(cwd, evidence) as (server, disabled_count):
            account = server.request("account/read", {"refreshToken": False})
            if not account.get("account"):
                raise ValueError("Codex has no authenticated account; use normal Codex login on the host")
            yield server, disabled_count

    def catalog(self, server):
        cursor = None
        entries = []
        while True:
            page = server.request("model/list", {"modelProvider": "openai", "cursor": cursor})
            entries.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                return entries

    def check_roles(self, server, roles):
        catalog = self.catalog(server)
        for role in roles:
            check({"name": role.name, "model": role.model,
                   "model_reasoning_effort": role.effort}, catalog, False, None, None)

    def command(self, server, cwd, argv, policy, *, env=None):
        return server.request("command/exec", {
            "cwd": str(cwd), "command": list(argv), "sandboxPolicy": policy,
            "env": env, "timeoutMs": self.timeout * 1000, "outputBytesCap": 100000,
        })

    def probe_read_only(self, server, cwd, policy):
        path = cwd / f".nstack-write-probe-{uuid.uuid4().hex}"
        script = (
            "import errno, sys\n"
            "try:\n"
            "    open(sys.argv[1], 'x').close()\n"
            "except OSError as error:\n"
            "    if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS):\n"
            "        print('write-denied', error.errno)\n"
            "    else:\n"
            "        raise\n"
        )
        result = self.command(server, cwd, (sys.executable, "-c", script, str(path)), policy)
        if path.exists():
            path.unlink()
            raise ValueError("review sandbox permitted writing in the candidate checkout")
        expected = {f"write-denied {code}" for code in (errno.EACCES, errno.EPERM, errno.EROFS)}
        if result["exitCode"] != 0 or result["stdout"].strip() not in expected:
            raise ValueError(f"could not verify review sandbox write denial: {result['stderr'].strip()}")
        return result["stdout"].strip()

    def preflight(self, cwd, roles, evidence):
        with self.server(cwd, evidence) as (server, disabled_count):
            self.check_roles(server, roles)
            states = [self.start_thread(server, cwd, role, role.name == "nstack_review")
                      for role in roles]
            review = states[-1]["sandbox"]
            denial = self.probe_read_only(server, cwd, review)
            with TemporaryDirectory(prefix="gate-probe-", dir=evidence.parent) as temporary:
                scratch = Path(temporary)
                target = scratch / "write-probe"
                probe = self.gate_command(server, cwd, (
                    sys.executable, "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                    str(target),
                ), scratch)
                if probe["exitCode"] != 0 or not target.is_file():
                    raise ValueError(f"could not verify quality gate scratch writes: {probe['stderr'].strip()}")
            return {"disabledMcpServers": disabled_count, "writeProbe": denial,
                    "gateScratchWrite": True,
                    "roles": [{"model": state["model"], "effort": state["reasoningEffort"],
                               "sandbox": state["sandbox"]["type"]} for state in states]}

    def gate_command(self, server, cwd, argv, scratch):
        policy = {"type": "workspaceWrite", "writableRoots": [str(cwd), str(scratch)],
                  "networkAccess": False, "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}
        return self.command(server, cwd, argv, policy, env={
            "TMPDIR": str(scratch), "PYTHONDONTWRITEBYTECODE": "1",
        })

    def gate(self, cwd, argv, scratch, evidence):
        with self.server(cwd, evidence) as (server, _):
            return self.gate_command(server, cwd, argv, scratch)

    def start_thread(self, server, cwd, role, review):
        mode = "read-only" if review else "workspace-write"
        state = server.request("thread/start", {
            "cwd": str(cwd), "model": role.model, "modelProvider": "openai",
            "config": {"model_reasoning_effort": role.effort},
            "approvalPolicy": "never", "sandbox": mode, "ephemeral": True,
        })
        thread = state["thread"]
        policy = state["sandbox"]
        if (state["model"] != role.model or state["reasoningEffort"] != role.effort
                or state["modelProvider"] != "openai" or state["approvalPolicy"] != "never"
                or Path(state["cwd"]).resolve() != cwd or thread["parentThreadId"]
                or thread["forkedFromId"] or not thread["ephemeral"]):
            raise ValueError("Codex returned unexpected model, context, or approval settings")
        if policy["type"] != ("readOnly" if review else "workspaceWrite") or policy["networkAccess"]:
            raise ValueError("Codex returned an unexpected sandbox policy")
        if not review:
            roots = {Path(root).resolve() for root in policy["writableRoots"]}
            if roots - {cwd} or not policy["excludeTmpdirEnvVar"] or not policy["excludeSlashTmp"]:
                raise ValueError("Codex implementation sandbox permits extra writable roots")
        return state

    def run(self, cwd, role, prompt, evidence, *, schema=None):
        review = schema is not None
        with self.server(cwd, evidence) as (server, _):
            self.check_roles(server, (role,))
            state = self.start_thread(server, cwd, role, review)
            thread = state["thread"]
            thread_id = thread["id"]
            policy = state["sandbox"]
            denial = self.probe_read_only(server, cwd, policy) if review else None

            events = []
            turn = server.request("turn/start", {
                "threadId": thread_id, "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "outputSchema": schema,
            }, observe=events.append)["turn"]["id"]
            message = None
            usage = None
            while True:
                event = events.pop(0) if events else server.receive()
                params = event.get("params", {})
                if params.get("threadId") != thread_id:
                    continue
                method = event.get("method")
                if method == "turn/completed" and params["turn"]["id"] == turn:
                    if params["turn"]["status"] != "completed" or params["turn"]["error"]:
                        raise ValueError("Codex did not complete the turn")
                    break
                if params.get("turnId") != turn:
                    continue
                if method == "item/completed":
                    item = params["item"]
                    if item["type"] == "agentMessage" and item.get("phase") != "commentary":
                        message = item["text"]
                    if item["type"] in ("mcpToolCall", "collabAgentToolCall"):
                        raise ValueError("unexpected Codex tool outside this workflow")
                if method == "thread/tokenUsage/updated":
                    usage = params["tokenUsage"]["total"]
            if not message:
                raise ValueError("Codex completed without a final message")
            return {"model": state["model"], "effort": state["reasoningEffort"],
                    "thread": thread_id, "session": thread["sessionId"], "turn": turn,
                    "sandbox": policy, "writeProbe": denial, "usage": usage, "message": message}
