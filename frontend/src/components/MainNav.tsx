import { useState } from "react";
import { NavLink } from "react-router-dom";
import { Dialog, DialogClose, DialogTitle, DialogTrigger, SheetContent } from "./ui/Dialog";

export const NAV = [
  { to: "/", label: "Обзор", end: true },
  { to: "/strategies", label: "Стратегии", end: false },
  { to: "/bots", label: "Боты", end: false },
  { to: "/backtest", label: "Бэктест", end: false },
  { to: "/sandbox", label: "Песочница и счета", end: false },
];

const desktopLink = ({ isActive }: { isActive: boolean }) =>
  "relative inline-flex min-h-9 items-center whitespace-nowrap rounded-control px-3 text-sm transition-colors " +
  "duration-(--duration-fast) " +
  (isActive
    ? "bg-surface-raised font-medium text-text after:absolute after:inset-x-3 after:-bottom-px after:h-px after:bg-accent-bright"
    : "text-text-muted hover:bg-surface hover:text-text");

const mobileLink = ({ isActive }: { isActive: boolean }) =>
  "flex min-h-11 items-center rounded-control px-3 text-base transition-colors " +
  (isActive ? "bg-surface-raised font-medium text-text" : "text-text-secondary hover:bg-surface-raised");

/** Навигация: полоса ссылок на широких экранах, панель-меню — на узких (R6). */
export function MainNav() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <nav aria-label="Основная навигация" className="hidden items-center gap-1 lg:flex">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={desktopLink}>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <button
            type="button"
            aria-label="Открыть меню"
            className="inline-flex h-11 w-11 items-center justify-center rounded-control border border-border text-text-secondary hover:bg-surface-raised lg:hidden"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
        </DialogTrigger>
        <SheetContent>
          <div className="mb-3 flex items-center justify-between">
            <DialogTitle className="text-sm font-medium text-text-muted">Разделы</DialogTitle>
            <DialogClose asChild>
              <button
                type="button"
                aria-label="Закрыть меню"
                className="inline-flex h-11 w-11 items-center justify-center rounded-control text-text-secondary hover:bg-surface-raised"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <path d="M6 6l12 12M18 6 6 18" />
                </svg>
              </button>
            </DialogClose>
          </div>
          <nav aria-label="Основная навигация (меню)" className="flex flex-col gap-1">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className={mobileLink} onClick={() => setOpen(false)}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </SheetContent>
      </Dialog>
    </>
  );
}
