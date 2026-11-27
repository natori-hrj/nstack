---
name: swarm
description: Run independent tasks in parallel with explicit ownership and isolation.
---

List dependencies, expected file overlap, acceptance checks and one owner per task. Parallelize only independent work. Use the configured native review agent from a read-only parent or a separate read-only session for independent reviews with a fresh task-specific brief. For writers use separate Codex sessions in separate Git worktrees, with a distinct branch per writer. Use a sandbox rooted at each worktree without granting sibling write access. If isolation or delegation is unavailable, run serially and report it. Collect exact bases, diffs, tests and blockers. Integration and publication remain operator decisions.
