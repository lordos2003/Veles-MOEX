# OpenCode / Git Workflow

## Canonical control branch

`agent/control` is the canonical control branch for the Veles-MOEX development workflow.

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

## Current example: MVP-6.9

Task:
`.agent/TASK-MVP-6.9-POSITION-STATE.md`

Control branch:
`agent/control`

Implementation/review branch:
`agent/review/mvp-6.9`

Base:
`master @ b2c4ee27cdd1bcf67bb69c2f22374cb062bebb52`

Control task commit:
`5349bd4f89862e68740998340fa6a3754c383bdc`

Current status:
- task recorded in `agent/control`;
- implementation must be performed in `agent/review/mvp-6.9`;
- `master` must not be changed until independent ChatGPT review and explicit acceptance.

## Important invariant

The control branch is not the product implementation branch.

The sequence must remain:

`agent/control -> agent/review/mvp-X -> ChatGPT review -> master`.
