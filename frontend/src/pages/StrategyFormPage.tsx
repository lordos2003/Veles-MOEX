import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, fieldErrors, verbatimMessage } from "../api";
import type { IndicatorResponse, InstrumentInfo, SchemaNode, StrategyValidateResponse } from "../types";
import {
  compact,
  deepClone,
  formFromConfig,
  initialValue,
  initialValueForVariant,
  isPlainObject,
  metaOf,
  nullableOf,
  propertyMetas,
  resolveRef,
} from "../lib/schema";
import {
  DIRECTION_OPTIONS,
  GRID_MODE_OPTIONS,
  SIGNAL_OFFSET_OPTIONS,
  STOP_REFERENCE_OPTIONS,
  TIMEFRAME_OPTIONS,
  TP_KIND_OPTIONS,
  hintFor,
  labelFor,
} from "../lib/labels";
import {
  Button,
  CheckboxInput,
  ErrorBanner,
  Field,
  Loading,
  NullableBoolInput,
  NumberInput,
  Section,
  SelectInput,
  TextInput,
} from "../components/FormControls";
import { FilterGroupEditor, collectMissingIndicatorArgs } from "../components/FilterGroupEditor";
import { InstrumentPicker } from "../components/InstrumentPicker";
import { PageHeader } from "../components/PageHeader";

type Config = Record<string, unknown>;
type Defs = Record<string, SchemaNode>;

function pathError(errors: Record<string, string> | undefined, path: string): string | null {
  return errors?.[path] ?? null;
}

