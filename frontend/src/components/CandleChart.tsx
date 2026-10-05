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
      const color = up ? "#22c55e" : "#ef4444";
      const bodyTop = yAt(Math.max(open, close));
      const bodyBottom = yAt(Math.min(open, close));
      return { x, up, color, bodyTop, bodyBottom, wickTop: yAt(high), wickBottom: yAt(low), candleW };
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
    return <p className="text-sm text-zinc-500">Нет данных для отображения</p>;
  }

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="bg-zinc-900">
      {bars.map((bar, i) => (
        <g key={i}>
          <line
            x1={bar.x}
            x2={bar.x}
            y1={bar.wickTop}
            y2={bar.wickBottom}
            stroke={bar.color}
            strokeWidth="1"
          />
          <rect
            x={bar.x - bar.candleW / 2}
            y={bar.bodyTop}
            width={bar.candleW}
            height={Math.max(bar.bodyBottom - bar.bodyTop, 1)}
            fill={bar.color}
            opacity="0.9"
          />
        </g>
      ))}
      {scaledMarkers.map((m, i) => (
        <g key={`m-${i}`}>
          <circle cx={m.x} cy={m.y} r="4" fill={m.kind === "entry" ? "#facc15" : "#38bdf8"} stroke="#000" strokeWidth="1" />
          <title>{m.kind === "entry" ? "Вход" : "Выход"}</title>
        </g>
      ))}
    </svg>
  );
}
