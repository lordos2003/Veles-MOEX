import type { IndicatorResponse, SchemaNode } from "../types";
import { initialValueForVariant, isPlainObject } from "../lib/schema";
import {
  ARG_KIND_OPTIONS,
  OPERATOR_OPTIONS,
  SERIES_OPTIONS,
  TIMEFRAME_OPTIONS,
  labelFor,
} from "../lib/labels";
import { Button, Field, NumberInput, SelectInput, TextInput } from "./FormControls";

export type Catalog = Map<string, IndicatorResponse> | null;
export type CatalogError = string | null;

interface EditorProps {
  /** Groups array (mutated through onChange). */
  groups: Record<string, unknown>[];
  onChange: (groups: Record<string, unknown>[]) => void;
  /** Dotted prefix for a group index, e.g. "entry.groups". */
  pathPrefix: string;
  catalog: Catalog;
  catalogError: CatalogError;
  /** Errors by dotted path (422 mapping). */
  errors?: Record<string, string>;
  disabled?: boolean;
}

function at<T>(arr: T[] | undefined, i: number): T {
  if (!arr || !arr[i]) return {} as T;
  return arr[i];
}

function getPathError(errors: Record<string, string> | undefined, path: string): string | null {
  return errors?.[path] ?? null;
}

/** Checks `a == b` for the display of the active operator. */
export function FilterGroupEditor(props: EditorProps) {
  const { groups, onChange, pathPrefix, catalog, catalogError, errors } = props;

  const updateGroup = (groupIndex: number, group: Record<string, unknown>) => {
    const next = groups.map((g, i) => (i === groupIndex ? group : g));
    onChange(next);
  };

  const removeGroup = (groupIndex: number) => {
    onChange(groups.filter((_, i) => i !== groupIndex));
  };

  const addGroup = () => {
    onChange([...groups, { conditions: [] }]);
  };

  return (
    <div className="space-y-3">
      {groups.map((group, gi) => {
        const conditions = (group.conditions as Record<string, unknown>[]) ?? [];
        const groupPath = `${pathPrefix}.${gi}`;
        return (
          <div key={gi} className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-400">
                Группа {gi + 1} {gi > 0 ? "(ИЛИ с предыдущими)" : ""}
              </span>
              <Button variant="ghost" onClick={() => removeGroup(gi)} disabled={props.disabled}>
                Удалить группу
              </Button>
            </div>
            <div className="space-y-3">
              {conditions.map((_condition, ci) => {
                const condPath = `${groupPath}.conditions.${ci}`;
                return (
                  <div key={ci} className="rounded border border-zinc-800 p-2">
                    <div className="mb-2 flex justify-end">
                      <Button
                        variant="ghost"
                        disabled={props.disabled}
                        onClick={() => {
                          const next = conditions.filter((_, i) => i !== ci);
                          updateGroup(gi, { ...group, conditions: next });
                        }}
                      >
                        Удалить условие
                      </Button>
                    </div>
                    <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
                      <ArgumentEditor
                        label={labelFor("arg1")}
                        pathPrefix={`${condPath}.arg1`}
                        value={at(conditions, ci).arg1 as Record<string, unknown>}
                        onChange={(arg1) => {
                          const next = conditions.map((c, i) => (i === ci ? { ...c, arg1 } : c));
                          updateGroup(gi, { ...group, conditions: next });
                        }}
                        catalog={catalog}
                        catalogError={catalogError}
                        errors={errors}
                        disabled={props.disabled}
                      />
                      <Field
                        label={labelFor("operator")}
                        error={getPathError(errors, `${condPath}.operator`)}
                        required
                      >
                        <SelectInput
                          value={at(conditions, ci).operator}
                          options={OPERATOR_OPTIONS}
                          allowEmpty
                          onChange={(operator) => {
                            const next = conditions.map((c, i) =>
                              i === ci ? { ...c, operator } : c,
                            );
                            updateGroup(gi, { ...group, conditions: next });
                          }}
                          disabled={props.disabled}
                        />
                      </Field>
                      <ArgumentEditor
                        label={labelFor("arg2")}
                        pathPrefix={`${condPath}.arg2`}
                        value={at(conditions, ci).arg2 as Record<string, unknown>}
                        onChange={(arg2) => {
                          const next = conditions.map((c, i) => (i === ci ? { ...c, arg2 } : c));
                          updateGroup(gi, { ...group, conditions: next });
                        }}
                        catalog={catalog}
                        catalogError={catalogError}
                        errors={errors}
                        disabled={props.disabled}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-2">
              <Button
                variant="ghost"
                disabled={props.disabled}
                onClick={() => {
                  updateGroup(gi, {
                    ...group,
                    conditions: [...conditions, { arg1: {}, operator: undefined, arg2: {} }],
                  });
                }}
              >
                + Условие
              </Button>
            </div>
          </div>
        );
      })}
      <Button variant="ghost" onClick={addGroup} disabled={props.disabled}>
        + Группа фильтров
      </Button>
    </div>
  );
}

function ArgumentEditor(props: {
  label: string;
  pathPrefix: string;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  catalog: Catalog;
  catalogError: CatalogError;
  errors?: Record<string, string>;
  disabled?: boolean;
}) {
  const { label, value, onChange, pathPrefix, catalog, catalogError, errors, disabled } = props;
  const kind = typeof value.kind === "string" ? value.kind : undefined;

  return (
    <div className="space-y-2 rounded border border-zinc-800 p-2">
      <Field label={label} error={getPathError(errors, pathPrefix)} required>
        <SelectInput
          value={kind}
          options={ARG_KIND_OPTIONS}
          allowEmpty
          disabled={disabled}
          onChange={(selected) => {
            const variant = ARG_KIND_VARIANTS[selected];
            if (!variant) {
              onChange({});
              return;
            }
            const init = initialValueForVariant(variant);
            onChange(init as Record<string, unknown>);
          }}
        />
      </Field>
      {kind === "constant" ? (
        <Field
          label={labelFor("constant.value")}
          error={getPathError(errors, `${pathPrefix}.value`)}
          required
        >
          <NumberInput
            value={value.value as number | null}
            disabled={disabled}
            onChange={(v) => onChange({ ...value, value: v })}
          />
        </Field>
      ) : null}
      {kind === "indicator" ? (
        <IndicatorArgs
          pathPrefix={pathPrefix}
          value={value}
          onChange={onChange}
          catalog={catalog}
          catalogError={catalogError}
          errors={errors}
          disabled={disabled}
        />
      ) : null}
      {kind === "candle" ? (
        <>
          <Field
            label={labelFor("candle.timeframe")}
            error={getPathError(errors, `${pathPrefix}.timeframe`)}
            required
          >
            <SelectInput
              value={value.timeframe}
              options={TIMEFRAME_OPTIONS}
              allowEmpty
              disabled={disabled}
              onChange={(timeframe) => onChange({ ...value, timeframe })}
            />
          </Field>
          <Field label={labelFor("candle.series")}>
            <SelectInput
              value={value.series ?? "close"}
              options={SERIES_OPTIONS}
              disabled={disabled}
              onChange={(series) => onChange({ ...value, series })}
            />
          </Field>
          <Field label={labelFor("candle.shift")}>
            <NumberInput
              value={value.shift as number | null}
              disabled={disabled}
              onChange={(shift) => onChange({ ...value, shift })}
            />
          </Field>
        </>
      ) : null}
      {catalogError ? (
        <p className="text-xs text-amber-400">Каталог индикаторов недоступен: {catalogError}</p>
      ) : null}
    </div>
  );
}

function IndicatorArgs(props: {
  pathPrefix: string;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  catalog: Catalog;
  catalogError: CatalogError;
  errors?: Record<string, string>;
  disabled?: boolean;
}) {
  const { pathPrefix, value, onChange, catalog, errors, disabled } = props;
  const name = typeof value.name === "string" ? value.name : "";
  const entry = catalog?.get(name) ?? null;

  const setName = (n: string) => onChange({ ...value, name: n });
  const setField = (key: string, v: unknown) => onChange({ ...value, [key]: v });
  const setParam = (key: string, v: number | null) => {
    const params = { ...((value.params as Record<string, unknown>) ?? {}) };
    if (v === null) delete params[key];
    else params[key] = v;
    onChange({ ...value, params });
  };

  return (
    <>
      <Field
        label={labelFor("indicator.name")}
        error={getPathError(errors, `${pathPrefix}.name`)}
        required
      >
        {catalog ? (
          <SelectInput
            value={name}
            options={[...catalog.values()].map((i) => ({ value: i.name, label: i.name }))}
            allowEmpty
            disabled={disabled}
            onChange={setName}
          />
        ) : (
          <TextInput value={name} onChange={setName} disabled={disabled} />
        )}
      </Field>
      <Field
        label={labelFor("indicator.timeframe")}
        error={getPathError(errors, `${pathPrefix}.timeframe`)}
        required
      >
        <SelectInput
          value={value.timeframe}
          options={TIMEFRAME_OPTIONS}
          allowEmpty
          disabled={disabled}
          onChange={(timeframe) => setField("timeframe", timeframe)}
        />
      </Field>
      {entry?.uses_period ? (
        <Field
          label={labelFor("indicator.period")}
          error={getPathError(errors, `${pathPrefix}.period`)}
          required
        >
          <NumberInput
            value={value.period as number | null}
            disabled={disabled}
            onChange={(period) => setField("period", period)}
          />
        </Field>
      ) : null}
      {entry?.uses_method ? (
        <Field label={labelFor("indicator.method")}>
          <TextInput
            value={(value.method as string) ?? ""}
            disabled={disabled}
            onChange={(method) => setField("method", method)}
          />
        </Field>
      ) : null}
      {entry?.uses_series ? (
        <Field label={labelFor("indicator.series")}>
          <SelectInput
            value={value.series ?? "value"}
            options={entry.series.map((s) => ({ value: s, label: s }))}
            disabled={disabled}
            onChange={(series) => setField("series", series)}
          />
        </Field>
      ) : null}
      <Field label={labelFor("indicator.shift")}>
        <NumberInput
          value={value.shift as number | null}
          disabled={disabled}
          onChange={(shift) => setField("shift", shift)}
        />
      </Field>
      {entry && entry.params.length > 0 ? (
        <div className="space-y-2 rounded border border-zinc-800 p-2">
          <p className="text-xs text-zinc-400">Параметры индикатора</p>
          {entry.params.map((param) => (
            <Field
              key={param.name}
              label={param.name}
              error={getPathError(errors, `${pathPrefix}.params.${param.name}`)}
              required
            >
              <NumberInput
                value={((value.params as Record<string, unknown>) ?? {})[param.name] as
                  | number
                  | null}
                disabled={disabled}
                onChange={(v) => setParam(param.name, v)}
              />
            </Field>
          ))}
          {value.params && typeof value.params === "object"
            ? Object.keys(value.params as Record<string, unknown>)
                .filter((k) => !entry.params.some((p) => p.name === k))
                .map((extra) => (
                  <Field key={extra} label={extra}>
                    <NumberInput
                      value={((value.params as Record<string, unknown>)[extra] as number) ?? null}
                      disabled={disabled}
                      onChange={(v) => setParam(extra, v)}
                    />
                  </Field>
                ))
            : null}
        </div>
      ) : null}
    </>
  );
}

// Variants resolved once (kind -> initial value factory); schema-independent
// because argument kinds are fixed by the engine (constant/indicator/candle).
const ARG_KIND_VARIANTS: Record<string, { kind: string; node: SchemaNode }> = {
  constant: { kind: "constant", node: { type: "object", properties: { kind: { const: "constant", default: "constant" }, value: { type: "number" } } } },
  indicator: { kind: "indicator", node: { type: "object", properties: { kind: { const: "indicator", default: "indicator" }, name: { type: "string" }, timeframe: { type: "string" }, period: { type: "integer", default: null }, method: { type: "string", default: null }, shift: { type: "integer", default: 0 }, series: { type: "string", default: "value" }, params: { type: "object" } } } },
  candle: { kind: "candle", node: { type: "object", properties: { kind: { const: "candle", default: "candle" }, series: { type: "string", default: "close" }, timeframe: { type: "string" }, shift: { type: "integer", default: 0 } } } },
} as const;

/**
 * B5: the calculation engine falls back to hidden defaults (SMA 20, RSI 14,
 * MACD 12/26/9, ...) when an indicator argument is empty, so the form must not
 * submit a strategy with missing period/catalog params.
 *
 * Recursively walks the config, finds every `{ kind: "indicator", name }` node
 * and returns errors keyed by the same dotted paths Field components use.
 */
export function collectMissingIndicatorArgs(
  value: unknown,
  catalog: Catalog,
  path = "",
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!catalog || value === null || value === undefined) return errors;

  const visit = (node: unknown, nodePath: string): void => {
    if (Array.isArray(node)) {
      node.forEach((item, i) => visit(item, `${nodePath}.${i}`));
      return;
    }
    if (!isPlainObject(node)) return;
    if (node.kind === "indicator" && typeof node.name === "string") {
      const entry = catalog.get(node.name);
      if (entry) {
        if (entry.uses_period && node.period == null) {
          errors[`${nodePath}.period`] = "Укажите период индикатора.";
        }
        const params = isPlainObject(node.params) ? node.params : {};
        for (const param of entry.params) {
          if (params[param.name] == null) {
            errors[`${nodePath}.params.${param.name}`] = `Укажите параметр «${param.name}».`;
          }
        }
      }
    }
    for (const [key, child] of Object.entries(node)) {
      visit(child, nodePath === "" ? key : `${nodePath}.${key}`);
    }
  };

  visit(value, path);
  return errors;
}
