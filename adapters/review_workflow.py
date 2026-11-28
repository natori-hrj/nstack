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


TRACKED_VERDICT_SCHEMA = {
    **VERDICT_SCHEMA,
    "required": [*VERDICT_SCHEMA["required"], "previous"],
    "properties": {
        **VERDICT_SCHEMA["properties"],
        "previous": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "status", "evidence"],
            "properties": {"id": {"type": "string"}, "evidence": {"type": "string"},
                           "status": {"type": "string", "enum": ["resolved", "recurring", "uncertain"]}},
        }},
    },
}


def verdict(text, candidate, registry=None):
    value = json.loads(text)
    fields = {"candidate", "verdict", "findings"}
    if registry is not None:
        fields.add("previous")
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid structured review result")
    status = value["verdict"]
    findings = value["findings"]
    if (value["candidate"] != candidate or status not in ("pass", "changes_requested", "blocked")
            or not isinstance(findings, list)):
        raise ValueError("review verdict does not match the candidate or findings")
    for finding in findings:
        if (not isinstance(finding, dict) or set(finding) != set(FINDING_FIELDS)
                or any(not isinstance(detail, str) or not detail.strip() for detail in finding.values())):
            raise ValueError("incomplete independent review finding")
    if registry is None:
        if (status == "pass") != (not findings):
            raise ValueError("review verdict does not match the findings")
    else:
        previous = value["previous"]
        seen = set()
        if not isinstance(previous, list):
            raise ValueError("review did not assess previous finding IDs")
        for item in previous:
            if (not isinstance(item, dict) or set(item) != {"id", "status", "evidence"}
                    or not isinstance(item["id"], str) or item["id"] not in registry or item["id"] in seen
                    or item["status"] not in ("resolved", "recurring", "uncertain")
                    or not isinstance(item["evidence"], str) or not item["evidence"].strip()):
                raise ValueError("invalid or unexpected previous finding assessment")
            seen.add(item["id"])
        if seen != registry.keys():
            raise ValueError("review did not assess every previous finding ID")
        outstanding = findings or any(item["status"] != "resolved" for item in previous)
        if status != "blocked" and (status == "pass") != (not outstanding):
            raise ValueError("review verdict does not match the finding assessments")
    return value


def git(cwd, *argv, config=()):
    return subprocess.run(
        ["git", "-C", str(cwd), *config, *argv],
        text=True, capture_output=True, check=True,
    ).stdout.strip()


def head(cwd):
    return git(cwd, "rev-parse", "HEAD")


def check_index(cwd):
    entries = git(cwd, "ls-files", "-v", "-z").split("\0")
    if any(entry and (entry[0].islower() or entry[0] == "S") for entry in entries):
        raise ValueError(f"checkout has index flags that can hide tracked changes: {cwd}")


def clean_at(cwd, sha):
    check_index(cwd)
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


def delivery_target(args, repo, name):
    # Let Git apply its push URL resolution, even for a literal argument.
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
    return config, github_repo


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


def branch_ref(repo, ref):
    if not ref or not ref.startswith("refs/heads/"):
        raise ValueError("authorization requires an explicit refs/heads/ branch")
    git(repo, "check-ref-format", ref)
    return ref


def current_ref(repo):
    result = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--quiet", "HEAD"],
                            capture_output=True, text=True)
    if result.returncode == 1:
        return None
    result.check_returncode()
    return result.stdout.strip()


def check_work(repo, ref, sha, original, start):
    if current_ref(repo) != ref or head(repo) != sha:
        raise ValueError("authorized work ref or candidate changed")
    if original and git(repo, "rev-parse", "--verify", original) != start:
        raise ValueError("original ref changed")
    check_index(repo)


