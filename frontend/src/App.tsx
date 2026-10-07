import { NavLink, Route, Routes } from "react-router-dom";
import { ModeBadge } from "./components/ModeBadge";
import { OverviewPage } from "./pages/OverviewPage";
import { StrategyFormPage } from "./pages/StrategyFormPage";
import { StrategiesListPage, StrategyDetailPage } from "./pages/StrategiesPage";
import { BotsPage, BotDetailPage } from "./pages/BotsPage";
import { BacktestPage } from "./pages/BacktestPage";
import { SandboxPage } from "./pages/SandboxPage";

const NAV = [
  { to: "/", label: "Обзор", end: true },
  { to: "/strategies", label: "Стратегии", end: false },
  { to: "/bots", label: "Боты", end: false },
  { to: "/backtest", label: "Бэктест", end: false },
  { to: "/sandbox", label: "Песочница и счета", end: false },
];

function App() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-6xl px-6 py-6">
        <header className="flex items-center justify-between gap-4 border-b border-zinc-800 pb-4">
          <h1 className="text-2xl font-semibold tracking-tight">Veles-MOEX</h1>
          <ModeBadge />
        </header>

        <nav className="mt-4 flex flex-wrap gap-1 border-b border-zinc-800 pb-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                "rounded px-3 py-1.5 text-sm " +
                (isActive
                  ? "bg-zinc-800 font-medium text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-6">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/strategies" element={<StrategiesListPage />} />
            <Route path="/strategies/new" element={<StrategyFormPage />} />
            <Route path="/strategies/:id" element={<StrategyDetailPage />} />
            <Route path="/strategies/:id/edit" element={<StrategyFormPage edit />} />
            <Route path="/bots" element={<BotsPage />} />
            <Route path="/bots/:id" element={<BotDetailPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
            <Route path="/sandbox" element={<SandboxPage />} />
          </Routes>
        </div>
      </div>
    </main>
  );
}

export default App;
