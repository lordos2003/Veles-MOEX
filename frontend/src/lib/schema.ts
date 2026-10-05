/**
 * Schema-driven form utilities (task U4 / U8).
 *
 * The strategy form is built from the pydantic JSON Schema returned by
 * `GET /api/strategies/schema` plus the indicator catalog (U3). The main rule
 * (owner contract): the UI never invents values — a field gets a value only
 * from (a) user input or (b) a `default` already present in the JSON Schema.
 * Python `default_factory` values are NOT in the schema, so they are not
 * pre-filled here (the backend applies them on validation).
 */

import type { SchemaNode } from "../types";

export type FieldMeta =
  | { kind: "object" }
  | { kind: "array"; items: SchemaNode }
  | { kind: "enum"; options: unknown[]; nullable: boolean }
  | {
      kind: "number" | "integer";
      nullable: boolean;
      minimum?: number;
      maximum?: number;
      exclusiveMinimum?: number;
      exclusiveMaximum?: number;
    }
  | { kind: "boolean"; nullable: boolean }
  | { kind: "string"; nullable: boolean }
  | { kind: "const"; value: unknown }
  | { kind: "union"; propertyName: string; variants: VariantMeta[]; nullable: boolean }
  | { kind: "any"; nullable: boolean };

export interface VariantMeta {
  kind: string;
  node: SchemaNode;
}

export interface PropertyMeta {
  name: string;
  node: SchemaNode;
  required: boolean;
  hasDefault: boolean;
  defaultValue: unknown;
  meta: FieldMeta;
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function deepClone<T>(value: T): T {
  if (value === undefined || value === null) return value;
  if (Array.isArray(value)) return value.map((v) => deepClone(v)) as T;
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) out[k] = deepClone(v);
    return out as T;
  }
  return value;
}

/** Follow `#/$defs/NAME` references. */
export function resolveRef(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): SchemaNode | undefined {
  let current = node;
  const seen = new Set<string>();
  while (current?.$ref !== undefined) {
    const name = current.$ref.split("/").pop() ?? "";
    if (seen.has(name) || !(name in defs)) return current;
    seen.add(name);
    current = defs[name];
  }
  return current;
}

export function hasDefault(node: SchemaNode | undefined): boolean {
  return node?.default !== undefined;
}

function stripNull(variants: SchemaNode[] | undefined): SchemaNode[] {
  return (variants ?? []).filter((v) => v.type !== "null");
}

export function metaOf(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): FieldMeta {
  const resolved = resolveRef(node, defs);
  if (!resolved) return { kind: "any", nullable: false };

  if (resolved.oneOf !== undefined) {
    const variants: VariantMeta[] = [];
    for (const variant of resolved.oneOf) {
      const rv = resolveRef(variant, defs);
      const kindConst = resolveRef(rv?.properties?.["kind"], defs)?.const;
      if (typeof kindConst === "string" || typeof kindConst === "number") {
        variants.push({ kind: String(kindConst), node: rv ?? {} });
      }
    }
    const prop = resolved.discriminator?.propertyName ?? "kind";
    return { kind: "union", propertyName: prop, variants, nullable: hasNullAny(resolved) };
  }

  if (resolved.anyOf !== undefined) {
    const rest = stripNull(resolved.anyOf);
    if (rest.length === 1) return metaOf(rest[0], defs);
    return { kind: "any", nullable: hasNullAny(resolved) };
  }

  if (resolved.const !== undefined) return { kind: "const", value: resolved.const };
  if (resolved.enum !== undefined) {
    return { kind: "enum", options: resolved.enum, nullable: resolved.enum.includes(null) };
  }

  if (Array.isArray(resolved.type)) {
    const nonNull = resolved.type.filter((t) => t !== "null");
    if (nonNull.length === 1) return metaOf({ ...resolved, type: nonNull[0] }, defs);
    return { kind: "any", nullable: resolved.type.includes("null") };
  }

  switch (resolved.type) {
    case "object":
      return { kind: "object" };
    case "array":
      return { kind: "array", items: resolved.items ?? { type: "any" } };
    case "number":
    case "integer":
      return {
        kind: resolved.type,
        nullable: false,
        minimum: resolved.minimum,
        maximum: resolved.maximum,
        exclusiveMinimum: resolved.exclusiveMinimum,
        exclusiveMaximum: resolved.exclusiveMaximum,
      };
    case "boolean":
      return { kind: "boolean", nullable: false };
    case "string":
      return { kind: "string", nullable: false };
    default:
      return { kind: "any", nullable: false };
  }
}

