<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatPercent } from "@investintell/ui";

	interface ScatterPayload {
		instrument_ids: string[];
		names: string[];
		tickers: Array<string | null>;
		expected_returns: Array<number | null>;
		tail_risks: Array<number | null>;
		strategies: string[];
		strategy_map: Record<string, string>;
	}

	let {
		payload = null,
		loading = false,
		error = null,
	}: {
		payload?: ScatterPayload | null;
		loading?: boolean;
		error?: string | null;
	} = $props();

	const palette = [
		"#0ea5e9",
		"#22c55e",
		"#f59e0b",
		"#ef4444",
		"#a855f7",
		"#14b8a6",
		"#f97316",
		"#64748b",
	];

	const chartData = $derived.by(() => {
		if (!payload) return [];
		return payload.instrument_ids
			.map((instrumentId, index) => {
				const expectedReturn = payload.expected_returns[index];
				const tailRisk = payload.tail_risks[index];
				if (expectedReturn == null || tailRisk == null) return null;
				return {
					value: [Math.abs(tailRisk), expectedReturn],
					name: payload.names[index] ?? instrumentId,
					ticker: payload.tickers[index] ?? "—",
					strategy: payload.strategy_map[instrumentId] ?? payload.strategies[index] ?? "Unclassified",
				};
			})
			.filter((item): item is NonNullable<typeof item> => item !== null);
	});

	const strategies = $derived([...new Set(chartData.map((item) => item.strategy))]);

	const option = $derived.by(() => {
		const series = strategies.map((strategy, index) => ({
			type: "scatter",
			name: strategy,
			data: chartData.filter((item) => item.strategy === strategy),
			symbolSize: 11,
			itemStyle: {
				color: palette[index % palette.length],
				opacity: 0.9,
			},
			emphasis: {
				scale: 1.15,
			},
		}));

		return {
			color: palette,
			backgroundColor: "transparent",
			grid: { left: 72, right: 24, top: 32, bottom: 72 },
			xAxis: {
				type: "value",
				name: "Tail Risk",
				nameLocation: "middle",
				nameGap: 42,
				nameTextStyle: { color: "var(--ii-text-muted)" },
				axisLine: { lineStyle: { color: "var(--ii-border)" } },
				splitLine: { lineStyle: { color: "var(--ii-border)", type: "dashed" } },
				axisLabel: {
					formatter: (value: number) => formatPercent(value, 1),
					color: "var(--ii-text-muted)",
				},
			},
			yAxis: {
				type: "value",
				name: "Expected Return",
				nameLocation: "middle",
				nameGap: 52,
				nameTextStyle: { color: "var(--ii-text-muted)" },
				axisLine: { lineStyle: { color: "var(--ii-border)" } },
				splitLine: { lineStyle: { color: "var(--ii-border)", type: "dashed" } },
				axisLabel: {
					formatter: (value: number) => formatPercent(value, 1),
					color: "var(--ii-text-muted)",
				},
			},
			tooltip: {
				trigger: "item",
				formatter: (params: { data?: { name: string; ticker: string; strategy: string; value: [number, number] } }) => {
					const data = params.data;
					if (!data) return "";
					return [
						`<strong>${data.name}</strong>`,
						data.ticker,
						data.strategy,
						`Tail Risk: ${formatPercent(data.value[0], 2)}`,
						`Expected Return: ${formatPercent(data.value[1], 2)}`,
					].join("<br/>");
				},
			},
			legend: {
				show: true,
				top: 0,
				textStyle: {
					color: "var(--ii-text-muted)",
				},
			},
			series,
		} as Record<string, unknown>;
	});
</script>

<div class="research-card">
	<div class="research-card__header">
		<h2>Risk and Return</h2>
		<p>Universe-level view of expected return versus tail risk, colored by mandate.</p>
	</div>
	<ChartContainer
		height={460}
		option={option}
		loading={loading}
		empty={!loading && (!payload || chartData.length === 0)}
		emptyMessage={error ?? "No eligible funds available for this view."}
		ariaLabel="Risk and return scatter"
	/>
</div>

<style>
	.research-card {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 18px;
		border: 1px solid var(--ii-border);
		border-radius: 16px;
		background:
			linear-gradient(180deg, color-mix(in srgb, var(--ii-surface-elevated) 88%, transparent), var(--ii-surface));
	}

	.research-card__header h2 {
		margin: 0 0 4px;
		font-size: 1rem;
		color: var(--ii-text-secondary);
	}

	.research-card__header p {
		margin: 0;
		font-size: 0.875rem;
		color: var(--ii-text-muted);
	}
</style>
