<!--
  AdvancedMarketChart — institutional charting on svelte-echarts.

  Tier A scope (per docs/reference/wealth-charting-tech-debt.md):
    - Default chart type: Line + subtle area fill (Barchart north-star).
    - Switchable chart types: Line / Area / Candlestick.
    - Bottom range chip row (1D / 5D / 1M / 2M / 3M / 6M / 9M / 1Y / 2Y / 3Y / 5Y / 10Y / 20Y / Max).
    - Top granularity dropdown (Daily / 1h / 30min / 15min / 5min / 1min).
    - Indicators dropdown (SMA20 / SMA50 / EMA20 / Bollinger Bands).
    - Volume sub-pane (always on).
    - Last-price callout pill on the right edge of the price series.
    - Crosshair + rich OHLC + indicator tooltip.
    - Log scale toggle. Percent change (rebased) toggle.
    - Live tick fold from marketStore.priceMap[ticker].
    - Tokens, no hex literals.

  Out of scope (Tier B/C/D — see docs/reference/wealth-charting-tech-debt.md):
    Compare overlay, RSI/MACD sub-pane, drawing tools, templates, notes,
    alerts, server-side indicator pre-compute, custom f(x) formulas.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions, echarts } from "@investintell/ui/charts/echarts-setup";
	import { formatCurrency, formatNumber, formatPercent } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { MarketDataStore } from "$lib/stores/market-data.svelte";

	// ── Props ────────────────────────────────────────────────────────────
	interface Props {
		ticker: string;
		height?: number;
	}

	let { ticker, height = 420 }: Props = $props();

	// ── Context ──────────────────────────────────────────────────────────
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const marketStore = getContext<MarketDataStore | undefined>("netz:marketDataStore");

	// ── Domain types ─────────────────────────────────────────────────────
	type Bar = {
		time: number; // ms epoch
		open: number;
		high: number;
		low: number;
		close: number;
		volume: number;
	};

	type Granularity = "daily" | "1hour" | "30min" | "15min" | "5min" | "1min";
	const GRANULARITIES: Granularity[] = ["daily", "1hour", "30min", "15min", "5min", "1min"];
	const GRANULARITY_LABEL: Record<Granularity, string> = {
		daily: "Daily",
		"1hour": "1 Hour",
		"30min": "30 Min",
		"15min": "15 Min",
		"5min": "5 Min",
		"1min": "1 Min",
	};

	type ChartType = "line" | "area" | "candle";
	const CHART_TYPES: { id: ChartType; label: string }[] = [
		{ id: "line", label: "Line" },
		{ id: "area", label: "Area" },
		{ id: "candle", label: "Candle" },
	];

	type RangeKey = "1D" | "5D" | "1M" | "2M" | "3M" | "6M" | "9M" | "1Y" | "2Y" | "3Y" | "5Y" | "10Y" | "20Y" | "Max";
	const RANGES: RangeKey[] = ["1D", "5D", "1M", "2M", "3M", "6M", "9M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "Max"];
	const RANGE_DAYS: Record<Exclude<RangeKey, "Max">, number> = {
		"1D": 1, "5D": 5, "1M": 30, "2M": 60, "3M": 91, "6M": 182, "9M": 273,
		"1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "10Y": 3650, "20Y": 7300,
	};

	type IndicatorId = "sma20" | "sma50" | "ema20" | "bbands20";
	const INDICATOR_LABEL: Record<IndicatorId, string> = {
		sma20: "SMA 20",
		sma50: "SMA 50",
		ema20: "EMA 20",
		bbands20: "Bollinger Bands (20, 2)",
	};

	// ── State ────────────────────────────────────────────────────────────
	let bars = $state<Bar[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);

	let granularity = $state<Granularity>("daily");
	let chartType = $state<ChartType>("line");
	let activeRange = $state<RangeKey>("6M");
	let activeIndicators = $state<Set<IndicatorId>>(new Set(["sma20", "sma50"]));
	let logScale = $state(false);
	let percentMode = $state(false);

	let granularityOpen = $state(false);
	let indicatorsOpen = $state(false);
	let chartTypeOpen = $state(false);

	// Chart instance bound from ChartContainer for live tick replaceMerge.
	let chart = $state<ReturnType<typeof echarts.init> | undefined>();

	// ── Theme tokens (ECharts can't read CSS vars directly) ──────────────
	let brandPrimary = $state("#0177fb");
	let brandPrimaryDim = $state("rgba(1, 119, 251, 0.16)");
	let successColor = $state("#22c55e");
	let dangerColor = $state("#ef4444");
	let textPrimary = $state("#e5e7eb");
	let textSecondary = $state("#9ca3af");
	let textMuted = $state("#6b7280");
	let surfaceElevated = $state("#0d0d0d");
	let borderSubtle = $state("rgba(255, 255, 255, 0.06)");
	let chart1 = $state("#1b365d");
	let chart3 = $state("#ff975a");

	function readChartTokens() {
		if (typeof document === "undefined") return;
		const cs = getComputedStyle(document.documentElement);
		const get = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb;
		brandPrimary = get("--ii-brand-primary", "#0177fb");
		brandPrimaryDim = `color-mix(in srgb, ${brandPrimary} 16%, transparent)`;
		successColor = get("--ii-success", "#22c55e");
		dangerColor = get("--ii-danger", "#ef4444");
		textPrimary = get("--ii-text-primary", "#e5e7eb");
		textSecondary = get("--ii-text-secondary", "#9ca3af");
		textMuted = get("--ii-text-muted", "#6b7280");
		surfaceElevated = get("--ii-surface-elevated", "#0d0d0d");
		borderSubtle = get("--ii-border-subtle", "rgba(255, 255, 255, 0.06)");
		chart1 = get("--ii-chart-1", "#1b365d");
		chart3 = get("--ii-chart-3", "#ff975a");
	}

	$effect(() => {
		readChartTokens();
		if (typeof document === "undefined") return;
		const obs = new MutationObserver(() => readChartTokens());
		obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
		return () => obs.disconnect();
	});

	// ── Indicator math (pure, frozen, client-side for Tier A) ────────────
	// Tech-debt §4a queues moving these to backend pre-compute.
	function smaSeries(values: number[], period: number): (number | null)[] {
		const out: (number | null)[] = new Array(values.length).fill(null);
		let sum = 0;
		for (let i = 0; i < values.length; i++) {
			sum += values[i]!;
			if (i >= period) sum -= values[i - period]!;
			if (i >= period - 1) out[i] = sum / period;
		}
		return out;
	}

	function emaSeries(values: number[], period: number): (number | null)[] {
		const out: (number | null)[] = new Array(values.length).fill(null);
		if (values.length < period) return out;
		const k = 2 / (period + 1);
		// Seed with SMA of first window.
		let prev = 0;
		for (let i = 0; i < period; i++) prev += values[i]!;
		prev /= period;
		out[period - 1] = prev;
		for (let i = period; i < values.length; i++) {
			prev = values[i]! * k + prev * (1 - k);
			out[i] = prev;
		}
		return out;
	}

	function bollingerBands(values: number[], period: number, mult: number) {
		const sma = smaSeries(values, period);
		const upper: (number | null)[] = new Array(values.length).fill(null);
		const lower: (number | null)[] = new Array(values.length).fill(null);
		for (let i = period - 1; i < values.length; i++) {
			const mean = sma[i]!;
			let varianceSum = 0;
			for (let j = i - period + 1; j <= i; j++) {
				const d = values[j]! - mean;
				varianceSum += d * d;
			}
			const std = Math.sqrt(varianceSum / period);
			upper[i] = mean + mult * std;
			lower[i] = mean - mult * std;
		}
		return { upper, lower };
	}

	// ── Derived: visible window based on activeRange ─────────────────────
	let visibleBars = $derived.by(() => {
		if (bars.length === 0) return bars;
		if (activeRange === "Max") return bars;
		const days = RANGE_DAYS[activeRange];
		const cutoff = bars[bars.length - 1]!.time - days * 24 * 60 * 60 * 1000;
		// Find first index >= cutoff via binary search.
		let lo = 0, hi = bars.length - 1, idx = 0;
		while (lo <= hi) {
			const mid = (lo + hi) >> 1;
			if (bars[mid]!.time >= cutoff) { idx = mid; hi = mid - 1; }
			else lo = mid + 1;
		}
		return bars.slice(idx);
	});

	// ── Derived: rebased values (% mode) ─────────────────────────────────
	let displayBars = $derived.by(() => {
		if (!percentMode || visibleBars.length === 0) return visibleBars;
		const base = visibleBars[0]!.close;
		if (base === 0) return visibleBars;
		return visibleBars.map((b) => ({
			...b,
			open: ((b.open - base) / base) * 100,
			high: ((b.high - base) / base) * 100,
			low: ((b.low - base) / base) * 100,
			close: ((b.close - base) / base) * 100,
		}));
	});

	let closeValues = $derived(displayBars.map((b) => b.close));
	let timeValues = $derived(displayBars.map((b) => b.time));

	let sma20 = $derived(activeIndicators.has("sma20") ? smaSeries(closeValues, 20) : null);
	let sma50 = $derived(activeIndicators.has("sma50") ? smaSeries(closeValues, 50) : null);
	let ema20 = $derived(activeIndicators.has("ema20") ? emaSeries(closeValues, 20) : null);
	let bbands = $derived(activeIndicators.has("bbands20") ? bollingerBands(closeValues, 20, 2) : null);

	// ── Header summary ───────────────────────────────────────────────────
	let livePrice = $derived.by(() => {
		const t = ticker?.trim().toUpperCase();
		if (!t) return null;
		const tick = marketStore?.priceMap[t];
		if (tick?.price) return Number(tick.price);
		if (bars.length > 0) return bars[bars.length - 1]!.close;
		return null;
	});

	let livePctChange = $derived.by(() => {
		if (visibleBars.length < 2 || livePrice == null) return null;
		const base = visibleBars[0]!.close;
		if (base === 0) return null;
		return (livePrice - base) / base;
	});

	// ── ECharts option builder ───────────────────────────────────────────
	let option = $derived.by(() => {
		if (displayBars.length === 0) return {};

		const t = ticker?.trim().toUpperCase() || "—";
		const yIsLog = logScale && !percentMode && chartType !== "candle";
		const lastBar = displayBars[displayBars.length - 1]!;
		const lastValue = chartType === "candle" ? lastBar.close : lastBar.close;
		const lastUp = displayBars.length < 2 || lastValue >= displayBars[displayBars.length - 2]!.close;

		// Build the price series based on chart type.
		const priceSeries: Record<string, unknown>[] = [];

		if (chartType === "candle") {
			priceSeries.push({
				name: t,
				type: "candlestick",
				xAxisIndex: 0,
				yAxisIndex: 0,
				// ECharts candlestick data: [open, close, low, high]
				data: displayBars.map((b) => [b.open, b.close, b.low, b.high]),
				itemStyle: {
					color: successColor,
					color0: dangerColor,
					borderColor: successColor,
					borderColor0: dangerColor,
				},
				large: true,
				largeThreshold: 600,
				progressive: 2000,
				progressiveThreshold: 5000,
			});
		} else {
			// line / area
			const isArea = chartType === "area";
			priceSeries.push({
				name: t,
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				data: displayBars.map((b) => b.close),
				showSymbol: false,
				symbol: "circle",
				symbolSize: 6,
				smooth: false,
				sampling: "lttb",
				progressive: 2000,
				progressiveThreshold: 5000,
				large: true,
				largeThreshold: 2000,
				lineStyle: { width: 1.6, color: brandPrimary },
				itemStyle: { color: brandPrimary },
				// Subtle area fill — gradient from brandPrimary @ 14% to transparent.
				...(isArea
					? {
						areaStyle: {
							color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
								{ offset: 0, color: brandPrimaryDim },
								{ offset: 1, color: "rgba(0,0,0,0)" },
							]),
						},
					}
					: {}),
				// Last-price callout pill — markPoint anchored at the rightmost bar.
				markPoint: {
					symbol: "rect",
					symbolSize: [56, 18],
					symbolOffset: [28, 0],
					silent: true,
					data: [{
						name: "last",
						coord: [displayBars.length - 1, lastValue],
						value: lastValue,
						itemStyle: { color: lastUp ? successColor : dangerColor },
						label: {
							show: true,
							color: "#ffffff",
							fontSize: 11,
							fontWeight: 700,
							formatter: () => percentMode ? `${formatNumber(lastValue, 2)}%` : formatNumber(lastValue, 2),
						},
					}],
				},
			});
		}

		// Indicator overlays — flat lines, no markers, no area.
		if (sma20) {
			priceSeries.push({
				name: "SMA 20",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				data: sma20,
				showSymbol: false,
				smooth: false,
				sampling: "lttb",
				lineStyle: { width: 1, color: chart3, type: "solid" },
				z: 3,
			});
		}
		if (sma50) {
			priceSeries.push({
				name: "SMA 50",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				data: sma50,
				showSymbol: false,
				smooth: false,
				sampling: "lttb",
				lineStyle: { width: 1, color: chart1, type: "solid" },
				z: 3,
			});
		}
		if (ema20) {
			priceSeries.push({
				name: "EMA 20",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				data: ema20,
				showSymbol: false,
				smooth: false,
				sampling: "lttb",
				lineStyle: { width: 1, color: textSecondary, type: "dashed" },
				z: 3,
			});
		}
		if (bbands) {
			priceSeries.push({
				name: "BB Upper",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				data: bbands.upper,
				showSymbol: false,
				smooth: false,
				sampling: "lttb",
				lineStyle: { width: 0.8, color: textMuted, type: "dashed" },
				z: 2,
			});
			priceSeries.push({
				name: "BB Lower",
				type: "line",
				xAxisIndex: 0,
				yAxisIndex: 0,
				data: bbands.lower,
				showSymbol: false,
				smooth: false,
				sampling: "lttb",
				lineStyle: { width: 0.8, color: textMuted, type: "dashed" },
				// Fill between upper and lower via stacked area trick — keep simple, skip for Tier A.
				z: 2,
			});
		}

		// Volume sub-pane — always on.
		priceSeries.push({
			name: "Volume",
			type: "bar",
			xAxisIndex: 1,
			yAxisIndex: 1,
			data: displayBars.map((b, i) => {
				const up = i === 0 || b.close >= displayBars[i - 1]!.close;
				return {
					value: b.volume,
					itemStyle: { color: up ? successColor : dangerColor, opacity: 0.45 },
				};
			}),
			large: true,
			largeThreshold: 2000,
		});

		const xAxisData = timeValues.map((t) => formatTimeLabel(t, granularity));

		return {
			...globalChartOptions,
			animation: true,
			animationDuration: 200,
			grid: [
				// Main grid: top 75%
				{ left: 56, right: 84, top: 16, bottom: "30%", containLabel: false },
				// Volume sub-pane: bottom 22%
				{ left: 56, right: 84, top: "76%", bottom: 28, containLabel: false },
			],
			xAxis: [
				{
					type: "category",
					gridIndex: 0,
					data: xAxisData,
					boundaryGap: chartType === "candle",
					axisLine: { lineStyle: { color: borderSubtle } },
					axisTick: { show: false },
					axisLabel: { show: false },
					splitLine: { show: false },
					axisPointer: { z: 100 },
				},
				{
					type: "category",
					gridIndex: 1,
					data: xAxisData,
					boundaryGap: chartType === "candle",
					axisLine: { lineStyle: { color: borderSubtle } },
					axisTick: { show: false },
					axisLabel: { color: textMuted, fontSize: 10 },
					splitLine: { show: false },
				},
			],
			yAxis: [
				{
					type: yIsLog ? "log" : "value",
					gridIndex: 0,
					scale: true,
					position: "right",
					axisLine: { show: false },
					axisTick: { show: false },
					axisLabel: {
						color: textSecondary,
						fontSize: 10,
						formatter: (v: number) => percentMode ? `${formatNumber(v, 1)}%` : formatNumber(v, 2),
					},
					splitLine: { lineStyle: { color: borderSubtle, type: "dashed" } },
				},
				{
					type: "value",
					gridIndex: 1,
					scale: true,
					position: "right",
					axisLine: { show: false },
					axisTick: { show: false },
					axisLabel: {
						color: textMuted,
						fontSize: 9,
						formatter: (v: number) => formatVolumeLabel(v),
					},
					splitLine: { show: false },
				},
			],
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "cross", link: [{ xAxisIndex: "all" }], crossStyle: { color: textMuted } },
				backgroundColor: surfaceElevated,
				borderColor: borderSubtle,
				borderWidth: 1,
				padding: [8, 12],
				textStyle: { color: textPrimary, fontSize: 11 },
				formatter: (params: unknown) => buildTooltip(params, t),
			},
			axisPointer: { link: [{ xAxisIndex: "all" }] },
			dataZoom: [
				{ type: "inside", xAxisIndex: [0, 1], filterMode: "none", zoomOnMouseWheel: true, moveOnMouseMove: true },
			],
			toolbox: { show: false },
			series: priceSeries,
		};
	});

	// Tooltip builder — extracted to keep the option block readable.
	function buildTooltip(params: unknown, t: string): string {
		const list = Array.isArray(params) ? params : [];
		if (list.length === 0) return "";
		const first = list[0] as { axisValueLabel?: string; dataIndex?: number };
		const i = first.dataIndex ?? 0;
		const bar = displayBars[i];
		if (!bar) return "";

		const dateLabel = formatTimeLabel(bar.time, granularity);
		const priceFmt = (v: number) => percentMode ? `${formatNumber(v, 2)}%` : formatNumber(v, 2);

		let html = `<div style="font-weight:700;margin-bottom:4px">${t} · ${dateLabel}</div>`;
		html += `<div style="display:grid;grid-template-columns:auto auto;gap:2px 12px;font-variant-numeric:tabular-nums">`;
		if (chartType === "candle") {
			html += `<span>Open</span><span style="text-align:right">${priceFmt(bar.open)}</span>`;
			html += `<span>High</span><span style="text-align:right">${priceFmt(bar.high)}</span>`;
			html += `<span>Low</span><span style="text-align:right">${priceFmt(bar.low)}</span>`;
		}
		html += `<span>Close</span><span style="text-align:right;font-weight:700">${priceFmt(bar.close)}</span>`;
		if (sma20 && sma20[i] != null) html += `<span>SMA 20</span><span style="text-align:right">${priceFmt(sma20[i] as number)}</span>`;
		if (sma50 && sma50[i] != null) html += `<span>SMA 50</span><span style="text-align:right">${priceFmt(sma50[i] as number)}</span>`;
		if (ema20 && ema20[i] != null) html += `<span>EMA 20</span><span style="text-align:right">${priceFmt(ema20[i] as number)}</span>`;
		if (bbands && bbands.upper[i] != null) {
			html += `<span>BB Upper</span><span style="text-align:right">${priceFmt(bbands.upper[i] as number)}</span>`;
			html += `<span>BB Lower</span><span style="text-align:right">${priceFmt(bbands.lower[i] as number)}</span>`;
		}
		html += `<span>Volume</span><span style="text-align:right">${formatVolumeLabel(bar.volume)}</span>`;
		html += `</div>`;
		return html;
	}

	function formatTimeLabel(t: number, g: Granularity): string {
		const d = new Date(t);
		if (g === "daily") {
			return d.toLocaleDateString(undefined, { month: "short", day: "2-digit", year: "numeric" });
		}
		return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
	}

	function formatVolumeLabel(v: number): string {
		if (v >= 1e9) return `${formatNumber(v / 1e9, 2)}B`;
		if (v >= 1e6) return `${formatNumber(v / 1e6, 2)}M`;
		if (v >= 1e3) return `${formatNumber(v / 1e3, 1)}K`;
		return formatNumber(v, 0);
	}

	// ── Fetch on ticker / granularity change ─────────────────────────────
	$effect(() => {
		const t = ticker?.trim().toUpperCase();
		const g = granularity;
		if (!t) return;

		let cancelled = false;
		loading = true;
		error = null;

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				type RawBar = {
					timestamp: string;
					open: number;
					high: number;
					low: number;
					close: number;
					volume: number;
				};
				const resp = await api.get<{ bars: RawBar[] }>(
					`/market-data/historical/${encodeURIComponent(t)}?interval=${g}`,
				);
				if (cancelled) return;

				const next: Bar[] = (resp.bars ?? [])
					.map((b) => ({
						time: new Date(b.timestamp).getTime(),
						open: Number(b.open),
						high: Number(b.high),
						low: Number(b.low),
						close: Number(b.close),
						volume: Number(b.volume ?? 0),
					}))
					.filter((b) => Number.isFinite(b.close))
					.sort((a, b) => a.time - b.time);

				bars = next;
			} catch (e) {
				if (!cancelled) error = e instanceof Error ? e.message : "Failed to load chart";
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		// Pre-warm WS subscription so live tick fold works.
		marketStore?.subscribe([t]);

		return () => {
			cancelled = true;
		};
	});

	// ── Live tick fold ───────────────────────────────────────────────────
	// Read marketStore.priceMap[ticker] — Svelte 5 wires this $effect to the
	// rune so every IEX trade triggers a surgical setOption() instead of a
	// full re-render.
	$effect(() => {
		if (!marketStore || !chart) return;
		const t = ticker?.trim().toUpperCase();
		if (!t || bars.length === 0) return;

		const tick = marketStore.priceMap[t];
		if (!tick || !tick.price) return;

		const last = bars[bars.length - 1]!;
		const tickTime = tick.timestamp ? new Date(tick.timestamp).getTime() : Date.now();
		const lastDay = new Date(last.time).toISOString().slice(0, 10);
		const tickDay = new Date(tickTime).toISOString().slice(0, 10);
		// Daily bars are immutable for prior sessions — only fold same-day ticks.
		if (granularity === "daily" && lastDay !== tickDay) return;

		const price = Number(tick.price);
		const newHigh = Math.max(last.high, price);
		const newLow = Math.min(last.low, price);
		const tickVol = Number(tick.volume ?? 0);
		const newVolume = last.volume + tickVol;

		// Skip duplicate ticks (firehose dedupe).
		if (last.close === price && last.high === newHigh && last.low === newLow) return;

		// Mutate the in-memory bar (kept in sync with what's drawn).
		const patched = { ...last, close: price, high: newHigh, low: newLow, volume: newVolume };
		bars = [...bars.slice(0, -1), patched];
		// `bars` is reactive — `option` $derived recomputes — ChartContainer's
		// $effect calls setOption with notMerge:true. The line series is short
		// enough that this is fine; for tighter perf the bind:chart hook lets
		// callers do a replaceMerge here directly. We rely on the derived path
		// for now to keep the code path single.
	});

	// ── UI handlers ──────────────────────────────────────────────────────
	function selectGranularity(g: Granularity) {
		granularity = g;
		granularityOpen = false;
	}

	function toggleIndicator(id: IndicatorId) {
		const next = new Set(activeIndicators);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		activeIndicators = next;
	}

	function selectChartType(c: ChartType) {
		chartType = c;
		chartTypeOpen = false;
		// Candlestick + log scale don't compose in ECharts; force linear.
		if (c === "candle") logScale = false;
		// Candlestick + percent mode also doesn't make sense (rebased OHLC
		// loses meaning); force off.
		if (c === "candle") percentMode = false;
	}

	// Close popovers on outside click.
	let rootEl: HTMLDivElement | undefined = $state();
	onMount(() => {
		const onClick = (e: MouseEvent) => {
			if (!rootEl || !rootEl.contains(e.target as Node)) {
				granularityOpen = false;
				indicatorsOpen = false;
				chartTypeOpen = false;
			}
		};
		document.addEventListener("click", onClick);
		return () => document.removeEventListener("click", onClick);
	});
