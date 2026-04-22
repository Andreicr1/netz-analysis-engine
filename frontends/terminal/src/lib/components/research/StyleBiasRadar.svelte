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

	const option = $derived.by(() =>
		({
			backgroundColor: "transparent",
			radar: {
				indicator: exposures.map((item) => ({
					name: item.label,
					max: 3,
					min: -3,
				})),
				center: ["50%", "54%"],
				radius: "66%",
				axisName: {
					color: "var(--ii-text-muted)",
				},
				splitLine: { lineStyle: { color: "var(--ii-border)" } },
				splitArea: { areaStyle: { color: ["transparent"] } },
				axisLine: { lineStyle: { color: "var(--ii-border)" } },
			},
			tooltip: {
				formatter: () =>
					exposures
						.map((item) => `${item.label}: ${formatNumber(item.value, 2)} (${item.significance})`)
						.join("<br/>"),
			},
			series: [
				{
					type: "radar",
					data: [
						{
							value: exposures.map((item) => item.value),
							name: "Style Bias",
							areaStyle: { color: "rgba(14, 165, 233, 0.18)" },
							lineStyle: { color: "#0ea5e9", width: 2 },
							itemStyle: { color: "#0ea5e9" },
						},
					],
				},
			],
		}) as Record<string, unknown>,
	);
</script>

<div class="research-card">
	<div class="research-card__header">
		<h2>Style Bias</h2>
		<p>Cross-sectional style readout normalized in the backend for direct comparison.</p>
	</div>
	<ChartContainer
		height={420}
		option={option}
		loading={loading}
		empty={!loading && exposures.length === 0}
		emptyMessage={error ?? "No style profile available for this fund."}
		ariaLabel="Style bias radar chart"
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
