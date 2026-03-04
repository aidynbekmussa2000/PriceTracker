@ralph/plan.md @ralph/activity.md
@price_tracker/markets/base.py @price_tracker/markets/arbuz.py @price_tracker/markets/vprestige.py
@price_tracker/markets/__init__.py @price_tracker/core/runner.py @price_tracker/main.py @config.yaml

You are implementing exactly ONE market-expansion task per iteration for this repository.

Workflow rules:
1. Read `ralph/activity.md`.
2. Open `ralph/plan.md` and find the first task where:
   - `"passes": false`
   - all `depends_on` tasks are `true`
3. Immediately change that task to `"passes": "in_progress"`.
4. Implement exactly that one task and do not start another.
5. Validate with the command(s) listed in the task (or closest equivalent if a minor flag change is needed).
6. Update that task to `"passes": true` only if validation succeeded.
7. Append a dated progress entry to `ralph/activity.md` with:
   - files changed
   - commands run
   - validation results
8. Create one git commit for this task only.

Implementation constraints:
- Keep architecture market-agnostic.
- Reuse `BaseMarket` contract and existing storage/report flow.
- Do not rewrite existing `arbuz`/`vprestige` behavior unless required by the selected task.
- Keep changes minimal and focused on the selected task.
- Do not run `git init`, do not change remotes, do not push.

When there are no runnable tasks left with `"passes": false`, output exactly:
<promise>COMPLETE</promise>