</script>

<div class="adv-chart" bind:this={rootEl}>
	<!-- ── Header bar (left: ticker pill / right: controls) ─────── -->
	<header class="adv-chart-header">
		<div class="adv-chart-title">
			<span class="adv-chart-pill">
				<span class="adv-chart-ticker">{ticker || "—"}</span>
				<span class="adv-chart-sep">·</span>
				<span class="adv-chart-meta">{GRANULARITY_LABEL[granularity]}</span>
				<span class="adv-chart-sep">·</span>
				<span class="adv-chart-meta">{activeRange}</span>
			</span>
			{#if livePrice != null}
				<span class="adv-chart-price">{percentMode ? `${formatNumber(((livePrice - (visibleBars[0]?.close ?? livePrice)) / (visibleBars[0]?.close || 1)) * 100, 2)}%` : formatCurrency(livePrice)}</span>
				{#if livePctChange != null}
					<span class="adv-chart-delta" class:delta-up={livePctChange >= 0} class:delta-down={livePctChange < 0}>
						{livePctChange >= 0 ? "▲" : "▼"} {formatPercent(livePctChange, 2)}
					</span>
				{/if}
			{/if}
		</div>

		<div class="adv-chart-controls">
			<!-- Granularity dropdown -->
			<div class="adv-chart-popover-wrap">
				<button
					type="button"
					class="adv-chart-btn"
					onclick={(e) => { e.stopPropagation(); granularityOpen = !granularityOpen; indicatorsOpen = false; chartTypeOpen = false; }}
				>
					{GRANULARITY_LABEL[granularity]}
					<span class="adv-chart-caret">▾</span>
				</button>
				{#if granularityOpen}
					<div class="adv-chart-popover">
						{#each GRANULARITIES as g (g)}
							<button
								type="button"
								class="adv-chart-popover-item"
								class:adv-chart-popover-item--active={granularity === g}
								onclick={(e) => { e.stopPropagation(); selectGranularity(g); }}
							>
								{GRANULARITY_LABEL[g]}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Chart type dropdown -->
			<div class="adv-chart-popover-wrap">
				<button
					type="button"
					class="adv-chart-btn"
					onclick={(e) => { e.stopPropagation(); chartTypeOpen = !chartTypeOpen; indicatorsOpen = false; granularityOpen = false; }}
					title="Chart type"
				>
					{CHART_TYPES.find((c) => c.id === chartType)?.label ?? "Line"}
					<span class="adv-chart-caret">▾</span>
				</button>
				{#if chartTypeOpen}
					<div class="adv-chart-popover">
						{#each CHART_TYPES as c (c.id)}
							<button
								type="button"
								class="adv-chart-popover-item"
								class:adv-chart-popover-item--active={chartType === c.id}
								onclick={(e) => { e.stopPropagation(); selectChartType(c.id); }}
							>
								{c.label}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Indicators dropdown -->
			<div class="adv-chart-popover-wrap">
				<button
					type="button"
					class="adv-chart-btn"
					onclick={(e) => { e.stopPropagation(); indicatorsOpen = !indicatorsOpen; granularityOpen = false; chartTypeOpen = false; }}
				>
					Indicators ({activeIndicators.size})
					<span class="adv-chart-caret">▾</span>
				</button>
				{#if indicatorsOpen}
					<div class="adv-chart-popover adv-chart-popover--wide">
						{#each Object.entries(INDICATOR_LABEL) as [id, label] (id)}
							<button
								type="button"
								class="adv-chart-popover-item adv-chart-popover-item--checkable"
								onclick={(e) => { e.stopPropagation(); toggleIndicator(id as IndicatorId); }}
							>
								<span class="adv-chart-check" class:adv-chart-check--on={activeIndicators.has(id as IndicatorId)}>
									{activeIndicators.has(id as IndicatorId) ? "✓" : ""}
								</span>
								{label}
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</header>

	<!-- ── Chart canvas ─────────────────────────────────────────── -->
	<div class="adv-chart-stage" style:height="{height - 92}px">
		<ChartContainer
			{option}
			height={height - 92}
			loading={loading && bars.length === 0}
			empty={!loading && bars.length === 0}
			emptyMessage={error ?? `No data for ${ticker || "selected ticker"}`}
			ariaLabel="Advanced market chart"
			bind:chart
		/>
	</div>

	<!-- ── Bottom range chips + scale toggles ───────────────────── -->
	<footer class="adv-chart-footer">
		<div class="adv-chart-ranges">
			{#each RANGES as r (r)}
				<button
					type="button"
					class="adv-chart-range"
					class:adv-chart-range--active={activeRange === r}
					onclick={() => (activeRange = r)}
				>
					{r}
				</button>
			{/each}
		</div>
		<div class="adv-chart-scale-toggles">
			<button
				type="button"
				class="adv-chart-toggle"
				class:adv-chart-toggle--active={percentMode}
				disabled={chartType === "candle"}
				onclick={() => (percentMode = !percentMode)}
				title={chartType === "candle" ? "Percent mode unavailable for candlestick" : "Toggle percent change view"}
			>
				%
			</button>
			<button
				type="button"
				class="adv-chart-toggle"
				class:adv-chart-toggle--active={logScale}
				disabled={chartType === "candle" || percentMode}
				onclick={() => (logScale = !logScale)}
				title={chartType === "candle" ? "Log scale unavailable for candlestick" : "Toggle log scale"}
			>
				log
			</button>
		</div>
	</footer>
</div>

<style>
	.adv-chart {
		display: flex;
		flex-direction: column;
		gap: 8px;
		width: 100%;
		font-family: var(--ii-font-sans, Urbanist, system-ui, sans-serif);
	}

	/* ── Header bar ────────────────────────────────────────────── */
	.adv-chart-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
	}

	.adv-chart-title {
		display: flex;
		align-items: baseline;
		gap: 12px;
		font-variant-numeric: tabular-nums;
	}

	.adv-chart-pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 999px;
		background: color-mix(in srgb, var(--ii-surface-elevated) 60%, transparent);
		font-size: 11px;
		color: var(--ii-text-secondary);
	}

	.adv-chart-ticker {
		font-weight: 700;
		color: var(--ii-text-primary);
		letter-spacing: 0.02em;
	}

	.adv-chart-meta {
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.adv-chart-sep {
		color: var(--ii-text-muted);
	}

	.adv-chart-price {
		font-size: 16px;
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.adv-chart-delta {
		font-size: 11px;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--ii-text-primary) 4%, transparent);
	}

	.delta-up   { color: var(--ii-success); }
	.delta-down { color: var(--ii-danger); }

	/* ── Controls (granularity / chart type / indicators dropdowns) ─ */
	.adv-chart-controls {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.adv-chart-popover-wrap {
		position: relative;
	}

	.adv-chart-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px;
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-secondary);
		background: transparent;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 6px;
		cursor: pointer;
		transition: all 120ms ease;
		font-family: inherit;
	}

	.adv-chart-btn:hover {
		color: var(--ii-text-primary);
		background: color-mix(in srgb, var(--ii-text-primary) 4%, transparent);
	}

	.adv-chart-caret {
		font-size: 9px;
		color: var(--ii-text-muted);
	}

	.adv-chart-popover {
		position: absolute;
		top: calc(100% + 4px);
		right: 0;
		min-width: 140px;
		padding: 4px;
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border-subtle);
		border-radius: 8px;
		box-shadow: 0 8px 24px color-mix(in srgb, var(--ii-text-primary) 12%, transparent);
		z-index: 20;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.adv-chart-popover--wide {
		min-width: 200px;
	}

	.adv-chart-popover-item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 10px;
		font-size: 11px;
		font-weight: 500;
		color: var(--ii-text-secondary);
		background: transparent;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		text-align: left;
		transition: background 100ms ease;
		font-family: inherit;
	}

	.adv-chart-popover-item:hover {
		background: color-mix(in srgb, var(--ii-text-primary) 5%, transparent);
		color: var(--ii-text-primary);
	}

	.adv-chart-popover-item--active {
		color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
	}

	.adv-chart-popover-item--checkable {
		justify-content: flex-start;
	}

	.adv-chart-check {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 14px;
		height: 14px;
		border: 1px solid var(--ii-border);
		border-radius: 3px;
		font-size: 10px;
		font-weight: 700;
		color: var(--ii-brand-primary);
	}

	.adv-chart-check--on {
		background: color-mix(in srgb, var(--ii-brand-primary) 14%, transparent);
		border-color: var(--ii-brand-primary);
	}

	/* ── Chart stage ───────────────────────────────────────────── */
	.adv-chart-stage {
		position: relative;
		width: 100%;
	}

	/* ── Footer (range chips + scale toggles) ──────────────────── */
	.adv-chart-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		padding-top: 4px;
		border-top: 1px solid var(--ii-border-subtle);
	}

	.adv-chart-ranges {
		display: flex;
		gap: 2px;
		flex-wrap: wrap;
	}

	.adv-chart-range {
		padding: 4px 9px;
		font-size: 10px;
		font-weight: 600;
		color: var(--ii-text-muted);
		background: transparent;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		transition: all 100ms ease;
		font-family: inherit;
	}

	.adv-chart-range:hover {
		color: var(--ii-text-primary);
		background: color-mix(in srgb, var(--ii-text-primary) 5%, transparent);
	}

	.adv-chart-range--active {
		color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 12%, transparent);
	}

	.adv-chart-scale-toggles {
		display: flex;
		gap: 2px;
	}

	.adv-chart-toggle {
		padding: 4px 10px;
		font-size: 10px;
		font-weight: 700;
		text-transform: lowercase;
		color: var(--ii-text-muted);
		background: transparent;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 4px;
		cursor: pointer;
		transition: all 100ms ease;
		font-family: inherit;
	}

	.adv-chart-toggle:hover:not(:disabled) {
		color: var(--ii-text-primary);
	}

	.adv-chart-toggle:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}

	.adv-chart-toggle--active {
		color: var(--ii-brand-primary);
		border-color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
	}
</style>
