"""Check an installed Codex role against a current model/list result on stdin."""
import argparse
import json
from pathlib import Path
import sys
import tomllib


OPTIONAL = "nstack_security_daybreak"


def check(role, models, daybreak_selected, inherited_model, inherited_effort):
    name = role["name"]
    model = role.get("model", inherited_model)
    effort = role.get("model_reasoning_effort", inherited_effort)
    if not model:
        raise ValueError("resolve the inherited model in the active session before dispatch")
    if name == OPTIONAL and not daybreak_selected:
        raise ValueError("explicitly select the Daybreak route for an authorized defensive task")

    entry = next((entry for entry in models if entry["model"] == model), None)
    if entry is None:
        raise ValueError(f"{model} is absent from the active model catalog")
    if name == OPTIONAL or entry.get("modelSpecialty") == "cyber":
        if name != OPTIONAL:
            raise ValueError(f"{model} requires the optional defensive role")
        programs = entry.get("availableAccessPrograms") or {}
        if "daybreakBlue" not in (programs.get("cyber") or []):
            raise ValueError(f"{model} does not advertise Daybreak Blue for this account and client")
    elif entry.get("hidden"):
        raise ValueError(f"{model} is hidden in the active model catalog")
    supported = {option["reasoningEffort"] for option in entry["supportedReasoningEfforts"]}
    if effort and effort not in supported:
        raise ValueError(f"{model} does not advertise reasoning effort {effort}")
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", type=Path)
    parser.add_argument("--daybreak-selected", action="store_true")
    parser.add_argument("--inherited-model", help="Effective session model when omitted in TOML")
    parser.add_argument("--inherited-effort", help="Effective session effort when omitted in TOML")
    args = parser.parse_args()
    try:
        with args.role.open("rb") as source:
            role = tomllib.load(source)
        catalog = json.load(sys.stdin)
        result = catalog.get("result", catalog)
        if result.get("nextCursor"):
            raise ValueError("collect all model/list pages before checking a role")
        model = check(role, result["data"], args.daybreak_selected,
                      args.inherited_model, args.inherited_effort)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"role unavailable: {error}\n")
    print(f'{role["name"]}: {model} advertised (provider response unverified)')


if __name__ == "__main__":
    main()
