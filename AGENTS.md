# AGENTS.md — Veles-MOEX Agent Directives

## 1. Mandatory context recovery

Before changing code, the agent MUST independently recover the current project state from the repository and Git:

1. Read `PROJECT_STATE.md`.
2. Check the current branch, HEAD, working tree, and `master`.
3. Read the current MVP task in `.agent/TASK-*.md`.
4. Read the applicable `.agent/REVIEW-*.md` and latest `.agent/REPORT-*.md`.
5. Inspect the relevant architecture/product documentation before implementation.

Do not rely on chat history, assumptions, or remembered project state when repository documentation is available.

## 2. Veles compatibility — HARD RULE

Veles-MOEX must reproduce documented Veles behavior. For every behavior derived from Veles, the agent MUST first inspect the official Veles Help Center / project Veles documentation.

The agent MUST NOT invent, infer, generalize, or silently substitute:

- indicators;
- indicator formulas;
- indicator parameters;
- parameter defaults;
- timeframe/interval semantics;
- shift semantics;
- signal semantics;
- crossing semantics;
- warmup/history requirements;
- lookback rules;
- order/grid/DCA behavior;
- TP/exit behavior;
- other Veles-specific behavior.

Generic trading conventions are NOT a substitute for Veles documentation.

If the official documentation does not define a required behavior:

1. Do not invent a rule.
2. Do not silently choose a conventional/default value.
3. Implement only the documented portion, if that is technically possible.
4. Otherwise stop at that boundary and document the limitation in the task/report.
5. Ask for clarification when a decision is required to continue.

## 3. Documentation-first implementation

Before implementing a Veles-derived feature, record internally which official documentation establishes the relevant behavior. If documentation is ambiguous or incomplete, preserve that ambiguity rather than creating a new undocumented contract.

Any new project-level semantic contract must be explicitly documented and approved; it must not be introduced merely because it is convenient for implementation.

## 4. Task and branch discipline

- Work only within the branch/task explicitly assigned by the current control workflow.
- `agent/control` is the control/audit contour.
- Implementation/review branches must remain traceable to the assigned task.
- Do not modify `master` as part of ordinary implementation work.
- Do not force-push.
- Do not use rebase as a substitute for the publication/review process.
- Do not self-declare an MVP accepted.
- Acceptance is performed by the independent review process.

## 5. Scope discipline

Preserve existing documented behavior unless the current task explicitly changes it.

In particular, do not silently change:

- Veles Filter/Signal semantics;
- DCA/Grid semantics;
- Backtest behavior;
- PositionManager quantity authority;
- broker-neutral architecture;
- Decimal monetary/price handling;
- UTC timestamp semantics;
- T-Invest read-only boundary;
- existing MVP acceptance guarantees.

If a requested change conflicts with an existing accepted contract, stop and document the conflict rather than silently changing the contract.

## 6. Validation and reporting

Before reporting completion:

- run the relevant tests;
- run lint/static checks applicable to the changed code;
- run the frontend build when applicable;
- inspect the actual diff;
- verify that no undocumented Veles semantics were introduced.

The report must state:

- task/MVP;
- implementation branch;
- commit SHA;
- exact changes;
- validation results;
- known limitations;
- any documentation/specification gaps.

A passing test suite does not make an undocumented Veles behavior acceptable.

## 7. Current project recovery source

`PROJECT_STATE.md` is the canonical recovery document. Keep it current after accepted MVP changes according to the project workflow.
