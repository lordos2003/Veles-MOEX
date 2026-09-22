# T-Invest connection transports

## Decision

Veles-MOEX has **one broker in MVP: T-Invest**.

T-Invest is exposed through two selectable connection transports:

1. **Open API** — direct T-Invest API integration.
2. **T-Invest MCP** — MCP over HTTP Streamable.

These are not separate brokers and must not produce separate domain models.

## Runtime model

```text
                     T-Invest (one broker)
                              |
                    selected transport
                         /          \
                        /            \
               Open API              MCP
                  |                    |
          TInvestAdapter        TInvestMcpAdapter
                  \                    /
                   \                  /
                    +-- BrokerAdapter-+
                              |
                    Trading / Data layers
```

The selected transport is a connection/integration concern. Strategy, Backtest,
Trading, Risk, Position and Order Manager code must remain transport-agnostic.

## User setting

The broker connection settings will expose:

- Broker: `T-Invest`
- Transport:
  - `Open API`
  - `T-Invest MCP`

The default remains `Open API` until MCP implementation and integration tests are complete.

## Credentials

Both transports use a T-Invest API token. The token must remain server-side and
must never be persisted in source control or returned to the frontend.

The MCP endpoint documented by T-Bank is:

`https://invest-public-api.tbank.ru/mcp`

T-Bank documents HTTP Streamable transport and Bearer authentication for T-Invest MCP.

## Adapter contract

Both implementations must satisfy the same `BrokerAdapter` contract and return
the existing broker-agnostic DTOs:

- `BrokerAccount`
- `BrokerPosition`
- `BrokerOrder`
- `BrokerDeal`
- `BrokerInstrument`
- `BrokerOrderRequest`
- `Candle`
- `LastPrice`

No MCP protocol object may cross the broker adapter boundary.

## Current implementation status

- `TInvestAdapter`: implemented, read-only, using T-Invest Open API.
- `TInvestMcpAdapter`: architectural boundary documented; implementation is a separate task.
- User-selectable transport: reserved in architecture; UI/runtime selection is enabled only after both adapters satisfy the same contract.

This deliberate sequencing prevents the UI from offering an MCP option that cannot yet execute the complete broker contract.

## Live trading

When trading is implemented, the execution path remains:

```text
Strategy -> Trading Engine -> BrokerAdapter
                              |
                 +------------+------------+
                 |                         |
              Open API                    MCP
                 |                         |
           T-Invest API              T-Invest MCP
                 |                         |
                 +------------+------------+
                              |
                             MOEX
```

The trading engine must not contain `if transport == ...` branches.

## Official references

- T-Invest API: https://developer.tbank.ru/invest/intro/intro
- T-Invest MCP: https://developer.tbank.ru/invest/mcp
- MCP coding-agent connection: https://developer.tbank.ru/invest/mcp/agents-connect/coding-agents