class Delivery:
    def __init__(self, args, repo, base, start, *, writer_required):
        self.repo, self.args, self.base = repo, args, base
        self.ref = branch_ref(repo, args.delivery_ref)
        self.pr_base_ref = f"refs/heads/{args.pr_base}" if args.pr_base else None
        self.remote = f"nstack-delivery-{uuid.uuid4().hex}"
        self.config, self.github = delivery_target(args, repo, self.remote)
        self.default = self.remote_default()
        self.remote_start = self.remote_ref(self.ref)
        if writer_required and self.remote_start is not None and self.remote_start != start:
            raise ValueError("delivery ref does not match the starting candidate")
        self.number = args.pr_number
        if self.github and self.number is None:
            self.number = self.open_pr_number()
        self.check(start)

    @property
    def branch(self):
        return self.ref.removeprefix("refs/heads/")

    def remote_ref(self, name):
        reply = git(self.repo, "ls-remote", "--refs", "--", self.remote, name, config=self.config)
        # ls-remote patterns also match ref names with the same tail.
        matches = [line.split("\t") for line in reply.splitlines() if line.endswith(f"\t{name}")]
        if not matches:
            return None
        if (len(matches) != 1 or len(matches[0]) != 2
                or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", matches[0][0])):
            raise ValueError(f"cannot verify remote ref {name}")
        return matches[0][0]

    def remote_default(self):
        if self.ref in ("refs/heads/main", "refs/heads/master", "refs/heads/trunk"):
            raise ValueError("delivery requires an isolated feature branch")
        reply = git(self.repo, "ls-remote", "--symref", "--", self.remote, "HEAD", config=self.config)
        default = default_branch(self.repo, reply)
        if self.ref in (default, self.pr_base_ref):
            raise ValueError("delivery ref is the remote default or PR base branch")
        return default

    def open_pr_number(self):
        limit = 100
        # Updating the head ref updates every same-repository PR using it, across all bases.
        prs = json.loads(github_pr(
            self.repo, self.github, "list", "--state", "open", "--head", self.branch,
            "--limit", str(limit), "--json", "number,isCrossRepository",
        ))
        if not isinstance(prs, list) or len(prs) >= limit:
            raise ValueError("cannot verify the complete list of open PRs for the delivery branch")
        matches = [pr["number"] for pr in prs if not pr["isCrossRepository"]]
        if len(matches) > 1 or any(type(number) is not int or number < 1 for number in matches):
            raise ValueError("cannot identify a unique open PR for the delivery branch")
        return matches[0] if matches else None

    def check_pr(self, expected_head, candidate):
        data = json.loads(github_pr(
            self.repo, self.github, "view", str(self.number), "--json",
            "number,url,state,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository",
        ))
        if (data["state"] != "OPEN" or data["isCrossRepository"] or data["number"] != self.number
                or pr_number(data["url"], self.github) != self.number or data["headRefName"] != self.branch
                or data["headRefOid"] != expected_head or data["baseRefName"] != self.args.pr_base):
            raise ValueError("PR does not reference the authorized branches and expected head")
        verify_pr_base(self.repo, self.base, candidate, data["baseRefOid"])
        return data["url"]

    def check(self, candidate):
        if delivery_target(self.args, self.repo, self.remote) != (self.config, self.github):
            raise ValueError("effective delivery destination changed")
        if self.remote_default() != self.default or self.remote_ref(self.ref) != self.remote_start:
            raise ValueError("remote default branch or delivery candidate changed")
        if self.remote_start is not None:
            git(self.repo, "merge-base", "--is-ancestor", self.remote_start, candidate)
        if self.pr_base_ref:
            base_tip = self.remote_ref(self.pr_base_ref)
            if base_tip is None:
                raise ValueError("cannot verify remote PR base")
            verify_pr_base(self.repo, self.base, candidate, base_tip)
        if self.github and self.open_pr_number() != self.number:
            raise ValueError("open PR for the delivery branch does not match the authorized PR")
        if self.number is not None:
            if self.remote_start is None:
                raise ValueError("existing PR requires an existing delivery ref")
            self.check_pr(self.remote_start, candidate)

    def push(self, candidate, evidence):
        self.check(candidate)
        clean_at(self.repo, candidate)
        git(self.repo, "push", "--no-follow-tags", "--recurse-submodules=no", "--", self.remote,
            f"{candidate}:{self.ref}", config=self.config)
        if self.remote_ref(self.ref) != candidate:
            raise ValueError("remote SHA differs from reviewed candidate")
        result = {"candidate": candidate, "base": self.base, "ref": self.ref, "defaultRef": self.default}
        if self.github:
            if self.number is None:
                url = github_pr(self.repo, self.github, "create", "--draft", "--head", self.branch,
                                "--base", self.args.pr_base, "--title", self.args.pr_title, "--body", "")
                self.number = pr_number(url, self.github)
            result["pr"] = self.check_pr(candidate, candidate)
        write_json(evidence / "delivery.json", result)


class ReviewChangesRequested(ValueError):
    def __init__(self, candidate):
        super().__init__("independent review requested changes in review-only mode")
        self.candidate = candidate


def execute(adapter: ReviewAdapter, args, repo, evidence):
    start = head(repo)
    clean_at(repo, start)
    base = git(repo, "rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}")
    git(repo, "merge-base", "--is-ancestor", base, start)
    original = current_ref(repo)
    task = args.brief.read_text().strip()
    if not task:
        raise ValueError("task brief is empty")
    writer = Role("nstack_implement", args.implement_model, args.implement_effort)
    reviewer = Role("nstack_review", args.review_model, args.review_effort)
    roles = (reviewer,) if args.review_only else (writer, reviewer)
    write_json(evidence / "request.json", {
        "adapter": adapter.name, "start": start, "base": base, "gate": args.gate,
        "roles": [vars(role) for role in roles],
        "reviewOnly": args.review_only, "reviewFirst": args.review_first,
        "maxRemediations": args.max_remediations, "originalRef": original,
        "workRef": args.work_ref, "deliveryRef": args.delivery_ref, "prNumber": args.pr_number,
    })
    probe = adapter.preflight(repo, (reviewer,), evidence / "preflight")
    write_json(evidence / "preflight.json", probe)
    last = start
    findings = None
    registry = {}
    work = None
    delivery = None
    sessions = set()
    with TemporaryDirectory(prefix="checkouts-", dir=evidence) as temporary:
        directory = Path(temporary)
        for attempt in range((0 if args.review_only else args.max_remediations) + 1):
            if not args.review_only and (findings is not None or not args.review_first):
                clean_at(repo, last)
                if work is None:
                    work = branch_ref(repo, args.work_ref)
                    if git(repo, "for-each-ref", "--format=%(refname)", work):
                        raise ValueError("authorized work ref must be new")
                    if current_ref(repo) != original:
                        raise ValueError("original checkout ref changed")
                    if args.push:
                        delivery = Delivery(args, repo, base, start, writer_required=True)
                        if work in (delivery.default, delivery.ref, delivery.pr_base_ref):
                            raise ValueError("work ref must be distinct from delivery and protected refs")
                    git(repo, "switch", "-c", work.removeprefix("refs/heads/"), last)
                if delivery:
                    delivery.check(last)
                check_work(repo, work, last, original, start)
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
                write_json(evidence / f"{attempt}-implementation.json", {**result, "start": last, "base": base, "workRef": work})
                if delivery:
                    delivery.check(last)
                check_work(repo, work, last, original, start)
                git(repo, "add", "-A")
                if not git(repo, "diff", "--cached", "--name-only"):
                    raise ValueError("implementation made no committable change")
                if delivery:
                    delivery.check(last)
                check_work(repo, work, last, original, start)
                git(repo, "commit", "-m", "Implement requested change" if not findings
                    else "Address independent review findings")
                if git(repo, "rev-parse", "HEAD^") != last:
                    raise ValueError("implementation commit did not extend the authorized candidate")
            candidate = head(repo)
            clean_at(repo, candidate)
            if work:
                check_work(repo, work, candidate, original, start)
            elif current_ref(repo) != original or candidate != start:
                raise ValueError("starting ref or candidate changed")
            if candidate == base:
                raise ValueError("review candidate has no commits beyond the base")
            gate_checkout = directory / f"{attempt}-gate"
            checkout(repo, gate_checkout, candidate)
            scratch = directory / f"{attempt}-scratch"
            scratch.mkdir()
            gate = adapter.gate(gate_checkout, args.gate, scratch, evidence / f"{attempt}-gate")
            write_json(evidence / f"{attempt}-gate.json", {**gate, "candidate": candidate, "base": base})
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
            if not args.review_only:
                prompt += (
                    "\n\nIndependently discover new blocking defects. Put only new defects in findings. "
                    "Assess EVERY registered ID once in previous with resolved, recurring, or uncertain "
                    "and candidate-specific evidence. Keep the ID for the same defect even if the location "
                    "or reproduction changes. If equivalence or resolution cannot be determined use uncertain. "
                    "A pass requires all previous findings resolved and no new findings. Registry: "
                    + json.dumps(registry, ensure_ascii=False)
                )
            result = adapter.run(review_checkout, reviewer, prompt, evidence / f"{attempt}-review",
                                 schema=VERDICT_SCHEMA if args.review_only else TRACKED_VERDICT_SCHEMA)
            record = {**result, "candidate": candidate, "base": base}
            review_path = evidence / f"{attempt}-review.json"
            try:
                clean_at(review_checkout, candidate)
                clean_at(repo, candidate)
                if result["session"] in sessions:
                    raise ValueError("review reused an existing context")
                sessions.add(result["session"])
                review = verdict(result["message"], candidate, None if args.review_only else registry)
            except (ValueError, TypeError, KeyError, subprocess.CalledProcessError) as error:
                write_json(review_path, {**record, "validationError": str(error)})
                raise
            new_ids = {}
            if not args.review_only:
                for item in review["findings"]:
                    identifier = f"F{len(registry) + 1}"
                    registry[identifier] = {"initialLocation": item["location"],
                                            "contract": item["expected"], "failure": item["impact"],
                                            "initialEvidence": item["evidence"]}
                    new_ids[identifier] = item
            write_json(review_path, {**record, "review": review, "newFindingIds": new_ids})
            previous = review.get("previous", [])
            if any(item["status"] in ("recurring", "uncertain") for item in previous):
                raise ValueError("previous finding recurs or remains uncertain; no further remediation")
            if review["verdict"] == "pass":
                if work:
                    check_work(repo, work, candidate, original, start)
                elif current_ref(repo) != original or candidate != start:
                    raise ValueError("starting ref or candidate changed")
                if args.push:
                    if delivery is None:
                        delivery = Delivery(args, repo, base, start, writer_required=False)
                    delivery.push(candidate, evidence)
                return candidate
            if review["verdict"] == "blocked":
                raise ValueError("independent review blocked this candidate")
            if args.review_only:
                raise ReviewChangesRequested(candidate)
            findings = new_ids
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
    parser.add_argument("--work-ref", help="Authorize creation of this new local refs/heads/ branch")
    parser.add_argument("--push", metavar="REMOTE", help="Normal push of the passing candidate")
    parser.add_argument("--delivery-ref", help="Explicit remote refs/heads/ target for --push")
    parser.add_argument("--github-repo", help="Explicit OWNER/REPO for draft PR creation")
    parser.add_argument("--pr-base")
    pr_action = parser.add_mutually_exclusive_group()
    pr_action.add_argument("--pr-title")
    pr_action.add_argument("--pr-number", type=int, help="Update this existing PR only")
    parser.add_argument("gate", nargs="+", help="Mandatory gate argv, after --")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if bool(args.push) != bool(args.delivery_ref):
        parser.error("--push and --delivery-ref must be supplied together")
    pr = (args.github_repo, args.pr_base, args.pr_title or args.pr_number)
    if any(value is not None for value in pr) and (not all(pr) or not args.push):
        parser.error("PR delivery requires --push, --github-repo, --pr-base and --pr-title or --pr-number")
    if args.pr_number is not None and args.pr_number < 1:
        parser.error("--pr-number must be positive")
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
