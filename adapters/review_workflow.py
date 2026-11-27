"""Host-side state transitions for a single implementation and review task."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import re
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
import uuid
from typing import Protocol


@dataclass(frozen=True)
class Role:
    name: str
    model: str
    effort: str


class ReviewAdapter(Protocol):
    name: str

    def preflight(self, cwd: Path, roles: tuple[Role, ...], evidence: Path) -> dict: ...
    def gate(self, cwd: Path, argv: list[str], scratch: Path, evidence: Path) -> dict: ...
    def run(self, cwd: Path, role: Role, prompt: str, evidence: Path, *,
            schema: dict | None = None) -> dict: ...


FINDING_FIELDS = ("location", "evidence", "expected", "impact")
VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate", "verdict", "findings"],
    "properties": {
        "candidate": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "changes_requested", "blocked"]},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": list(FINDING_FIELDS),
            "properties": {field: {"type": "string"} for field in FINDING_FIELDS},
        }},
    },
}


def verdict(text, candidate):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {"candidate", "verdict", "findings"}:
        raise ValueError("invalid structured review result")
    status = value["verdict"]
    findings = value["findings"]
    if (value["candidate"] != candidate or status not in ("pass", "changes_requested", "blocked")
            or not isinstance(findings, list) or (status == "pass") != (not findings)):
        raise ValueError("review verdict does not match the candidate or findings")
    for finding in findings:
        if (not isinstance(finding, dict) or set(finding) != set(FINDING_FIELDS)
                or any(not isinstance(detail, str) or not detail.strip() for detail in finding.values())):
            raise ValueError("incomplete independent review finding")
    return value


def git(cwd, *argv, config=()):
    return subprocess.run(
        ["git", "-C", str(cwd), *config, *argv],
        text=True, capture_output=True, check=True,
    ).stdout.strip()


def head(cwd):
    return git(cwd, "rev-parse", "HEAD")


def clean_at(cwd, sha):
    entries = git(cwd, "ls-files", "-v", "-z").split("\0")
    if any(entry and (entry[0].islower() or entry[0] == "S") for entry in entries):
        raise ValueError(f"checkout has index flags that can hide tracked changes: {cwd}")
    if head(cwd) != sha or git(cwd, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError(f"dirty checkout or changed candidate: {cwd}")


@contextmanager
def exclusive_checkout(repo):
    path = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-path", "nstack-review.lock"))
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another nstack review workflow owns this checkout") from None
        yield


def checkout(repo, destination, sha):
    git(repo, "clone", "--quiet", "--no-local", "--no-checkout", "--", str(repo), str(destination))
    git(destination, "checkout", "--quiet", "--detach", sha)
    clean_at(destination, sha)


def write_json(path, value):
    with path.open("x") as target:
        json.dump(value, target, ensure_ascii=False, indent=2)
        target.write("\n")


def remote_urls(repo, name, direction, config):
    prefix = f"{name}\t"
    suffix = f" ({direction})"
    return [line[len(prefix):-len(suffix)]
            for line in git(repo, "remote", "-v", config=config).splitlines()
            if line.startswith(prefix) and line.endswith(suffix)]


def delivery_target(args, repo):
    # Let Git apply its push URL resolution, even for a literal argument.
    name = f"nstack-delivery-{uuid.uuid4().hex}"
    known = args.push in git(repo, "remote").splitlines()
    source = args.push if known else name
    config = () if known else ("-c", f"remote.{name}.url={args.push}")
    targets = remote_urls(repo, source, "push", config)
    if len(targets) != 1 or not targets[0]:
        raise ValueError("delivery requires exactly one push destination")
    target = targets[0]
    github_repo = None
    if args.github_repo:
        github = re.fullmatch(
            r"(?:https://github[.]com/|git@github[.]com:|ssh://git@github[.]com/)"
            r"([a-z0-9-]+/[a-z0-9_.-]+)", target, re.IGNORECASE,
        )
        if not github or github[1].removesuffix(".git").casefold() != args.github_repo.casefold():
            raise ValueError("GitHub PR repository must match the Git push destination")
        github_repo = f"github.com/{github[1].removesuffix('.git')}"

    # An explicit pushurl prevents a second pushInsteadOf rewrite. Reject a
    # second insteadOf rewrite on either operation before contacting the remote.
    config = ("-c", f"remote.{name}.url={target}", "-c", f"remote.{name}.pushurl={target}")
    for direction in ("fetch", "push"):
        urls = remote_urls(repo, name, direction, config)
        if urls != [target]:
            raise ValueError("Git would rewrite the pinned delivery destination")
    return name, config, github_repo


def default_branch(repo, reply):
    heads = [line.split("\t") for line in reply.splitlines() if line.endswith("\tHEAD")]
    symbolic = [fields[0][5:] for fields in heads
                if len(fields) == 2 and fields[0].startswith("ref: ")]
    hashes = [fields[0] for fields in heads
              if len(fields) == 2 and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", fields[0])]
    if len(heads) != 2 or len(symbolic) != 1 or len(hashes) != 1 or not symbolic[0].startswith("refs/heads/"):
        raise ValueError("cannot verify a non-default remote branch")
    git(repo, "check-ref-format", symbolic[0])
    return symbolic[0]


def verify_pr_base(repo, base, candidate, actual):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", actual):
        raise ValueError("cannot verify PR base revision")
    try:
        merge_bases = git(repo, "merge-base", "--all", actual, candidate).splitlines()
    except subprocess.CalledProcessError as error:
        raise ValueError("cannot verify PR merge base; fetch the current base branch first") from error
    if merge_bases != [base]:
        raise ValueError("PR diff does not match the reviewed base and candidate")


def github_pr(repo, github_repo, *args):
    return subprocess.run(
        ["gh", "pr", *args, "--repo", github_repo],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


def pr_number(url, github_repo):
    match = re.fullmatch(rf"https://{re.escape(github_repo)}/pull/([1-9][0-9]*)", url, re.IGNORECASE)
    if not match:
        raise ValueError("GitHub returned a PR URL outside the verified repository")
    return int(match[1])


def deliver(args, repo, base, candidate, evidence):
    branch = git(repo, "symbolic-ref", "--short", "HEAD")
    if branch in ("main", "master", "trunk") or branch == args.pr_base:
        raise ValueError("delivery requires an isolated feature branch")
    remote, config, github_repo = delivery_target(args, repo)
    ref = f"refs/heads/{branch}"

    def remote_ref(name):
        fields = git(repo, "ls-remote", "--refs", "--", remote, name, config=config).split()
        if len(fields) != 2 or fields[1] != name:
            raise ValueError(f"cannot verify remote ref {name}")
        return fields[0]

    def check_base():
        if args.pr_base:
            verify_pr_base(repo, base, candidate, remote_ref(f"refs/heads/{args.pr_base}"))

    remote_head = git(repo, "ls-remote", "--symref", "--", remote, "HEAD", config=config)
    if default_branch(repo, remote_head) == ref:
        raise ValueError("cannot verify a non-default remote branch")
    check_base()
    number = None
    if github_repo:
        existing = json.loads(github_pr(repo, github_repo, "list", "--state", "open", "--head", branch,
                                        "--base", args.pr_base, "--json", "number,isCrossRepository"))
        matches = [pr["number"] for pr in existing if not pr["isCrossRepository"]]
        if len(matches) > 1 or any(type(item) is not int or item < 1 for item in matches):
            raise ValueError("cannot identify a unique GitHub PR for the requested branch and base")
        number = matches[0] if matches else None
    check_base()
    clean_at(repo, candidate)
    git(repo, "push", "--no-follow-tags", "--recurse-submodules=no", "--", remote, f"{candidate}:{ref}", config=config)
    if remote_ref(ref) != candidate:
        raise ValueError("remote SHA differs from reviewed candidate")
    delivery = {"candidate": candidate, "base": base, "ref": ref}
    if github_repo:
        check_base()
        if number is None:
            url = github_pr(repo, github_repo, "create", "--draft", "--head", branch,
                            "--base", args.pr_base, "--title", args.pr_title, "--body", "")
            number = pr_number(url, github_repo)
        data = json.loads(github_pr(repo, github_repo, "view", str(number), "--json",
                                    "number,url,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository"))
        if (data["isCrossRepository"] or data["number"] != number
                or pr_number(data["url"], github_repo) != number or data["headRefName"] != branch
                or data["headRefOid"] != candidate or data["baseRefName"] != args.pr_base):
            raise ValueError("PR does not reference the reviewed candidate and requested branches")
        verify_pr_base(repo, base, candidate, data["baseRefOid"])
        delivery["pr"] = data["url"]
    write_json(evidence / "delivery.json", delivery)



class ReviewChangesRequested(ValueError):
    def __init__(self, candidate):
        super().__init__("independent review requested changes in review-only mode")
        self.candidate = candidate


def execute(adapter: ReviewAdapter, args, repo, evidence):
    start = head(repo)
    clean_at(repo, start)
    base = git(repo, "rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}")
    git(repo, "merge-base", "--is-ancestor", base, start)
    if not (args.review_only or args.review_first):
        git(repo, "symbolic-ref", "--short", "HEAD")
    task = args.brief.read_text().strip()
    if not task:
        raise ValueError("task brief is empty")
    writer = Role("nstack_implement", args.implement_model, args.implement_effort)
    reviewer = Role("nstack_review", args.review_model, args.review_effort)
    roles = (reviewer,) if args.review_only else (writer, reviewer)
    initial_roles = (reviewer,) if args.review_first else roles
    write_json(evidence / "request.json", {
        "adapter": adapter.name, "start": start, "base": base, "gate": args.gate,
        "roles": [vars(role) for role in roles],
        "reviewOnly": args.review_only, "reviewFirst": args.review_first,
        "maxRemediations": args.max_remediations,
    })
    probe = adapter.preflight(repo, initial_roles, evidence / "preflight")
    write_json(evidence / "preflight.json", probe)
    last = start
    findings = None
    seen_findings = set()
    sessions = set()
    with TemporaryDirectory(prefix="checkouts-", dir=evidence) as temporary:
        directory = Path(temporary)
        for attempt in range((0 if args.review_only else args.max_remediations) + 1):
            if not args.review_only and (findings is not None or not args.review_first):
                if args.review_first:
                    git(repo, "symbolic-ref", "--short", "HEAD")
                prompt = (
                    f"Implement this task in the current feature checkout. Base: {base}.\n"
                    "Only edit task files. The caller owns Git commits, quality gates, and remote delivery. "
                    "Use no subagents or external services.\n\n"
                    f"Task and acceptance criteria:\n{task}"
                )
                if findings:
                    prompt += f"\n\nFix demonstrated findings for {last}:\n{json.dumps(findings)}"
                result = adapter.run(repo, writer, prompt, evidence / f"{attempt}-implementation")
                sessions.add(result["session"])
                write_json(evidence / f"{attempt}-implementation.json", {"start": last, "base": base, **result})
                if head(repo) != last:
                    raise ValueError("implementation changed HEAD")
                git(repo, "add", "-A")
                if not git(repo, "diff", "--cached", "--name-only"):
                    raise ValueError("implementation made no committable change")
                git(repo, "commit", "-m", "Implement requested change" if not findings
                    else "Address independent review findings")
            candidate = head(repo)
            clean_at(repo, candidate)
            if candidate == base:
                raise ValueError("review candidate has no commits beyond the base")
            gate_checkout = directory / f"{attempt}-gate"
            checkout(repo, gate_checkout, candidate)
            scratch = directory / f"{attempt}-scratch"
            scratch.mkdir()
            gate = adapter.gate(gate_checkout, args.gate, scratch, evidence / f"{attempt}-gate")
            write_json(evidence / f"{attempt}-gate.json", {"candidate": candidate, "base": base, **gate})
            clean_at(gate_checkout, candidate)
            if gate["exitCode"] != 0:
                raise ValueError("candidate quality gate failed")

            review_checkout = directory / f"{attempt}-review"
            checkout(repo, review_checkout, candidate)
            prompt = (
                f"Independently review exactly candidate {candidate} against base {base}. Verify HEAD. "
                "Inspect the diff and actual behavior where possible in this read-only checkout. "
                "Use no subagents or external services. The caller already ran the quality gate. "
                "Return the full candidate SHA and a structured verdict. Use changes_requested only "
                "for demonstrated acceptance defects; include location, evidence (actual behavior and "
                "reproduction if feasible), expected behavior and impact for each. Use blocked for "
                "insufficient evidence or required contract decisions; use pass when the contract holds.\n\n"
                f"Task and acceptance criteria:\n{task}"
            )
            result = adapter.run(review_checkout, reviewer, prompt, evidence / f"{attempt}-review",
                                 schema=VERDICT_SCHEMA)
            clean_at(review_checkout, candidate)
            clean_at(repo, candidate)
            if result["session"] in sessions:
                raise ValueError("review reused an existing context")
            sessions.add(result["session"])
            review = verdict(result["message"], candidate)
            write_json(evidence / f"{attempt}-review.json",
                       {"candidate": candidate, "base": base, **result, "review": review})
            if review["verdict"] == "pass":
                if args.push:
                    deliver(args, repo, base, candidate, evidence)
                return candidate
            if review["verdict"] == "blocked":
                raise ValueError("independent review blocked this candidate")
            if args.review_only:
                raise ReviewChangesRequested(candidate)
            findings = review["findings"]
            signature = frozenset(tuple(item[field] for field in FINDING_FIELDS) for item in findings)
            if signature in seen_findings:
                raise ValueError("same independent findings repeated after remediation")
            seen_findings.add(signature)
            last = candidate
    raise ValueError("independent review remediation budget exhausted")


def main(adapter_factory):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-host", action="store_true", required=True,
                        help="Authorize this invocation on the host under its effective policies")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True, help="Candidate comparison revision")
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True, help="New directory outside checkout")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--review-only", action="store_true")
    mode.add_argument("--review-first", action="store_true",
                      help="Review HEAD before enabling bounded remediation for demonstrated defects")
    parser.add_argument("--implement-model", default="gpt-6.2-sol")
    parser.add_argument("--implement-effort", default="medium")
    parser.add_argument("--review-model", default="gpt-6.2-astra")
    parser.add_argument("--review-effort", default="medium")
    parser.add_argument("--max-remediations", type=int, choices=range(3), default=2)
    parser.add_argument("--timeout", type=int, default=600, help="Maximum seconds per Codex process")
    parser.add_argument("--push", metavar="REMOTE", help="Normal push of the reviewed feature branch")
    parser.add_argument("--github-repo", help="Explicit OWNER/REPO for draft PR creation")
    parser.add_argument("--pr-base")
    parser.add_argument("--pr-title")
    parser.add_argument("gate", nargs="+", help="Mandatory gate argv, after --")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    pr = (args.github_repo, args.pr_base, args.pr_title)
    if any(pr) and (not all(pr) or not args.push):
        parser.error("draft PR requires --push, --github-repo, --pr-base and --pr-title")
    elapsed = time.monotonic()
    repo = args.repo.resolve()
    evidence = args.evidence.resolve()
    if evidence.is_relative_to(repo):
        parser.error("evidence directory must be outside the checkout")
    try:
        if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
            raise ValueError("repo must be the checkout root")
        evidence.mkdir(mode=0o700)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    try:
        with exclusive_checkout(repo):
            candidate = execute(adapter_factory(args.timeout), args, repo, evidence)
    except ReviewChangesRequested as error:
        write_json(evidence / "status.json", {"status": "changes_requested", "candidate": error.candidate,
                                             "error": str(error), "elapsedSeconds": time.monotonic() - elapsed})
        parser.exit(1, f"{error} (evidence: {evidence})\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        write_json(evidence / "status.json", {"status": "blocked", "error": str(error),
                                             "elapsedSeconds": time.monotonic() - elapsed})
        parser.exit(1, f"workflow blocked: {error} (evidence: {evidence})\n")
    write_json(evidence / "status.json", {"status": "pass", "candidate": candidate,
                                         "elapsedSeconds": time.monotonic() - elapsed})
    print(f"review passed for {candidate} (evidence: {evidence})")
