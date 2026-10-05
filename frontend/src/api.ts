/**
 * Thin typed HTTP client for the backend REST API (Vite proxies /api to FastAPI).
 *
 * Error handling contract (task U1): the backend error text is shown to the
 * user verbatim. HTTP 422 (FastAPI validation) is additionally mapped to
 * per-field messages so the strategy form can mark concrete fields.
 */

export interface ValidationItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(verbatimMessage(detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** The user-facing message of an API error: the backend text, unchanged. */
export function verbatimMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const loc = (item?.loc ?? []) as (string | number)[];
        const where = loc.filter((p) => typeof p === "string" && p !== "body").join(".");
        return where ? `${where}: ${item?.msg ?? ""}` : (item?.msg ?? "");
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
    if (path) out[path] = item.msg ?? "Ошибка";
  }
  return out;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...((init?.headers as Record<string, string>) ?? {}),
  };
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