export function StrategyFormPage(props: { edit?: boolean }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const edit = props.edit === true;
  const strategyId = id ? Number(id) : null;

  const [schema, setSchema] = useState<SchemaNode | null>(null);
  const [defs, setDefs] = useState<Defs>({});
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<Map<string, IndicatorResponse> | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [instruments, setInstruments] = useState<InstrumentInfo[]>([]);

  const [form, setForm] = useState<Config>({});
  const [description, setDescription] = useState<string>("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [liveVerdict, setLiveVerdict] = useState<StrategyValidateResponse["live_deal"] | null>(null);
  const [validated, setValidated] = useState(false);

  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // --- load schema + catalog + existing strategy ---
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const full = await api.get<{ $defs: Defs } & SchemaNode>("/api/strategies/schema");
        if (cancelled) return;
        setSchema(full);
        setDefs(full.$defs ?? {});
      } catch (err) {
        if (!cancelled) setSchemaError(err instanceof Error ? err.message : String(err));
      }
      try {
        const list = await api.get<IndicatorResponse[]>("/api/strategies/indicators");
        if (!cancelled) setCatalog(new Map(list.map((i) => [i.name, i])));
      } catch (err) {
        if (!cancelled) setCatalogError(err instanceof Error ? err.message : String(err));
      }
      try {
        // U9: the «Ценная бумага» picker sources active instruments the same
        // way as «Обзор» (U2 MVP-7.4).
        const list = await api.get<InstrumentInfo[]>("/api/instruments?active=true");
        if (!cancelled) setInstruments(list);
      } catch {
        // Leave the list empty: the field shows «не загружены», no fabrication.
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (edit && strategyId !== null) {
      api
        .get<{ config: Record<string, unknown>; description: string | null }>(
          `/api/strategies/${strategyId}`,
        )
        .then((s) => {
          setForm(formFromConfig(s.config ?? {}) as Config);
          setDescription(s.description ?? "");
          setLoaded(true);
        })
        .catch((err) => setSaveError(err instanceof Error ? err.message : String(err)));
    }
    // New strategy: `loaded` is left to the schema-init effect below, so the
    // form is built from schema defaults (B4) — never shown before the schema
    // arrives.
  }, [edit, strategyId]);

  // --- initialize form from schema (B4): a NEW strategy starts from schema
  // `default`s (the UI never invents values). In edit mode the stored config
  // above already set `loaded`, so this effect is a no-op there. ---
  useEffect(() => {
    if (!schema || loaded) return;
    const form = initialValue(schema, defs) as Config;
    // F1 (MVP-7.6, M1 from MVP-7.5): `lookback_bars` has `default: null` in
    // the schema so old strategies keep working, but the UI must neither show
    // nor send the key — the engine computes the depth (H1). Edit mode keeps
    // whatever the stored config holds (explicit values are preserved).
    if (isPlainObject(form) && form.lookback_bars === null) {
      delete form.lookback_bars;
    }
    setForm(form);
    setLoaded(true);
  }, [schema, defs, loaded]);

  const setField = useCallback((path: string, value: unknown) => {
    setForm((prev) => {
      const next = deepClone(prev);
      const parts = path.split(".");
      let node: Config = next;
      for (let i = 0; i < parts.length - 1; i += 1) {
        const part = parts[i];
        if (typeof node[part] !== "object" || node[part] === null) node[part] = {};
        node = node[part] as Config;
      }
      node[parts[parts.length - 1]] = value;
      return next;
    });
    setErrors((prev) => {
      if (!(path in prev)) return prev;
      const next = { ...prev };
      delete next[path];
      return next;
    });
  }, []);

  // --- JSON <-> form sync ---
  useEffect(() => {
    if (!jsonMode) return;
    setJsonText(JSON.stringify(compact(form), null, 2));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jsonMode]);

  const onJsonChange = (text: string) => {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as unknown;
      setJsonError(null);
      setForm(deepClone(parsed) as Config);
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : String(err));
    }
  };

  /** B5: refuse to send a config with missing indicator args (engine fills hidden defaults). */
  const requireIndicatorArgs = (): boolean => {
    const missing = collectMissingIndicatorArgs(compact(form), catalog);
    if (Object.keys(missing).length === 0) return true;
    setErrors(missing);
    setSaveError("Заполните обязательные параметры индикаторов (период и параметры).");
    return false;
  };

  const runValidate = async () => {
    setSaveError(null);
    if (!requireIndicatorArgs()) return;
    try {
      // U5: the endpoint takes the bare config (API contract R4 unchanged);
      // the old `{"config": ...}` wrapper made every «Проверить» click 422.
      const result = await api.post<StrategyValidateResponse>(
        "/api/strategies/validate",
        compact(form),
      );
      setLiveVerdict(result.live_deal);
      setValidated(true);
      setErrors({});
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(fieldErrors(err.detail));
        setSaveError(verbatimMessage(err.detail));
      } else {
        setSaveError(err instanceof Error ? err.message : String(err));
      }
    }
  };

  const save = async () => {
    if (!requireIndicatorArgs()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const config = compact(form) as Config;
      if (edit && strategyId !== null) {
        await api.put(`/api/strategies/${strategyId}`, {
          name: typeof config.name === "string" ? config.name : undefined,
          description: description || undefined,
          config,
        });
        navigate(`/strategies/${strategyId}`);
      } else {
        const created = await api.post<{ id: number }>("/api/strategies", {
          name: typeof config.name === "string" ? config.name : "",
          description: description || undefined,
          config,
        });
        navigate(`/strategies/${created.id}`);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(fieldErrors(err.detail));
        setSaveError(verbatimMessage(err.detail));
      } else {
        setSaveError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setSaving(false);
    }
  };

  if (schemaError) {
    return <ErrorBanner text={`Схема стратегии недоступна: ${schemaError}`} />;
  }
  if (!schema || !loaded) return <Loading text="Загрузка формы…" />;

  const config = form;
  const entry = (config.entry as Config) ?? {};
  const dca = (config.dca_grid as Config) ?? {};
  const exit = (config.exit as Config) ?? {};
  const risk = (config.risk as Config) ?? {};

  // U9: the form keeps `instrument_id` (local id) in the config, but shows
  // the paper by its ticker/name label — or falls back to "#id" when the
  // paper is no longer in the active list.
  const chosenInstrument =
    config.instrument_id === null || config.instrument_id === undefined
      ? undefined
      : instruments.find((i) => i.id === Number(config.instrument_id));
  const instrumentFigi = chosenInstrument ? chosenInstrument.figi : "";
  const onSelectInstrument = (figi: string) => {
    const inst = instruments.find((i) => i.figi === figi);
    setField("instrument_id", inst ? inst.id : null);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={edit ? "Стратегия — редактирование" : "Новая стратегия"}
        actions={
          <>
              <Button variant="ghost" onClick={() => navigate(edit && strategyId !== null ? `/strategies/${strategyId}` : "/strategies")}>
                Назад
              </Button>
              <Button variant="ghost" onClick={() => setJsonMode(!jsonMode)}>
                {jsonMode ? "Форма" : "JSON"}
              </Button>
              <Button variant="ghost" onClick={() => void runValidate()} disabled={jsonError !== null}>
                Проверить
              </Button>
              <Button onClick={() => void save()} disabled={saving || jsonError !== null}>
                {saving ? "Сохранение…" : edit ? "Сохранить (новая версия)" : "Создать"}
              </Button>
          </>
        }
      />

      <ErrorBanner text={saveError} />

      {liveVerdict && validated ? (
        liveVerdict.supported ? (
          <div className="rounded-control border border-success-border bg-success-soft/70 px-3 py-2 text-sm text-success">
            Для живой торговли подходит.
          </div>
        ) : (
          <div className="rounded-control border border-warning-border bg-warning-soft/70 px-3 py-2 text-sm text-warning">
            Только бэктест: {liveVerdict.reason ?? "конфигурация не поддерживается живым циклом"}
          </div>
        )
      ) : null}

      {jsonMode ? (
        <div className="space-y-2">
          <p className="text-xs text-text-muted">
            Правка конфигурации текстом. Изменения синхронны с формой; невалидный JSON не
            сохраняется.
          </p>
          <textarea
            className="min-h-8 h-[28rem] w-full rounded-control border border-border bg-sunken p-3 font-mono text-xs text-text"
            value={jsonText}
            onChange={(e) => onJsonChange(e.target.value)}
            spellCheck={false}
            aria-label="Конфигурация (JSON)"
          />
          {jsonError ? <p className="text-xs text-error">JSON: {jsonError}</p> : null}
        </div>
      ) : (
        <div className="space-y-4">
          <Section title={labelFor("name")}>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Field label={labelFor("name")} required error={pathError(errors, "name")}>
                <TextInput
                  value={(config.name as string) ?? ""}
                  onChange={(v) => setField("name", v)}
                />
              </Field>
              <Field label={labelFor("description")}>
                <TextInput value={description} onChange={setDescription} />
              </Field>
              <Field label={labelFor("direction")}>
                <SelectInput
                  value={config.direction}
                  options={DIRECTION_OPTIONS}
                  allowEmpty
                  onChange={(v) => setField("direction", v)}
                />
              </Field>
              <Field label={labelFor("timeframe")} hint="Таймфрейм данных для живого цикла">
                <SelectInput
                  value={config.timeframe}
                  options={TIMEFRAME_OPTIONS}
                  allowEmpty
                  onChange={(v) => setField("timeframe", v === "" ? null : v)}
                />
              </Field>
              <Field
                label={labelFor("instrument_id")}
                error={pathError(errors, "instrument_id")}
              >
                {instruments.length === 0 ? (
                  <p className="text-sm text-text-muted">Инструменты не загружены.</p>
                ) : (
                  <InstrumentPicker
                    instruments={instruments}
                    selectedFigi={instrumentFigi}
                    onSelect={onSelectInstrument}
                    fallbackLabel={
                      config.instrument_id === null || config.instrument_id === undefined
                        ? ""
                        : `#${String(config.instrument_id)}`
                    }
                    listId="strategy-form-instrument-results"
                  />
                )}
              </Field>
            </div>
          </Section>

          <Section title={labelFor("entry")}>
            <Field label={labelFor("entry.method")} hint={hintFor("entry.method")}>
              <SelectInput
                value={entry.method}
                options={[
                  { value: "at_bar_close", label: "По закрытию бара" },
                  { value: "per_minute", label: "Раз в минуту" },
                ]}
                allowEmpty
                onChange={(v) => setField("entry.method", v === "" ? undefined : v)}
              />
            </Field>
            <Field label={labelFor("entry.groups")} hint="Между группами — ИЛИ, внутри — И">
              <FilterGroupEditor
                groups={(entry.groups as Config[]) ?? []}
                onChange={(groups) => setField("entry.groups", groups)}
                pathPrefix="entry.groups"
                catalog={catalog}
                catalogError={catalogError}
                errors={errors}
              />
            </Field>
          </Section>

          <Section title={labelFor("dca_grid")}>
            <Field label={labelFor("dca_grid.mode")} error={pathError(errors, "dca_grid.mode")}>
              <SelectInput
                value={dca.mode}
                options={GRID_MODE_OPTIONS}
                allowEmpty
                onChange={(v) => setField("dca_grid.mode", v === "" ? undefined : v)}
              />
            </Field>
            {dca.mode === "signal" ? (
              <>
                <Field label={labelFor("dca_grid.signal_groups")}>
                  <FilterGroupEditor
                    groups={(dca.signal_groups as Config[]) ?? []}
                    onChange={(groups) => setField("dca_grid.signal_groups", groups)}
                    pathPrefix="dca_grid.signal_groups"
                    catalog={catalog}
                    catalogError={catalogError}
                    errors={errors}
                  />
                </Field>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <Field label={labelFor("dca_grid.signal_offset_type")}>
                    <SelectInput
                      value={dca.signal_offset_type}
                      options={SIGNAL_OFFSET_OPTIONS}
                      allowEmpty
                      onChange={(v) => setField("dca_grid.signal_offset_type", v === "" ? undefined : v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.signal_min_offset_percent")}>
                    <NumberInput
                      value={dca.signal_min_offset_percent as number | null}
                      onChange={(v) => setField("dca_grid.signal_min_offset_percent", v)}
                    />
                  </Field>
                </div>
              </>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <Field label={labelFor("dca_grid.levels")} hint="Число ордеров сетки (≥1)">
                    <NumberInput
                      value={dca.levels as number | null}
                      onChange={(v) => setField("dca_grid.levels", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.overlap_percent")} hint="Диапазон между первым и последним ордером сетки">
                    <NumberInput
                      value={dca.overlap_percent as number | null}
                      onChange={(v) => setField("dca_grid.overlap_percent", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.spacing_percent")}>
                    <NumberInput
                      value={dca.spacing_percent as number | null}
                      onChange={(v) => setField("dca_grid.spacing_percent", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.martingale_percent")}>
                    <NumberInput
                      value={dca.martingale_percent as number | null}
                      onChange={(v) => setField("dca_grid.martingale_percent", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.logarithmic_factor")} hint=">1 — плотнее у цены; <1 — плотнее дальше">
                    <NumberInput
                      value={dca.logarithmic_factor as number | null}
                      onChange={(v) => setField("dca_grid.logarithmic_factor", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.first_order_offset_percent")} hint="Лонг — ниже цены, шорт — выше">
                    <NumberInput
                      value={dca.first_order_offset_percent as number | null}
                      onChange={(v) => setField("dca_grid.first_order_offset_percent", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.pull_up_percent")}>
                    <NumberInput
                      value={dca.pull_up_percent as number | null}
                      onChange={(v) => setField("dca_grid.pull_up_percent", v)}
                    />
                  </Field>
                  <Field label={labelFor("dca_grid.active_limit")}>
                    <NumberInput
                      value={dca.active_limit as number | null}
                      onChange={(v) => setField("dca_grid.active_limit", v)}
                    />
                  </Field>
                </div>
                {dca.mode === "custom" ? (
                  <CustomLevelsEditor
                    levels={dca.custom_levels as Config[] | undefined}
                    onChange={(levels) => setField("dca_grid.custom_levels", levels)}
                    errors={errors}
                  />
                ) : null}
                {catalogError ? (
                  <ErrorBanner text={`Каталог индикаторов недоступен: ${catalogError}`} />
                ) : null}
              </>
            )}
          </Section>

          <Section title={labelFor("exit")}>
            <TakeProfitEditor
              value={exit.take_profit as Config}
              onChange={(v) => setField("exit.take_profit", v)}
              errors={errors}
              catalog={catalog}
              catalogError={catalogError}
            />
            <StopItem
              title={labelFor("exit.stop_loss")}
              enabled={exit.stop_loss !== null && exit.stop_loss !== undefined}
              onEnable={(on) => {
                if (on) {
                  setField("exit.stop_loss", { kind: "percent", percent: undefined, stop_bot_after: null });
                } else {
                  setField("exit.stop_loss", null);
                }
              }}
            >
              <Field
                label={labelFor("exit.stop_loss.percent")}
                hint={hintFor("exit.stop_loss.percent")}
                error={pathError(errors, "exit.stop_loss.percent")}
                required
              >
                <NumberInput
                  value={(exit.stop_loss as Config)?.percent as number | null}
                  onChange={(v) => setField("exit.stop_loss.percent", v)}
                />
              </Field>
              <Field label={labelFor("exit.stop_loss.stop_bot_after")} hint={hintFor("exit.stop_loss.stop_bot_after")}>
                <NullableBoolInput
                  value={(exit.stop_loss as Config)?.stop_bot_after as boolean | null}
                  onChange={(v) => setField("exit.stop_loss.stop_bot_after", v)}
                />
              </Field>
            </StopItem>
            <StopItem
              title={labelFor("exit.signal_stop")}
              enabled={exit.signal_stop !== null && exit.signal_stop !== undefined}
              onEnable={(on) => {
                if (on) setField("exit.signal_stop", { kind: "signal", groups: [], reference: undefined, min_offset_percent: 0.0, offset_enabled: true });
                else setField("exit.signal_stop", null);
              }}
            >
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Field label={labelFor("exit.signal_stop.reference")}>
                  <SelectInput
                    value={(exit.signal_stop as Config)?.reference}
                    options={STOP_REFERENCE_OPTIONS}
                    allowEmpty
                    onChange={(v) => setField("exit.signal_stop.reference", v === "" ? undefined : v)}
                  />
                </Field>
                <Field label={labelFor("min_offset_percent")}>
                  <NumberInput
                    value={(exit.signal_stop as Config)?.min_offset_percent as number | null}
                    onChange={(v) => setField("exit.signal_stop.min_offset_percent", v)}
                  />
                </Field>
              </div>
              <Field label={labelFor("offset_enabled")}>
                <CheckboxInput
                  value={(exit.signal_stop as Config)?.offset_enabled === true}
                  onChange={(v) => setField("exit.signal_stop.offset_enabled", v)}
                />
              </Field>
              <FilterGroupEditor
                groups={((exit.signal_stop as Config)?.groups as Config[]) ?? []}
                onChange={(groups) => setField("exit.signal_stop.groups", groups)}
                pathPrefix="exit.signal_stop.groups"
                catalog={catalog}
                catalogError={catalogError}
                errors={errors}
              />
            </StopItem>
          </Section>

          <Section title={labelFor("risk")}>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Field label={labelFor("risk.max_position_size")}>
                <NumberInput
                  value={risk.max_position_size as number | null}
                  onChange={(v) => setField("risk.max_position_size", v)}
                />
              </Field>
              <Field label={labelFor("risk.max_concurrent_bots")}>
                <NumberInput
                  value={risk.max_concurrent_bots as number | null}
                  onChange={(v) => setField("risk.max_concurrent_bots", v)}
                />
              </Field>
              <Field label={labelFor("risk.daily_loss_limit")}>
                <NumberInput
                  value={risk.daily_loss_limit as number | null}
                  onChange={(v) => setField("risk.daily_loss_limit", v)}
                />
              </Field>
              <Field label={labelFor("risk.emergency_stop")}>
                <CheckboxInput
                  value={risk.emergency_stop === true}
                  onChange={(v) => setField("risk.emergency_stop", v)}
                />
              </Field>
            </div>
          </Section>

          {/* Unknown schema fields are rendered generically (U4): never lost. */}
          <UnknownFields
            schema={schema}
            defs={defs}
            form={config}
            setField={setField}
          />
        </div>
      )}
    </div>
  );
}

function CustomLevelsEditor(props: {
  levels: Config[] | undefined;
  onChange: (levels: Config[]) => void;
  errors: Record<string, string>;
}) {
  const levels = props.levels ?? [];
  const update = (i: number, key: string, value: unknown) => {
    const next = levels.map((l, idx) => (idx === i ? { ...l, [key]: value } : l));
    props.onChange(next);
  };
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-text-secondary">{labelFor("dca_grid.custom_levels")}</p>
      {levels.map((level, i) => (
        <div key={i} className="flex items-end gap-2 rounded-control border border-border-soft p-2">
          <Field label={`Уровень ${i + 1} — ${labelFor("offset_percent")}`} error={pathError(props.errors, `dca_grid.custom_levels.${i}.offset_percent`)} required>
            <NumberInput
              value={level.offset_percent as number | null}
              onChange={(v) => update(i, "offset_percent", v)}
            />
          </Field>
          <Field label={labelFor("nominal_percent")} error={pathError(props.errors, `dca_grid.custom_levels.${i}.nominal_percent`)} required>
            <NumberInput
              value={level.nominal_percent as number | null}
              onChange={(v) => update(i, "nominal_percent", v)}
            />
          </Field>
          <Button
            variant="ghost"
            onClick={() => props.onChange(levels.filter((_, idx) => idx !== i))}
          >
            Удалить
          </Button>
        </div>
      ))}
      <Button variant="ghost" onClick={() => props.onChange([...levels, {}])}>
        + Уровень
      </Button>
    </div>
  );
}

function StopItem(props: {
  title: string;
  enabled: boolean;
  onEnable: (enabled: boolean) => void;
  children: ReactNode;
}) {
  return (
    <div className="rounded-control border border-border-soft p-3">
      <label className="flex min-h-8 cursor-pointer items-center gap-2 text-sm font-medium text-text">
        <input
          type="checkbox"
          checked={props.enabled}
          onChange={(e) => props.onEnable(e.target.checked)}
          className="h-4 w-4 accent-accent-bright"
        />
        {props.title}
      </label>
      {props.enabled ? <div className="mt-3 space-y-3">{props.children}</div> : null}
    </div>
  );
}

function TakeProfitEditor(props: {
  value: Config | undefined;
  onChange: (value: Config) => void;
  errors: Record<string, string>;
  catalog: Map<string, IndicatorResponse> | null;
  catalogError: string | null;
}) {
  const value = props.value ?? {};
  const kind = typeof value.kind === "string" ? value.kind : "";

  const setKind = (selected: string) => {
    const variant = TP_VARIANTS[selected];
    if (!variant) {
      props.onChange({});
      return;
    }
    props.onChange(initialValueForVariant(variant) as Config);
  };

  return (
    <div className="rounded-control border border-border-soft p-3">
      <Field label={labelFor("exit.take_profit")} required error={pathError(props.errors, "exit.take_profit")}>
        <SelectInput value={kind} options={TP_KIND_OPTIONS} allowEmpty onChange={setKind} />
      </Field>
      {kind === "fixed_percentage" ? (
        <Field
          label="Процент прибыли"
          hint={hintFor("exit.take_profit.percent")}
          error={pathError(props.errors, "exit.take_profit.percent")}
          required
        >
          <NumberInput
            value={value.percent as number | null}
            onChange={(v) => props.onChange({ ...value, percent: v })}
          />
        </Field>
      ) : null}
      {kind === "multi_take" ? (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-medium text-text-secondary">{labelFor("takes")}</p>
          {((value.takes as Config[]) ?? []).map((take, i) => (
            <div key={i} className="flex items-end gap-2 rounded-control border border-border-soft p-2">
              <Field label={labelFor("offset_percent")} error={pathError(props.errors, `exit.take_profit.takes.${i}.offset_percent`)} required>
                <NumberInput
                  value={take.offset_percent as number | null}
                  onChange={(v) => {
                    const takes = (value.takes as Config[]).map((t, idx) => (idx === i ? { ...t, offset_percent: v } : t));
                    props.onChange({ ...value, takes });
                  }}
                />
              </Field>
              <Field label={labelFor("volume_percent")} error={pathError(props.errors, `exit.take_profit.takes.${i}.volume_percent`)} required>
                <NumberInput
                  value={take.volume_percent as number | null}
                  onChange={(v) => {
                    const takes = (value.takes as Config[]).map((t, idx) => (idx === i ? { ...t, volume_percent: v } : t));
                    props.onChange({ ...value, takes });
                  }}
                />
              </Field>
              <Button
                variant="ghost"
                onClick={() =>
                  props.onChange({ ...value, takes: (value.takes as Config[]).filter((_, idx) => idx !== i) })
                }
              >
                Удалить
              </Button>
            </div>
          ))}
          <Button
            variant="ghost"
            onClick={() => props.onChange({ ...value, takes: [...((value.takes as Config[]) ?? []), {}] })}
          >
            + Частичный тейк
          </Button>
          <Field label={labelFor("breakeven")}>
            <NumberInput
              value={value.breakeven === null ? null : (value.breakeven as Config)?.deviation_percent as number | null}
              onChange={(v) => {
                if (v === null) props.onChange({ ...value, breakeven: null });
                else props.onChange({ ...value, breakeven: { reference: "average_price", deviation_percent: v } });
              }}
            />
          </Field>
        </div>
      ) : null}
      {kind === "signal" ? (
        <div className="mt-3 space-y-3">
          <Field label={labelFor("min_pnl_percent")}>
            <NumberInput
              value={value.min_pnl_percent as number | null}
              onChange={(v) => props.onChange({ ...value, min_pnl_percent: v })}
            />
          </Field>
          <FilterGroupEditor
            groups={(value.groups as Config[]) ?? []}
            onChange={(groups) => props.onChange({ ...value, groups })}
            pathPrefix="exit.take_profit.groups"
            catalog={props.catalog}
            catalogError={props.catalogError}
            errors={props.errors}
          />
        </div>
      ) : null}
      {kind === "trailing" ? (
        <Field label={labelFor("deviation_percent")}>
          <NumberInput
            value={value.deviation_percent as number | null}
            onChange={(v) => props.onChange({ ...value, deviation_percent: v })}
          />
        </Field>
      ) : null}
    </div>
  );
}

// TP/argument variants are statically described here; the schema itself does
// not carry these defaults in `default` (only Python defaults), so the UI does
// not prefill them either (owner rule U4).
const TP_VARIANTS: Record<string, { kind: string; node: SchemaNode }> = {
  fixed_percentage: {
    kind: "fixed_percentage",
    node: {
      type: "object",
      properties: {
        kind: { type: "string", const: "fixed_percentage", default: "fixed_percentage" },
        percent: { type: "number" },
      },
    },
  },
  multi_take: {
    kind: "multi_take",
    node: {
      type: "object",
      properties: {
        kind: { type: "string", const: "multi_take", default: "multi_take" },
        takes: { type: "array", items: { type: "object" } },
        breakeven: { anyOf: [{ type: "object" }, { type: "null" }], default: null },
      },
    },
  },
  signal: {
    kind: "signal",
    node: {
      type: "object",
      properties: {
        kind: { type: "string", const: "signal", default: "signal" },
        groups: { type: "array", items: { type: "object" } },
        min_pnl_percent: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
      },
    },
  },
  trailing: {
    kind: "trailing",
    node: {
      type: "object",
      properties: {
        kind: { type: "string", const: "trailing", default: "trailing" },
        deviation_percent: { type: "number", default: 0.0 },
      },
    },
  },
};

/** Renders schema properties not handled by an explicit block (U4 rule). */
function UnknownFields(props: {
  schema: SchemaNode;
  defs: Defs;
  form: Config;
  setField: (path: string, value: unknown) => void;
}) {
  const { schema, defs, form, setField } = props;
  const root = resolveRef(schema, defs) ?? schema;
  const propsOfRoot = root.properties ?? {};
  // U10: `lookback_bars` remains an optional schema field (old strategies keep
  // it working), but it is intentionally not rendered — the engine computes
  // the depth by contract H1. It stays in `handled` so it does not fall into
  // the generic «Дополнительные поля» block.
  const handled = new Set(["name", "description", "direction", "timeframe", "lookback_bars", "instrument_id", "entry", "dca_grid", "exit", "risk"]);
  const unknown = Object.entries(propsOfRoot).filter(([key]) => !handled.has(key));
  if (unknown.length === 0) return null;
  return (
    <Section title="Дополнительные поля (по схеме)">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {unknown.map(([key, node]) => (
          <GenericField
            key={key}
            node={node}
            defs={defs}
            path={key}
            value={form[key]}
            onChange={(v) => setField(key, v)}
            errors={{}}
          />
        ))}
      </div>
    </Section>
  );
}

function GenericField(props: {
  node: SchemaNode;
  defs: Defs;
  path: string;
  value: unknown;
  onChange: (v: unknown) => void;
  onRemove?: () => void;
  errors: Record<string, string>;
}) {
  const { node, defs, path, value, onChange } = props;
  const resolved = resolveRef(node, defs) ?? node;
  const meta = metaOf(resolved, defs);

  if (meta.kind === "const") return <span className="hidden">{String(meta.value)}</span>;

  if (meta.kind === "union") {
    const kind = (value as Config)?.[meta.propertyName];
    const variant = meta.variants.find((v) => v.kind === String(kind));
    return (
      <div className="space-y-2">
        <Field label={labelFor(path)}>
          <SelectInput
            value={kind}
            options={meta.variants.map((v) => ({ value: v.kind, label: v.kind }))}
            allowEmpty
            onChange={(selected) => {
              const found = meta.variants.find((v) => v.kind === selected);
              onChange(found ? initialValueForVariant(found) : {});
            }}
          />
        </Field>
        {variant ? (
          <GenericField
            node={variant.node}
            defs={defs}
            path={path}
            value={value as Config}
            onChange={onChange}
            errors={props.errors}
          />
        ) : null}
      </div>
    );
  }

  if (meta.kind === "object") {
    const subs = propertyMetas(resolved, defs);
    return (
      <div className="space-y-2 rounded-control border border-border-soft p-2">
        <p className="text-sm font-medium text-text-secondary">{labelFor(path)}</p>
        {subs.map((sub) => (
          <GenericField
            key={sub.name}
            node={sub.node}
            defs={defs}
            path={path === "" ? sub.name : `${path}.${sub.name}`}
            value={(value as Config)?.[sub.name]}
            onChange={(v) => onChange({ ...((value as Config) ?? {}), [sub.name]: v })}
            errors={props.errors}
          />
        ))}
      </div>
    );
  }

  if (meta.kind === "array") {
    const items = Array.isArray(value) ? value : [];
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium text-text-secondary">{labelFor(path)}</p>
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-2">
            <div className="flex-1">
              <GenericField
                node={meta.items}
                defs={defs}
                path={`${path}.${i}`}
                value={item}
                onChange={(v) => {
                  const next = items.map((it, idx) => (idx === i ? v : it));
                  onChange(next);
                }}
                errors={props.errors}
              />
            </div>
            <Button
              variant="ghost"
              onClick={() => onChange(items.filter((_, idx) => idx !== i))}
            >
              Удалить
            </Button>
          </div>
        ))}
        <Button variant="ghost" onClick={() => onChange([...items, {}])}>
          + Добавить
        </Button>
      </div>
    );
  }

  const nullable = nullableOf(resolved, defs);
  const error = props.errors[path] ?? null;

  if (meta.kind === "enum" && !meta.nullable) {
    return (
      <Field label={labelFor(path)} error={error}>
        <SelectInput
          value={value}
          options={meta.options.map((o) => ({ value: String(o), label: String(o) }))}
          allowEmpty
          onChange={(v) => onChange(v === "" ? undefined : v)}
        />
      </Field>
    );
  }
  if (meta.kind === "enum") {
    return (
      <Field label={labelFor(path)} error={error}>
        <SelectInput
          value={value}
          options={meta.options.filter((o) => o !== null).map((o) => ({ value: String(o), label: String(o) }))}
          allowEmpty
          onChange={(v) => onChange(v === "" ? null : v)}
        />
      </Field>
    );
  }
  if (meta.kind === "number" || meta.kind === "integer") {
    return (
      <Field label={labelFor(path)} error={error}>
        <NumberInput value={value as number | null} onChange={(v) => onChange(v)} />
      </Field>
    );
  }
  if (meta.kind === "boolean" && nullable) {
    return (
      <Field label={labelFor(path)} error={error}>
        <NullableBoolInput value={value as boolean | null} onChange={(v) => onChange(v)} />
      </Field>
    );
  }
  if (meta.kind === "boolean") {
    return (
      <Field label={labelFor(path)} error={error}>
        <CheckboxInput value={value === true} onChange={(v) => onChange(v)} />
      </Field>
    );
  }
  if (meta.kind === "string") {
    return (
      <Field label={labelFor(path)} error={error}>
        <TextInput value={(value as string) ?? ""} onChange={(v) => onChange(v)} />
      </Field>
    );
  }
  return (
    <Field label={labelFor(path)} error={error}>
      <TextInput value={value === undefined ? "" : JSON.stringify(value)} onChange={() => undefined} />
    </Field>
  );
}
