# OpenCode / Git Workflow

## Canonical control branch and audit source

`agent/control` is the canonical control branch for the Veles-MOEX development workflow **and the mandatory source of truth for current tasks, audit instructions, control records, implementation REPORTs, review/acceptance records, and publication records**.

**When ChatGPT or OpenCode needs to find the current task or audit assignment, start on `agent/control`. Do not require the user to tell the coder where the task is located.**

The current working repository state for audit/review is always taken from `agent/control` unless a task explicitly names another ref for comparison.

It contains:
- tasks for OpenCode;
- implementation instructions;
- control records;
- implementation REPORTs;
- review/acceptance records;
- publication records.

Product implementation must not be placed directly into `agent/control`.

## Standard MVP flow

```
agent/control
    ↓
задание кодеру + контроль + отчёты
    ↓
agent/review/mvp-X
    ↓
независимая проверка ChatGPT
    ↓
master — только после принятия
```

### Meaning of each stage

1. **agent/control**
   - ChatGPT records the task.
   - OpenCode receives the task from this branch.
   - OpenCode writes implementation REPORTs here.
   - Acceptance/review records are kept here.
   - This branch is the control/audit trail.
   - **All new audit/review work starts by reading the relevant task/specification and current project state from this branch.**

2. **agent/review/mvp-X**
   - OpenCode performs the actual product implementation in the dedicated MVP review branch.
   - The branch is based on the accepted/current `master` baseline unless the task explicitly specifies another base.
   - The implementation is not considered accepted merely because OpenCode reports success.

3. **Independent ChatGPT review**
   - ChatGPT independently checks the actual diff, architecture, tests, scope, and stated limitations.
   - ChatGPT either accepts the MVP or records required corrections.
   - OpenCode must not self-declare acceptance.

4. **master**
   - Only accepted implementation may be published to `master`.
   - No implementation is published to `master` before explicit ChatGPT acceptance.
   - No force-push.
   - No rebase as a substitute for the established publication workflow.
   - After publication, the resulting SHA and publication status are recorded in `agent/control`.

## Mandatory task-publication rule

**When ChatGPT prepares a task for OpenCode/coder, the task must be published directly to GitHub. The user must not be required to copy the task text manually.**

The GitHub task artifact is the source of truth. In the normal workflow, ChatGPT publishes the task to the repository (typically as a GitHub Issue), gives the user the direct link, and the coder works from that published task. This rule must be preserved when restoring the project in a new chat.

## Mandatory audit-location rule

**All repository audits, specification audits, acceptance audits, and cross-checks must use the current `agent/control` branch as the starting/current reference unless the task explicitly specifies another ref.**

The user must not be required to repeat or explain where the current task is located. ChatGPT/OpenCode must:
1. inspect `agent/control`;
2. locate the relevant task/specification/control record there;
3. use the current `agent/control` state as the audit baseline;
4. only then inspect implementation/review branches or `master` when required for comparison.

Detailed project control rules: `.agent/PROJECT-CONTROL-RULES.md`.

## Important invariant

The control branch is not the product implementation branch.

The sequence must remain:

`agent/control -> agent/review/mvp-X -> ChatGPT review -> master`.
