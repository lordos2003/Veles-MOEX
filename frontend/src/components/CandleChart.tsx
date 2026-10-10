import { useMemo } from "react";

interface Candle {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

export interface ChartMarker {
  timestamp: string;
  price: string;
  kind: "entry" | "exit";
}

interface CandleChartProps {
  candles: Candle[];
  /** Entry/exit markers of a backtest run (U6). */
  markers?: ChartMarker[];
}

const W = 640;
const H = 260;
const PAD = 8;

export default function CandleChart({ candles, markers = [] }: CandleChartProps) {
  const { bars, scaledMarkers } = useMemo(() => {
    if (candles.length === 0) return { bars: [], scaledMarkers: [] as { x: number; y: number; kind: "entry" | "exit" }[] };
    const highs = candles.map((c) => Number(c.high));
    const lows = candles.map((c) => Number(c.low));
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const range = max - min || 1;
    const candleW = Math.max((W - 2 * PAD) / Math.max(candles.length, 1) - 2, 1);
    const xAt = (i: number) => PAD + (i / Math.max(candles.length - 1, 1)) * (W - 2 * PAD);
    const yAt = (value: number) => H - PAD - ((value - min) / range) * (H - 2 * PAD);
    const byTime = new Map(candles.map((c, i) => [c.timestamp, i] as const));
    const bars = candles.map((c, i) => {
      const open = Number(c.open);
      const close = Number(c.close);
      const high = Number(c.high);
      const low = Number(c.low);
      const x = xAt(i);
      const up = close >= open;
      const bodyTop = yAt(Math.max(open, close));
      const bodyBottom = yAt(Math.min(open, close));
      return { x, up, bodyTop, bodyBottom, wickTop: yAt(high), wickBottom: yAt(low), candleW };
    });
    const scaledMarkers = markers
      .map((m) => {
        const index = byTime.get(m.timestamp) ?? -1;
        if (index < 0) return null;
        return { x: xAt(index), y: yAt(Number(m.price)), kind: m.kind };
      })
      .filter((m): m is { x: number; y: number; kind: "entry" | "exit" } => m !== null);
    return { bars, scaledMarkers };
  }, [candles, markers]);

  if (candles.length === 0) {
    return <p className="text-sm text-text-muted">Нет данных для отображения</p>;
  }

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      className="block rounded-control border border-border-soft bg-chart-bg"
      role="img"
      aria-label="График свечей"
    >
      {/* R7: горизонтальная сетка для ориентира по цене (токен, светлая тема — своя). */}
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} className="stroke-chart-grid" strokeWidth="1" strokeDasharray="3 5" />
      ))}
      {bars.map((bar, i) => (
        <g key={i} className={bar.up ? "fill-success stroke-success" : "fill-error stroke-error"}>
          <line x1={bar.x} x2={bar.x} y1={bar.wickTop} y2={bar.wickBottom} strokeWidth="1" />
          <rect
            x={bar.x - bar.candleW / 2}
            y={bar.bodyTop}
            width={bar.candleW}
            height={Math.max(bar.bodyBottom - bar.bodyTop, 1)}
            stroke="none"
            opacity="0.92"
          />
        </g>
      ))}
      {scaledMarkers.map((m, i) => (
        <g key={`m-${i}`}>
          <circle
            cx={m.x}
            cy={m.y}
            r="4"
            className={m.kind === "entry" ? "fill-warning" : "fill-accent-bright"}
            stroke="var(--color-chart-stroke)"
            strokeWidth="1"
          />
          <title>{m.kind === "entry" ? "Вход" : "Выход"}</title>
        </g>
      ))}
    </svg>
  );
}
