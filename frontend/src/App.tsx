import { Suspense, lazy } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { MainNav } from "./components/MainNav";
import { ModeBadge } from "./components/ModeBadge";
import { PageTransition } from "./components/PageTransition";
import { PageSkeleton } from "./components/ui/Skeleton";
import { Wordmark } from "./components/Wordmark";

// R5: страницы грузятся лениво — первый экран не тянет форму стратегий и бэктест.
const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const StrategyFormPage = lazy(() => import("./pages/StrategyFormPage").then((m) => ({ default: m.StrategyFormPage })));
const StrategiesListPage = lazy(() => import("./pages/StrategiesPage").then((m) => ({ default: m.StrategiesListPage })));
const StrategyDetailPage = lazy(() => import("./pages/StrategiesPage").then((m) => ({ default: m.StrategyDetailPage })));
const BotsPage = lazy(() => import("./pages/BotsPage").then((m) => ({ default: m.BotsPage })));
const BotDetailPage = lazy(() => import("./pages/BotsPage").then((m) => ({ default: m.BotDetailPage })));
const BacktestPage = lazy(() => import("./pages/BacktestPage").then((m) => ({ default: m.BacktestPage })));
const SandboxPage = lazy(() => import("./pages/SandboxPage").then((m) => ({ default: m.SandboxPage })));

function App() {
  return (
    <div className="min-h-screen bg-page text-text">
      <a href="#main" className="skip-link">
        К содержимому
      </a>
      <header className="sticky top-0 z-40 border-b border-border-soft/80 bg-page/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <h1 className="m-0">
            <Link to="/" aria-label="Veles-MOEX — на главную" className="inline-flex rounded-control">
              <Wordmark />
            </Link>
          </h1>
          <div className="flex items-center gap-3">
            <MainNav />
            <ModeBadge />
          </div>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-6 outline-none sm:px-6 sm:py-8">
        <PageTransition>
          <Suspense fallback={<PageSkeleton />}>
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
          </Suspense>
        </PageTransition>
      </main>
    </div>
  );
}

export default App;
