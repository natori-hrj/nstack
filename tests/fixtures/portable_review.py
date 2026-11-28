"""Drive the Python workflow with a deterministic, harness-independent adapter."""
from pathlib import Path
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "adapters"))
from review_workflow import main


class FixtureAdapter:
    name = "portable-fixture"

    def __init__(self, timeout):
        self.timeout = timeout
        self.scenario = os.environ["NSTACK_CONTRACT_SCENARIO"]

    def preflight(self, cwd, roles, evidence):
        if self.scenario == "missing-capability":
            raise ValueError("fixture: required read-only capability unavailable")
        return {"roles": [role.name for role in roles]}

    def gate(self, cwd, argv, scratch, evidence):
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                   timeout=self.timeout, env={**os.environ, "TMPDIR": str(scratch)})
        return {"exitCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}

    def run(self, cwd, role, prompt, evidence, *, schema=None):
        if role.name == "nstack_implement" and self.scenario == "implementation":
            (cwd / "value.txt").write_text("implemented\n")
            return {"session": "portable-implementation", "model": role.model, "effort": role.effort,
                    "message": "Updated the fixture value."}
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, text=True,
        ).strip()
        if self.scenario == "wrong-sha":
            candidate = "0" * len(candidate)
        findings = []
        if self.scenario == "changes-requested":
            findings.append({"location": "value.txt:1", "evidence": "fixture finding",
                             "expected": "correct value", "impact": "fixture mismatch"})
        result = {"candidate": candidate, "verdict": "changes_requested" if findings else "pass",
                  "findings": findings}
        if schema is not None and "previous" in schema["required"]:
            result["previous"] = []
        return {"session": "portable-review", "model": role.model, "effort": role.effort,
                "message": json.dumps(result)}


if __name__ == "__main__":
    main(FixtureAdapter)
