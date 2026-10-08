/**
 * Thin typed HTTP client for the backend REST API (Vite proxies /api to FastAPI).
 *
 * Error handling contract (task U1): the backend error text is shown to the
 * user verbatim. HTTP 422 (FastAPI validation) is additionally mapped to
 * per-field messages so the strategy form can mark concrete fields (U6: the
 * FastAPI ``{"detail": [...]}`` envelope is unwrapped, and non-field messages
 * are shown as readable «поле: сообщение» with Russian field labels).
 */

import { labelFor } from "./lib/labels";

export interface ValidationItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** Unwrap FastAPI's ``{"detail": ...}`` envelope so callers see the message
 * list / string directly instead of the wrapper object. */
function unwrapDetail(detail: unknown): unknown {
  if (detail && typeof detail === "object" && "detail" in detail) {
    const inner = (detail as { detail?: unknown }).detail;
    if (typeof inner === "string" || Array.isArray(inner)) return inner;
  }
  return detail;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    const inner = unwrapDetail(detail);
    super(verbatimMessage(inner));
    this.name = "ApiError";
    this.status = status;
    this.detail = inner;
  }
}

/**
 * Pydantic discriminator errors (the strategy form's «Тейк-профит» etc.)
 * come with a technical English message ("Unable to extract tag using
 * discriminator 'kind'"). M3 (MVP-7.4 review): show the readable Russian text.
 */
export function validationMessage(item: ValidationItem | null | undefined): string {
  if (item?.type === "union_tag_not_found" || item?.type === "union_tag_invalid") {
    return "Выберите вид тейк-профита.";
  }
  return item?.msg ?? "";
}

/** The user-facing message of an API error: the backend text, unchanged. */
export function verbatimMessage(detail: unknown): string {
  detail = unwrapDetail(detail);
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const loc = (item?.loc ?? []) as (string | number)[];
        const paths = loc.filter((p) => typeof p === "string" && p !== "body");
        const where = paths.length ? labelFor(paths.join(".")) : "";
        const msg = validationMessage(item);
        return where ? `${where}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const d = detail as { detail?: unknown; message?: unknown };
    if (typeof d.detail === "string") return d.detail;
    if (typeof d.detail === "object" && d.detail !== null) return JSON.stringify(d.detail);
    if (typeof d.message === "string") return d.message;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

/**
 * Map FastAPI 422 detail to field-path -> message, e.g.
 * ["body","exit","take_profit","percent"] -> "exit.take_profit.percent".
 */
export function fieldErrors(detail: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!Array.isArray(detail)) return out;
  for (const item of detail as ValidationItem[]) {
    const loc = (item.loc ?? []).filter((p) => typeof p === "string" && p !== "body");
    const path = loc.join(".");
    if (path) out[path] = validationMessage(item) || "Ошибка";
  }
  return out;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  // P1 (MVP-7.3): a request with a body must be JSON — browsers otherwise send
  // `text/plain`, and recent FastAPI versions reject a string body.
  if (init?.body !== undefined && headers["Content-Type"] === undefined) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, { ...init, headers });
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, body);
  }
  return body as T;
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },
  post<T>(path: string, data?: unknown): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  },
  put<T>(path: string, data: unknown): Promise<T> {
    return request<T>(path, { method: "PUT", body: JSON.stringify(data) });
  },
  patch<T>(path: string, data: unknown): Promise<T> {
    return request<T>(path, { method: "PATCH", body: JSON.stringify(data) });
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" });
  },
};
