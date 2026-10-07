// @vitest-environment jsdom
/**
 * REV2 B6 (hook test): bot display metadata loads LOCAL data (strategies,
 * instruments, versions) and BROKER data (accounts) independently. A failing
 * `GET /api/accounts` (no token, broker down) must not clear the
 * version/instrument maps that the bot page labels and the version-change
 * dropdown depend on — only `accountsError` is set.
 */
import { describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { api } from "../api";
import { useBotDisplayMeta } from "./BotSettingsPanel";

vi.mock("../api", () => ({
  ApiError: class ApiError extends Error {},
  fieldErrors: () => ({}),
  verbatimMessage: (detail: unknown) => String(detail),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const getMock = api.get as unknown as Mock;

describe("REV2 B6: метаданные бота грузятся независимо от запроса счетов", () => {
  it("при ошибке брокера локальные страницы/инструменты/версии сохраняются", async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === "/api/strategies") {
        return [
          {
            id: 1,
            name: "Стратегия A",
            description: null,
            is_active: true,
            config: {},
            versions: 2,
            created_at: "",
            updated_at: "",
          },
        ];
      }
      if (path === "/api/instruments?active=true") {
        return [
          {
            id: 1,
            figi: "BBG004730N88",
            ticker: "SBER",
            name: "Сбербанк",
            instrument_type: null,
            currency: null,
            lot_size: null,
            tick_size: null,
            trading_status: "NORMAL_TRADING",
            exchange: null,
            is_active: true,
          },
        ];
      }
      if (path === "/api/strategies/1/versions") {
        return [{ id: 7, version: 2, created_at: "" }];
      }
      if (path === "/api/accounts") {
        throw new Error("broker unavailable");
      }
      throw new Error(`unexpected path ${path}`);
    });

    const { result } = renderHook(() => useBotDisplayMeta());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await waitFor(() => expect(result.current.accountsError).toBe("broker unavailable"));

    expect(result.current.error).toBeNull();
    expect(result.current.versions.get(7)).toEqual({
      strategyId: 1,
      strategyName: "Стратегия A",
      version: 2,
    });
    expect(result.current.instruments.get(1)).toBe("SBER");
    expect(result.current.accounts.size).toBe(0);
  });

  it("успешные счета заполняют карту счетов и сбрасывают accountsError", async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === "/api/strategies") return [];
      if (path === "/api/instruments?active=true") return [];
      if (path === "/api/accounts") {
        return [
          {
            id: 3,
            account_id: "abc123",
            is_saved: true,
            broker: "t-invest",
            currency: "RUB",
            available_cash: "0",
            equity: "0",
            currencies: [],
            name: "Боевой счёт",
            account_type: null,
            status: null,
            opened_at: null,
            closed_at: null,
          },
        ];
      }
      throw new Error(`unexpected path ${path}`);
    });

    const { result } = renderHook(() => useBotDisplayMeta());
    await waitFor(() => expect(result.current.accounts.get(3)).toBe("Боевой счёт"));
    expect(result.current.accountsError).toBeNull();
  });
});
