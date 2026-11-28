---
name: swarm
description: Run independent tasks in parallel with explicit ownership and isolation.
---

List dependencies, expected file overlap, acceptance checks and one owner per task. Parallelize only independent work. Use $interrogate for independent review. Use the active harness adapter to start a separate writer session for each task, with a distinct branch and Git worktree per writer. Use a sandbox rooted at each worktree without granting sibling write access. If isolation or optional delegation is unavailable, run serially and report it. Collect exact bases, diffs, tests and blockers. The coordinating session applies the global and repository delivery rules.
