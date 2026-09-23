# Veles-MOEX — OpenCode Development Workflow

## Purpose

This document defines the working protocol between ChatGPT (architect/reviewer), the user, and OpenCode (implementation agent, called “кодер”).

The protocol applies to Veles-MOEX engineering work.

## Roles

### ChatGPT

ChatGPT is responsible for:
- defining the next engineering task;
- recording the task in the GitHub control channel;
- defining scope, constraints, acceptance criteria and tests;
- reviewing the coder's report;
- independently checking the actual GitHub commit and diff;
- checking architecture and implementation against the task;
- deciding whether the task is accepted or requires correction.

A coder's statement that a task is “done” is not sufficient evidence for acceptance.

### User

The user is the operator of the local development environment.

The user:
- starts OpenCode with the task from the control file;
- authorizes pushes when appropriate;
- does not need to manually translate the engineering task into implementation details.

### OpenCode (“кодер”)

OpenCode is the implementation agent.

It:
- reads `.agent/OPENCODE_TASK.md`;
- implements only the requested scope;
- runs the requested validation;
- creates the requested focused commit;
- writes a complete `REPORT` into `.agent/OPENCODE_TASK.md`;
- does not merge/rebase or make unrelated changes unless explicitly authorized.

## Standard workflow

1. ChatGPT defines the engineering task.
2. ChatGPT writes the task to `.agent/OPENCODE_TASK.md` on `agent/control`.
3. User tells OpenCode: “Выполни задачу GPT из `.agent/OPENCODE_TASK.md`. После завершения запиши полный REPORT в этот же файл. Push не выполняй.”
4. OpenCode implements and reports.
5. OpenCode pushes `agent/control` only when instructed to publish the report.
6. ChatGPT reads the report from GitHub.
7. ChatGPT independently checks the actual product commit/diff on GitHub.
8. If the implementation is correct, ChatGPT accepts it.
9. Only after acceptance is `master` pushed/published.
10. If the implementation is incorrect, ChatGPT writes a focused correction task. The process repeats.

## Branch protocol

- `master` = accepted product code.
- `agent/control` = ChatGPT ↔ OpenCode communication channel.
- Product code must not be merged/rebased through the control branch.
- If OpenCode detects unexpected history divergence, it must stop and report it.
- OpenCode must not silently resolve divergence.

## Evidence rule

Acceptance is based on independently verifiable evidence:
- GitHub commit exists;
- commit/diff matches the requested scope;
- tests and build results are consistent with the report;
- architecture constraints are respected;
- no unrelated changes were introduced.

The REPORT is evidence about what the coder says it did, not a substitute for checking the actual commit.

## Scope discipline

OpenCode must not autonomously:
- tune financial parameters;
- redesign Strategy, DCA/Grid or Exit logic;
- introduce additional brokers;
- change architecture outside the task;
- fix unrelated technical debt.

Only current blockers and changes necessary to complete the active task should be addressed.

## Communication

The control file is the authoritative hand-off document for an active OpenCode task.

The report must contain:
- implementation summary;
- changed files;
- tests and their results;
- lint/build results;
- commit SHA;
- known limitations;
- any divergence or blocked condition.

The `CHATGPT REVIEW` section is reserved for ChatGPT and must not be modified by OpenCode.