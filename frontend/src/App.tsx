import { useEffect, useState } from "react";

type BackendStatus = "checking" | "ok" | "error";

interface HealthResponse {
  status: string;
}

export default function App() {
  const [backend, setBackend] = useState<BackendStatus>("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch("/api/health");
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data: HealthResponse = await res.json();
        if (!cancelled) {
          setBackend(data.status === "ok" ? "ok" : "error");
        }
      } catch {
        if (!cancelled) {
          setBackend("error");
        }
      }
    }

    check();
    return () => {
      cancelled = true;
    };
  }, []);

  const label =
    backend === "ok"
      ? "Backend: подключен"
      : backend === "error"
        ? "Backend: недоступен"
        : "Backend: проверка...";

  const color =
    backend === "ok" ? "text-green-500" : backend === "error" ? "text-red-500" : "text-yellow-500";

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-100">
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Veles-MOEX</h1>
        <p className={color + " mt-2 text-sm"}>{label}</p>
      </div>
    </main>
  );
}
