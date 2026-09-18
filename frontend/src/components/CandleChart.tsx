import { useMemo } from "react";

interface Candle {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
}

interface CandleChartProps {
  candles: Candle[];
}

const W = 600;
const H = 220;
const PAD = 8;

export default function CandleChart({ candles }: CandleChartProps) {
  const points = useMemo(() => {
    if (candles.length === 0) return [];
    const values = candles.map((c) => Number(c.close));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    return candles.map((c, i) => {
      const x = PAD + (i / Math.max(candles.length - 1, 1)) * (W - 2 * PAD);
      const y = H - PAD - ((Number(c.close) - min) / range) * (H - 2 * PAD);
      return `${x},${y}`;
    });
  }, [candles]);

  if (candles.length === 0) {
    return <p className="text-sm text-zinc-500">Нет данных для отображения</p>;
  }

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="bg-zinc-900">
      <polyline points={points.join(" ")} fill="none" stroke="#22c55e" strokeWidth="1.5" />
    </svg>
  );
}
