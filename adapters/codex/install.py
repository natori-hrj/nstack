"""Stage or activate a Codex skill snapshot in an explicit Codex home."""
import argparse
from contextlib import contextmanager
import fcntl
import filecmp
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def identical(left, right):
    if left.is_symlink() or right.is_symlink():
        return False
    if left.is_file() and right.is_file():
        return filecmp.cmp(left, right, shallow=False)
    if left.is_dir() and right.is_dir():
        names = {entry.name for entry in left.iterdir()}
        return names == {entry.name for entry in right.iterdir()} and all(
            identical(left / name, right / name) for name in names
        )
    return False


def stage(state, snapshot):
    with TemporaryDirectory(prefix="stage-", dir=state) as temporary:
        staged = Path(temporary) / "snapshot"
        shutil.copytree(ROOT / "skills", staged / "skills")
        for name in ("adapters/codex", "docs", "examples/agents"):
            shutil.copytree(ROOT / name, staged / name)
        for name in ("LICENSE", "LICENSE-upstream", "README.md", "README.ja.md"):
            shutil.copy2(ROOT / name, staged / name)
        if snapshot.exists() or snapshot.is_symlink():
            if not identical(snapshot, staged):
                raise ValueError(f"snapshot {snapshot.name} already contains different files")
        else:
            staged.rename(snapshot)


def installed_skills(skills, managed):
    seen = set()
    for directory, subdirectories, files in os.walk(skills, followlinks=True):
        path = Path(directory)
        resolved = path.resolve()
        if resolved in seen:
            subdirectories.clear()
        seen.add(resolved)
        if path == skills and managed.name in subdirectories:
            subdirectories.remove(managed.name)
        if "SKILL.md" in files:
            yield path / "SKILL.md"


def activate(home, state, snapshot):
    if snapshot.is_symlink() or not (snapshot / "skills").is_dir():
        raise ValueError(f"stage snapshot {snapshot.name} first")

    skills = home / "skills"
    current = skills / "nstack-managed"
    if current.is_symlink():
        target = current.readlink()
        if target.name != "skills" or target.parent.parent != state / "snapshots":
            raise ValueError(f"unmanaged skill path: {current}")
    elif current.exists():
        raise ValueError(f"unmanaged skill path: {current}")

    names = {path.parent.name for path in (snapshot / "skills").glob("*/SKILL.md")}
    for existing in installed_skills(skills, current):
        declared = re.search(r"^name:[ 	]*(\S+)[ 	]*$", existing.read_text(), re.M)
        if existing.parent.name in names or (declared and declared[1] in names):
            raise ValueError(f"move existing skill out of discovery first: {existing}")

    skills.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".nstack-", dir=skills) as temporary:
        link = Path(temporary) / "skills"
        link.symlink_to(snapshot / "skills", target_is_directory=True)
        link.replace(current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("action", choices=("stage", "activate"))
    parser.add_argument("snapshot", help="Unique identifier, preferably the candidate Git SHA")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.snapshot):
        parser.error("invalid snapshot identifier")

    home = args.home.resolve()
    state = home / "nstack"
    snapshot = state / "snapshots" / args.snapshot
    try:
        if any(path.is_symlink() for path in (state, snapshot.parent, home / "skills")):
            raise ValueError("managed directories must not be symbolic links")
        with locked(state):
            snapshot.parent.mkdir(exist_ok=True)
            if args.action == "stage":
                stage(state, snapshot)
            else:
                activate(home, state, snapshot)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(snapshot)


if __name__ == "__main__":
    main()
