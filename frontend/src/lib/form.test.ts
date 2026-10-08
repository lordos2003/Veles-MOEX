/**
 * U8: frontend unit tests for the schema-driven strategy form.
 *
 * The owner contract: the UI invents no values — a field gets a value only from
 * user input or a `default` present in the JSON Schema. Python default_factory
 * values are not in the schema, so they must NOT appear in the initial form.
 *
 * The fixture below mirrors the real StrategyConfig JSON Schema shape
 * (entry/dca_grid/exit/risk + unions via oneOf + nullable anyOf).
 */
import { describe, expect, it } from "vitest";
import { compact, formFromConfig, formToConfig, initialValue, propertyMetas } from "./schema";
import { collectMissingIndicatorArgs } from "../components/FilterGroupEditor";
import { fieldErrors, verbatimMessage, ApiError } from "../api";
import type { IndicatorResponse, SchemaNode } from "../types";

const defs: Record<string, SchemaNode> = {
  EntryConfig: {
    type: "object",
    properties: {
      method: { type: "string", enum: ["at_bar_close", "per_minute"] },
      groups: { type: "array", items: { $ref: "#/$defs/FilterGroup" } },
    },
    required: ["method", "groups"],
  },
  FilterGroup: {
    type: "object",
    properties: {
      id: { type: "string" },
      conditions: { type: "array", items: { type: "object" } },
    },
  },
  DCAGridConfig: {
    type: "object",
    properties: {
      mode: { type: "string", enum: ["simple", "custom", "signal"] },
      levels: { type: "integer", default: 1, minimum: 1 },
      overlap_percent: { type: "number", default: 0.0 },
    },
  },
  ExitConfig: {
    type: "object",
    properties: {
      take_profit: {
        oneOf: [{ $ref: "#/$defs/FixedTP" }, { $ref: "#/$defs/MultiTP" }],
        discriminator: { propertyName: "kind" },
      },
      stop_loss: { anyOf: [{ $ref: "#/$defs/StopLoss" }, { type: "null" }] },
    },
    required: ["take_profit"],
  },
  FixedTP: {
    type: "object",
    properties: {
      kind: { type: "string", const: "fixed_percentage", default: "fixed_percentage" },
      percent: { type: "number" },
    },
    required: ["kind", "percent"],
  },
  MultiTP: {
    type: "object",
    properties: {
      kind: { type: "string", const: "multi_take", default: "multi_take" },
      takes: { type: "array", items: { type: "object" } },
    },
  },
  StopLoss: {
    type: "object",
    properties: {
      kind: { type: "string", const: "percent", default: "percent" },
      percent: { type: "number" },
      stop_bot_after: { anyOf: [{ type: "boolean" }, { type: "null" }] },
    },
    required: ["kind", "percent"],
  },
  RiskConfig: {
    type: "object",
    properties: {
      emergency_stop: { type: "boolean", default: false },
      max_position_size: { anyOf: [{ type: "number" }, { type: "null" }] },
    },
  },
};

const rootSchema: SchemaNode = {
  type: "object",
  properties: {
    name: { type: "string" },
    direction: { type: "string", enum: ["LONG", "SHORT"] },
    timeframe: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
    lookback_bars: { anyOf: [{ type: "integer" }, { type: "null" }] },
    entry: { $ref: "#/$defs/EntryConfig" },
    dca_grid: { $ref: "#/$defs/DCAGridConfig" },
    exit: { $ref: "#/$defs/ExitConfig" },
    risk: { $ref: "#/$defs/RiskConfig" },
  },
  required: ["name", "direction", "exit"],
};

describe("U8.1 схема → начальное состояние формы", () => {
  it("берёт значения только из `default` схемы; обязательные поля без default пустые", () => {
    const form = initialValue(rootSchema, defs) as Record<string, unknown>;
    const dca = form.dca_grid as Record<string, unknown>;
    const risk = form.risk as Record<string, unknown>;
    const entry = form.entry as Record<string, unknown>;

    // Поля без default (даже обязательные) — пустые (undefined), не «предзаполнены».
    expect(form.name).toBeUndefined();
    expect(form.direction).toBeUndefined();
    expect(form.lookback_bars).toBeUndefined();
    expect(entry.method).toBeUndefined();
    expect(dca.mode).toBeUndefined();

    // default из схемы применяется.
    expect(form.timeframe).toBeNull();
    expect(dca.levels).toBe(1);
    expect(dca.overlap_percent).toBe(0.0);
    expect(risk.emergency_stop).toBe(false);
    expect(risk.max_position_size).toBeUndefined();

    // Массив без default — пустой, но не заполненный «примерами».
    expect(entry.groups).toEqual([]);
    // Pydantic default_factory-значений в схеме нет — они не появляются.
  });
});