function hasNullAny(node: SchemaNode): boolean {
  const resolved = resolveRef(node, {});
  if (!resolved) return false;
  if (resolved.enum?.includes(null)) return true;
  if (Array.isArray(resolved.type) && resolved.type.includes("null")) return true;
  if (resolved.anyOf?.some((v) => v.type === "null")) return true;
  return false;
}

/** Non-null branch of an anyOf nullable node (nullable resolved with metaOf). */
export function nullableBase(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): SchemaNode | undefined {
  const resolved = resolveRef(node, defs);
  if (!resolved) return undefined;
  if (resolved.anyOf !== undefined) {
    const rest = stripNull(resolved.anyOf);
    return rest.length === 1 ? rest[0] : undefined;
  }
  if (Array.isArray(resolved.type)) {
    const nonNull = resolved.type.filter((t) => t !== "null");
    if (nonNull.length === 1) return { ...resolved, type: nonNull[0] };
  }
  return resolved;
}

export function nullableOf(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): boolean {
  const resolved = resolveRef(node, defs);
  return resolved ? hasNullAny(resolved) : false;
}

export function propertyMetas(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): PropertyMeta[] {
  const resolved = resolveRef(node, defs);
  if (!resolved?.properties) return [];
  const required = new Set(resolved.required ?? []);
  return Object.entries(resolved.properties).map(([name, child]) => ({
    name,
    node: child,
    required: required.has(name),
    hasDefault: hasDefault(child),
    defaultValue: child.default,
    meta: metaOf(child, defs),
  }));
}

export function unionVariants(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): VariantMeta[] {
  const meta = metaOf(node, defs);
  return meta.kind === "union" ? meta.variants : [];
}

export function unionPropertyName(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): string {
  const meta = metaOf(node, defs);
  return meta.kind === "union" ? meta.propertyName : "kind";
}

/** Scheme-rule initial value: `default` from schema, otherwise empty/undefined. */
export function initialValue(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): unknown {
  // B4: pydantic emits `{"$ref": "#/$defs/X", "default": ...}` — the default
  // is a SIBLING of `$ref`, so it must be read before resolving the reference
  // (resolving would lose it and show the field as "not selected").
  if (node !== undefined && hasDefault(node)) return deepClone(node.default);
  const resolved = resolveRef(node, defs);
  if (!resolved) return undefined;
  // Legacy: a `default` inside the resolved $defs node (no sibling default).
  if (hasDefault(resolved)) return deepClone(resolved.default);
  const meta = metaOf(resolved, defs);
  switch (meta.kind) {
    case "object": {
      const out: Record<string, unknown> = {};
      for (const prop of propertyMetas(resolved, defs)) {
        out[prop.name] = initialValue(prop.node, defs);
      }
      return out;
    }
    case "array":
      return [];
    case "union": {
      const out: Record<string, unknown> = {};
      out[meta.propertyName] = undefined;
      return out;
    }
    default:
      return undefined;
  }
}

/** For a union: initial value for a chosen variant (kind comes from its const). */
export function initialValueForVariant(variant: VariantMeta): Record<string, unknown> {
  const value = initialValue(variant.node, {});
  return isPlainObject(value) ? value : {};
}

/**
 * Deep-compact a form value for submission: `undefined` leaves are dropped,
 * everything else is preserved (including null = "not selected"/explicitly
 * empty). Never converts null to a default or to false.
 */
export function compact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(compact);
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      const c = compact(v);
      if (c !== undefined) out[k] = c;
    }
    return out;
  }
  return value;
}

/** Form state <- stored config: identity copy (no value is invented). */
export function formFromConfig(config: unknown): unknown {
  return deepClone(config);
}

/** Form state -> config for submit: compact undefined leaves only. */
export function formToConfig(form: unknown): unknown {
  return compact(form);
}
