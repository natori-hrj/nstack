---
name: swarm
description: Run independent tasks in parallel with explicit ownership and isolation.
---

List dependencies, expected file overlap, acceptance checks and one owner per task. Parallelize only independent work. Use $interrogate for independent review. For writers use separate Codex sessions in separate Git worktrees, with a distinct branch per writer. Use a sandbox rooted at each worktree without granting sibling write access. If isolation or optional delegation is unavailable, run serially and report it. Collect exact bases, diffs, tests and blockers. The coordinating session applies the global and repository delivery rules.
