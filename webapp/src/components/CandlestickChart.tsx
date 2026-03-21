/**
 * CandlestickChart — renders OHLCV data using TradingView's lightweight-charts.
 *
 * Matches the neobrutalist design system with heavy borders and bold colors.
 * Supports dark mode via the `dark` prop (auto-detected from Tailwind class).
 */

import { useEffect, useRef, useState } from "react";
import { createChart, type IChartApi, type CandlestickData, type Time } from "lightweight-charts";

interface Candle {
  time: number; // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface CandlestickChartProps {
  data: Candle[];
  height?: number;
  loading?: boolean;
  error?: string | null;
}

export function CandlestickChart({
  data,
  height = 300,
  loading = false,
  error = null,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [isDark, setIsDark] = useState(false);

  // Detect dark mode from document class
  useEffect(() => {
    const check = () => setIsDark(document.documentElement.classList.contains("dark"));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    // Clean up previous chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: isDark ? "#1f2937" : "#ffffff" },
        textColor: isDark ? "#d1d5db" : "#374151",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
      },
      grid: {
        vertLines: { color: isDark ? "#374151" : "#e5e7eb" },
        horzLines: { color: isDark ? "#374151" : "#e5e7eb" },
      },
      crosshair: {
        mode: 0, // Normal crosshair
      },
      rightPriceScale: {
        borderColor: isDark ? "#4b5563" : "#000000",
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: isDark ? "#4b5563" : "#000000",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#16a34a",
      borderDownColor: "#dc2626",
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });

    // Convert data to lightweight-charts format
    const chartData: CandlestickData<Time>[] = data
      .filter((c) => c.time > 0)
      .sort((a, b) => a.time - b.time)
      .map((c) => ({
        time: c.time as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

    if (chartData.length > 0) {
      candleSeries.setData(chartData);
    }

    // Volume histogram (overlay on bottom)
    const volumeSeries = chart.addHistogramSeries({
      color: isDark ? "#6366f1" : "#818cf8",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const volumeData = data
      .filter((c) => c.time > 0)
      .sort((a, b) => a.time - b.time)
      .map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: c.close >= c.open
          ? (isDark ? "#22c55e80" : "#22c55e60")
          : (isDark ? "#ef444480" : "#ef444460"),
      }));

    if (volumeData.length > 0) {
      volumeSeries.setData(volumeData);
    }

    // Fit content
    chart.timeScale().fitContent();

    // Handle resize
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    chartRef.current = chart;

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [data, height, isDark]);

  if (loading) {
    return (
      <div
        className="flex items-center justify-center border-4 border-black rounded-lg bg-gray-50 dark:bg-gray-900 dark:border-gray-700"
        style={{ height }}
      >
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-900 dark:border-white" />
          <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Loading chart data...
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="flex items-center justify-center border-4 border-black rounded-lg bg-red-50 dark:bg-red-900/20 dark:border-red-800"
        style={{ height }}
      >
        <span className="text-sm font-medium text-red-600 dark:text-red-400">
          {error}
        </span>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center border-4 border-black rounded-lg bg-gray-50 dark:bg-gray-900 dark:border-gray-700"
        style={{ height }}
      >
        <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
          No price history available for this market
        </span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="border-4 border-black rounded-lg overflow-hidden shadow-[4px_4px_0px_0px_#000] dark:border-gray-700 dark:shadow-[4px_4px_0px_0px_#1f2937]"
    />
  );
}