describe("U8.2 форма → конфигурация → форма без потерь", () => {
  it("сохраняет null/false/незнакомые поля и теряет только undefined", () => {
    const form = {
      name: "Моя стратегия",
      direction: "LONG",
      timeframe: null,
      an_unknown_root_field: 42,
      entry: { method: "at_bar_close", groups: [] },
      dca_grid: { mode: "simple", levels: 2, custom_levels: null, unknown_grid_field: "x" },
      exit: {
        take_profit: { kind: "fixed_percentage", percent: 3.5 },
        stop_loss: { kind: "percent", percent: 10, stop_bot_after: null },
        signal_stop: undefined, // удаляется при компактизации
      },
      risk: { emergency_stop: false, max_position_size: null },
    };

    const config = formToConfig(form) as Record<string, unknown>;
    expect(config).not.toHaveProperty("exit.signal_stop");
    const exit = config.exit as Record<string, unknown>;
    expect(exit).not.toHaveProperty("signal_stop");
    expect(exit.stop_loss).toEqual({ kind: "percent", percent: 10, stop_bot_after: null });
    expect((config.dca_grid as Record<string, unknown>).unknown_grid_field).toBe("x");
    expect((config as Record<string, unknown>).an_unknown_root_field).toBe(42);

    const form2 = formFromConfig(config);
    expect(form2).toEqual(config);
  });
});

describe("U8.3 ошибки 422 с путями попадают к нужным полям", () => {
  it("мапит loc без 'body' в точечные пути", () => {
    const detail = [
      { loc: ["body", "name"], msg: "Field required", type: "missing" },
      { loc: ["body", "exit", "take_profit", "percent"], msg: "Input should be a valid number", type: "float_parsing" },
      { loc: ["body", "dca_grid", "levels"], msg: "Input should be greater than or equal to 1", type: "greater_than_equal" },
    ];
    expect(fieldErrors(detail)).toEqual({
      name: "Field required",
      "exit.take_profit.percent": "Input should be a valid number",
      "dca_grid.levels": "Input should be greater than or equal to 1",
    });
  });

  it("строковый detail показывается дословно", () => {
    expect(verbatimMessage("period from 2020-01-01 to 2020-02-01 estimates 100000 candles")).toBe(
      "period from 2020-01-01 to 2020-02-01 estimates 100000 candles",
    );
  });
});

describe("MVP-7.4 U6: читаемые 422-сообщения", () => {
  const item = {
    type: "missing",
    loc: ["body", "exit", "take_profit"],
    msg: "Field required",
    input: {},
  };

  it("ApiError распаковывает конверт { detail: [...] }", () => {
    const err = new ApiError(422, { detail: [item] });
    expect(err.detail).toEqual([item]);
    expect(err.message).toBe("Тейк-профит: Field required");
  });

  it("verbatimMessage показывает русское имя поля вместо точечного пути", () => {
    expect(verbatimMessage([item])).toBe("Тейк-профит: Field required");
    expect(verbatimMessage({ detail: [item] })).toBe("Тейк-профит: Field required");
  });

  it("сообщение без пути показывается без префикса", () => {
    expect(verbatimMessage([{ type: "missing", loc: ["body"], msg: "Что-то пошло не так" }])).toBe(
      "Что-то пошло не так",
    );
  });
});

describe("U8.4 stop_bot_after не выбран по умолчанию; пустой выбор не превращается в false", () => {
  it("initial value undefined; compact сохраняет null и false как есть", () => {
    const exit = initialValue(rootSchema, defs) as Record<string, unknown>;
    const stopLoss = (exit.stop_loss ?? {}) as Record<string, unknown>;
    // В начальном состоянии стоп-лосс даже не выбран; если выбран —
    // stop_bot_after остаётся undefined, а не false.
    expect(stopLoss.stop_bot_after).toBeUndefined();

    expect(compact({ stop_bot_after: null })).toEqual({ stop_bot_after: null });
    expect(compact({ stop_bot_after: false })).toEqual({ stop_bot_after: false });
    expect(compact({ stop_bot_after: undefined })).toEqual({});
  });
});

describe("REV1 B4: default рядом с $ref (реальная форма схемы pydantic)", () => {
  // Pydantic v2 эмитит `{"$ref": "#/$defs/X", "default": ...}` — default —
  // сосед $ref, а не часть резолвленного узла. Ранее он терялся, и поле,
  // выбранное по default, выглядело как «не выбрано».
  const defs2: Record<string, SchemaNode> = {
    Direction: { type: "string", enum: ["LONG", "SHORT"] },
    CalculationMethod: { type: "string", enum: ["at_bar_close", "per_minute"] },
  };

  it("default из пары ($ref + default) доходит до начального значения", () => {
    const root: SchemaNode = {
      type: "object",
      properties: {
        direction: { $ref: "#/$defs/Direction", default: "LONG" },
        method: { $ref: "#/$defs/CalculationMethod", default: "at_bar_close" },
      },
    };
    const form = initialValue(root, defs2) as Record<string, unknown>;
    expect(form.direction).toBe("LONG");
    expect(form.method).toBe("at_bar_close");
  });

  it("propertyMetas сообщает defaultValue для узла с $ref", () => {
    const root: SchemaNode = {
      type: "object",
      properties: { direction: { $ref: "#/$defs/Direction", default: "LONG" } },
    };
    const metas = propertyMetas(root, defs2);
    expect(metas[0].hasDefault).toBe(true);
    expect(metas[0].defaultValue).toBe("LONG");
  });
});

