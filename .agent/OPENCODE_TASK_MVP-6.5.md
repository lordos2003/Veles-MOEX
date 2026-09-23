# OpenCode Task — MVP-6.5 Bot Lifecycle and Risk Preconditions

## TASK_ID

MVP-6.5-BOT-LIFECYCLE-RISK

## Context

MVP-6.4 is accepted and published in `master` at:

`3ce159f4ac2b49088a53ce70cd0d24a3f5a5b684`

Post-MVP-6 audit found a concrete remaining gap between the specification and the implementation.

The specification requires:

- bot lifecycle: START, RUNNING, STOP_REQUESTED, STOPPED, ERROR, EMERGENCY_STOP;
- Risk Manager checks before every live order:
  - bot is running;
  - instrument is allowed;
  - trading session/instrument status permits trading;
  - positive/valid quantity;
  - valid price;
  - required funds/position capacity;
  - configured execution limits;
  - emergency stop.

Current implementation has:

- `RiskManager.check_order()`: emergency stop, max position size, optional daily loss;
- `RiskManager.check_start()`: only an isolated counter method;
- no real live bot-start lifecycle;
- no production bot state connected to live execution;
- no configured production RiskLimits source;
- `TradingEngine.process()` is intentionally not part of the current live composition.

Do not hide these gaps with documentation only. Implement the real existing application lifecycle if the repository already contains a bot model/service/API. Do not invent a parallel fake lifecycle.

## Goal

Close the real bot-lifecycle gap with the smallest broker-neutral implementation that fits the existing application structure.

The authoritative execution chain must remain:

`LiveExecutionService.submit()`
→ `TradingEngine.submit_intent()`
→ `RiskManager.check_order()`
→ `OrderManager.submit()`
→ `BrokerAdapter`

## Required work

### 1. Inspect existing bot/application lifecycle first

Find the existing bot domain/model/service/API/configuration in the repository.

If a real bot lifecycle already exists:

- connect START/STOP to it;
- enforce the required lifecycle states;
- call the Risk Manager start guard from the real START path;
- ensure STOP prevents new execution;
- preserve active-position semantics for normal STOP;
- EMERGENCY_STOP must block new execution and cancel active bot orders where the existing broker-neutral cancellation path supports it.

Do not create a duplicate Bot subsystem.

If no bot lifecycle exists at all, stop and report the exact missing foundation. Do not invent a fake lifecycle.

### 2. Risk Manager

Extend the existing broker-neutral Risk Manager only where the existing domain data supports it.

At minimum:

- bot-running/start guard must be authoritative for live submit;
- existing emergency stop remains authoritative;
- existing max-position rule remains;
- quantity validity must be checked before broker submission.

For instrument/session/funds checks:

- reuse existing broker-neutral instrument/account DTOs or services if already available;
- do not import T-Invest into Risk Manager;
- do not invent financial defaults;
- if a required fact is not available in the current domain, document that exact limitation instead of fabricating a value.

### 3. Production configuration

Inspect existing application configuration.

If a real risk configuration source already exists, wire it into production `build_live_service()`.

If no such source exists:

- do not invent limits;
- keep limits unset;
- document the exact boundary.

### 4. Preserve existing live execution

Do not change:

- OrderStateStream-only live event architecture;
- recovery/reconciliation;
- SAFE/BLOCKED recovery gate;
- idempotency;
- fill deduplication;
- Position Manager;
- DCA/Grid;
- Exit Engine;
- Strategy Engine;
- Backtest Engine;
- T-Invest adapter behavior;
- MCP boundary.

### 5. Tests

Add deterministic tests for the actual implemented lifecycle.

At minimum:

- START transitions a real bot to RUNNING;
- start is rejected when max concurrent bots is reached;
- STOP prevents new live submission;
- normal STOP does not automatically close an active position;
- EMERGENCY_STOP blocks new submission;
- existing max-position protection still works;
- existing SAFE/BLOCKED recovery gate still works.

Do not write tests against a fake lifecycle created only for this task.

## Documentation

Update the MVP-6 live specification so it no longer contains a contradictory statement that bot-start is outside MVP-6 if the real lifecycle is now implemented.

Document any remaining risk checks that cannot be enforced because the required domain fact does not yet exist.

## Validation

Run:

```powershell
pytest
ruff check app tests scripts
npm run build
```

## Git

- One focused implementation commit.
- Do NOT push `master`.
- Do NOT merge.
- Do NOT rebase.
- Do NOT reset.
- Publish the commit to `agent/review/mvp-6.5`.
- Write a separate REPORT to `agent/control`.
- Do not modify `CHATGPT REVIEW`.
- Stop after REPORT.

REPORT must contain:

- commit SHA;
- existing lifecycle discovered;
- exact lifecycle path implemented;
- RiskManager checks actually enforced;
- production configuration status;
- changed files;
- tests and exact results;
- ruff result;
- npm build result;
- remaining limitations;
- git status;
- git log -5.

## Important

No financial tuning.

No new strategy logic.

No fake defaults.

No unrelated refactoring.
