<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatNumber } from "@investintell/ui";

	interface Exposure {
		label: string;
		value: number;
		significance: "high" | "medium" | "low" | "none";
	}

	let {
		exposures = [],
		loading = false,
		error = null,
	}: {
		exposures?: Exposure[];
		loading?: boolean;
		error?: string | null;
	} = $props();

	const significanceOpacity: Record<Exposure["significance"], number> = {
		high: 0.96,
		medium: 0.78,
		low: 0.58,
		none: 0.34,
	};

	const option = $derived.by(() =>
		({
			backgroundColor: "transparent",
			grid: { left: 128, right: 24, top: 24, bottom: 20 },
			xAxis: {
				type: "value",
				axisLine: { lineStyle: { color: "var(--ii-border)" } },
				splitLine: { lineStyle: { color: "var(--ii-border)", type: "dashed" } },
				axisLabel: {
					formatter: (value: number) => formatNumber(value, 2),
					color: "var(--ii-text-muted)",
				},
			},
			yAxis: {
				type: "category",
				data: exposures.map((item) => item.label),
				inverse: true,
				axisLabel: { color: "var(--ii-text-muted)" },
			},
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				formatter: (params: Array<{ dataIndex?: number }>) => {
					const item = exposures[params[0]?.dataIndex ?? -1];
					if (!item) return "";
					return [
						`<strong>${item.label}</strong>`,
						`Sensitivity: ${formatNumber(item.value, 3)}`,
						`Signal strength: ${item.significance}`,
					].join("<br/>");
				},
			},
			series: [
				{
					type: "bar",
					data: exposures.map((item) => ({
						value: item.value,
						itemStyle: {
							color: item.value >= 0 ? "#0ea5e9" : "#f97316",
							opacity: significanceOpacity[item.significance],
							borderRadius: item.value >= 0 ? [0, 8, 8, 0] : [8, 0, 0, 8],
						},
					})),
				},
			],
		}) as Record<string, unknown>,
	);
</script>

<div class="research-card">
	<div class="research-card__header">
		<h2>Market Sensitivities</h2>
		<p>Directional response to major market drivers, with intensity handled on the backend.</p>
	</div>
	<ChartContainer
		height={420}
		option={option}
		loading={loading}
		empty={!loading && exposures.length === 0}
		emptyMessage={error ?? "No sensitivities available for this fund."}
		ariaLabel="Market sensitivities bar chart"
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