describe("REV1 B5 / MVP-7.2 I4: обязательные параметры индикаторов (движок не подставляет скрытых дефолтов)", () => {
  const catalog = new Map<string, IndicatorResponse>([
    [
      "SMA",
      {
        name: "SMA",
        series: ["value"],
        params: [],
        uses_period: true,
        uses_method: false,
        uses_series: false,
        uses_params: false,
        period_default: 20,
        period_default_source: "project",
      },
    ],
    [
      "MACD",
      {
        name: "MACD",
        series: ["macd", "signal", "histogram"],
        params: [
          { name: "fast", type: "int", required: true, default: 12, default_source: "project" },
          { name: "slow", type: "int", required: true, default: 26, default_source: "project" },
          { name: "signal", type: "int", required: true, default: 9, default_source: "project" },
        ],
        uses_period: false,
        uses_method: false,
        uses_series: true,
        uses_params: true,
        period_default: null,
        period_default_source: null,
      },
    ],
  ]);

  it("находит пустой период и пустые параметры каталога по нужным путям", () => {
    const config = {
      entry: {
        groups: [
          {
            conditions: [
              {
                arg1: { kind: "indicator", name: "SMA", timeframe: "5m", period: null },
                operator: ">",
                arg2: { kind: "constant", value: 100 },
              },
            ],
          },
        ],
      },
      dca_grid: {
        signal_groups: [
          {
            conditions: [
              {
                arg1: { kind: "constant", value: 1 },
                operator: ">",
                arg2: {
                  kind: "indicator",
                  name: "MACD",
                  timeframe: "5m",
                  series: "macd",
                  params: { fast: 12 },
                },
              },
            ],
          },
        ],
      },
    };
    const errors = collectMissingIndicatorArgs(config, catalog);
    expect(errors).toEqual({
      "entry.groups.0.conditions.0.arg1.period": expect.any(String),
      "dca_grid.signal_groups.0.conditions.0.arg2.params.slow": expect.any(String),
      "dca_grid.signal_groups.0.conditions.0.arg2.params.signal": expect.any(String),
    });
  });

  it("заполненные индикаторы и другие kind не порождают ошибок", () => {
    const config = {
      exit: {
        take_profit: {
          groups: [
            {
              conditions: [
                {
                  arg1: { kind: "indicator", name: "SMA", timeframe: "5m", period: 20 },
                  operator: "<",
                  arg2: { kind: "candle", series: "close", timeframe: "5m" },
                },
              ],
            },
          ],
        },
      },
    };
    expect(collectMissingIndicatorArgs(config, catalog)).toEqual({});
  });

  it("B1: нулевой/отрицательный период и целые параметры — ошибка у поля", () => {
    const base = {
      entry: {
        groups: [
          {
            conditions: [
              {
                arg1: { kind: "indicator", name: "SMA", timeframe: "5m" },
                operator: ">",
                arg2: { kind: "constant", value: 50 },
              },
            ],
          },
        ],
      },
    };
    for (const bad of [0, -5]) {
      const config = structuredClone(base);
      (config.entry.groups[0].conditions[0].arg1 as Record<string, unknown>).period = bad;
      const errors = collectMissingIndicatorArgs(config, catalog);
      expect(errors["entry.groups.0.conditions.0.arg1.period"]).toMatch(/целым числом не меньше 1/);
    }
    const macd = {
      dca_grid: {
        signal_groups: [
          {
            conditions: [
              {
                arg1: { kind: "indicator", name: "MACD", timeframe: "5m", params: { fast: 0, slow: 26, signal: 9 } },
                operator: ">",
                arg2: { kind: "constant", value: 0 },
              },
            ],
          },
        ],
      },
    };
    const errors = collectMissingIndicatorArgs(macd, catalog);
    expect(errors["dca_grid.signal_groups.0.conditions.0.arg1.params.fast"]).toMatch(
      /целым числом не меньше 1/,
    );
  });

  it("B1: числовая строка-целое допустима (JSON-режим), дробный период — ошибка", () => {
    const config = {
      entry: {
        groups: [
          {
            conditions: [
              {
                arg1: {
                  kind: "indicator",
                  name: "SMA",
                  timeframe: "5m",
                  period: "20",
                },
                operator: ">",
                arg2: { kind: "constant", value: 50 },
              },
            ],
          },
        ],
      },
    };
    expect(collectMissingIndicatorArgs(config, catalog)).toEqual({});
    (config.entry.groups[0].conditions[0].arg1 as Record<string, unknown>).period = 2.5;
    const errors = collectMissingIndicatorArgs(config, catalog);
    expect(errors["entry.groups.0.conditions.0.arg1.period"]).toMatch(/целым числом не меньше 1/);
  });

  it("без каталога валидация не блокирует (каталог недоступен — редактор покажет ошибку)", () => {
    const config = { entry: { groups: [] } };
    expect(collectMissingIndicatorArgs(config, null)).toEqual({});
  });
});
