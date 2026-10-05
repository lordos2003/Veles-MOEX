import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../api";
import type { RuntimeResponse } from "../types";

export type RuntimeMode = "checking" | "sandbox" | "live";

export interface RuntimeState {
  runtime: RuntimeResponse | null;
  mode: RuntimeMode;
  error: string | null;
  reload: () => void;
}

const RuntimeContext = createContext<RuntimeState>({
  runtime: null,
  mode: "checking",
  error: null,
  reload: () => undefined,
});

export function RuntimeProvider(props: { children: ReactNode }) {
  const [runtime, setRuntime] = useState<RuntimeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await api.get<RuntimeResponse>("/api/runtime");
      setRuntime(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 30000);
    return () => clearInterval(timer);
  }, [load]);

  const mode: RuntimeMode = !runtime ? "checking" : runtime.sandbox ? "sandbox" : "live";
  return (
    <RuntimeContext.Provider value={{ runtime, mode, error, reload: load }}>
      {props.children}
    </RuntimeContext.Provider>
  );
}

export function useRuntime(): RuntimeState {
  return useContext(RuntimeContext);
}
