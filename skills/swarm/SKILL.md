---
name: swarm
description: Run independent tasks in parallel with explicit ownership and isolation.
---

List dependencies, expected file overlap, acceptance checks and one owner per task. Parallelize only independent work. Use the `interrogate` skill for independent review. Use the active harness adapter to start a separate writer session for each task, with a distinct branch and Git worktree per writer. Use a sandbox rooted at each worktree without granting sibling write access. If parallelism is optional, run serially only when the serial route meets all required permissions and capabilities. If a required capability cannot be verified, stop the affected work and report the blocker; do not substitute a weaker route. Collect exact bases, diffs, tests and blockers. The coordinating session applies the global and repository delivery rules.
