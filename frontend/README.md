# Frontend

React + TypeScript + Vite + Tailwind CSS application for Veles-MOEX. It displays
the project title and the backend connection status from `GET /api/health`.

## Stack

- React 18 + TypeScript
- Vite
- Tailwind CSS v4 (via the `@tailwindcss/vite` plugin, CSS-first `@theme` config)

## Browser support

Tailwind CSS v4 targets modern browsers: Safari 16.4+, Chrome 111+,
Firefox 128+ (same baseline as the official v4 requirement). The app is
designed for the desktop tool belt; no IE/legacy fallbacks are built.

## Running locally

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api/*` to the FastAPI
backend on `http://localhost:8000` (see `vite.config.ts`).

## Build

```powershell
npm run build
npm run preview
```

## Status

The page displays the backend health status and a T-Invest integration panel:
connection status (Connected / Disconnected / Not configured), accounts,
instruments, and market data (last price + candles) for a selected instrument.
The data comes from the read-only backend endpoints via `/api`.

## Notes

- `shadcn/ui` was not added at this stage to keep the initial scaffold minimal
  (it is optional per the task). It can be introduced when UI components grow.
- In Docker, the frontend is built and served by nginx, which proxies `/api/*`
  to the backend service.
