"""Expose the existing Python fixture behavior to the Go test launcher."""
import filecmp
import json
import os
from pathlib import Path
import shutil
import signal
import sys

from portable_review import FixtureAdapter
from review_workflow import Role


def run():
    profile, operation, timeout = sys.argv[1:]
    timeout_seconds = int(timeout)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    request = json.load(sys.stdin)
    directory, evidence = Path(request["Directory"]), Path(request["Evidence"])
    if profile == "portable":
        adapter = FixtureAdapter(timeout_seconds)
    elif profile == "protocol":
        fake = Path(__file__).with_name("review_app_server.py")
        executable = shutil.which("codex")
        if not executable or not os.environ.get("NSTACK_REVIEW_TEST_SCENARIO") or not filecmp.cmp(
            fake, executable, shallow=False
        ):
            raise ValueError("protocol bridge requires the offline executable fixture")
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "adapters" / "codex"))
        from review_adapter import CodexAdapter

        adapter = CodexAdapter(timeout_seconds)
    else:
        raise ValueError("unknown fixture profile")
    if operation == "preflight":
        return adapter.preflight(directory, (Role(**request["Role"]),), evidence)
    if operation == "gate":
        return adapter.gate(directory, request["Argv"], Path(request["Scratch"]), evidence)
    if operation == "run":
        return adapter.run(directory, Role(**request["Role"]), request["Prompt"], evidence,
                           schema=request["Schema"])
    raise ValueError("unknown fixture operation")


def interrupt(signum, _frame):
    # Unwind the existing adapter's finally block before leaving the bridge.
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    try:
        print(json.dumps({"result": run()}))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}))
