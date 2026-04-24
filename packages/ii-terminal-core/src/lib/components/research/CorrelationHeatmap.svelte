<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { formatNumber } from "@investintell/ui";

	interface CorrelationPayload {
		labels: string[];
		historical_matrix: number[][];
		structural_matrix: number[][];
		regime_state_at_calc: string | null;
		effective_window_days: number;
	}

	let {
		payload = null,
		mode = "structural",
		loading = false,
		error = null,
		onModeChange,
	}: {
		payload?: CorrelationPayload | null;
		mode?: "structural" | "historical";
		loading?: boolean;
		error?: string | null;
		onModeChange?: (mode: "structural" | "historical") => void;
	} = $props();

	const activeMatrix = $derived(
		mode === "historical" ? payload?.historical_matrix ?? [] : payload?.structural_matrix ?? [],
	);

	const tuples = $derived.by(() => {
		const labels = payload?.labels ?? [];
		return activeMatrix.flatMap((row, y) =>
			row.map((value, x) => [x, y, Number(value.toFixed(3))] as [number, number, number]),
		);
	});

	const option = $derived.by(() =>
		({
			backgroundColor: "transparent",
			grid: { left: 120, right: 40, top: 24, bottom: 90 },
			xAxis: {
				type: "category",
				data: payload?.labels ?? [],
				axisLine: { lineStyle: { color: "var(--ii-border)" } },
				axisLabel: {
					rotate: 55,
					fontSize: 10,
					interval: 0,
					color: "var(--ii-text-muted)",
				},
			},
			yAxis: {
				type: "category",
				data: payload?.labels ?? [],
				axisLine: { lineStyle: { color: "var(--ii-border)" } },
				axisLabel: {
					fontSize: 10,
					interval: 0,
					color: "var(--ii-text-muted)",
				},
			},
			visualMap: {
				min: -1,
				max: 1,
				orient: "horizontal",
				left: "center",
				bottom: 12,
				calculable: false,
				inRange: {
					color: ["#0f172a", "#0ea5e9", "#f8fafc", "#f59e0b", "#7f1d1d"],
				},
			},
			tooltip: {
				position: "top",
				formatter: (params: { data: [number, number, number] }) => {
					const [x, y, value] = params.data;
					const labels = payload?.labels ?? [];
					return [
						`<strong>${labels[x] ?? "—"}</strong>`,
						`${labels[y] ?? "—"}`,
						`${mode === "historical" ? "Historical Correlation" : "Structural Correlation"}: ${formatNumber(value, 3)}`,
					].join("<br/>");
				},
			},
			series: [
				{
					type: "heatmap",
					data: tuples,
					label: { show: payload != null && payload.labels.length <= 18, fontSize: 9 },
				},
			],
		}) as Record<string, unknown>,
	);
</script>

<div class="research-card">
	<div class="research-card__header">
		<div>
			<h2>Structural Correlation</h2>
			<p>
				{#if payload}
					{payload.effective_window_days} aligned observations
					{#if payload.regime_state_at_calc}
						· regime {payload.regime_state_at_calc}
					{/if}
				{:else}
					Institutional view of cross-fund linkage.
				{/if}
			</p>
		</div>
		<div class="toggle-strip">
			<button
				class:toggle-strip__active={mode === "structural"}
				onclick={() => onModeChange?.("structural")}
			>
				Structural
			</button>
			<button
				class:toggle-strip__active={mode === "historical"}
				onclick={() => onModeChange?.("historical")}
			>
				Historical
			</button>
		</div>
	</div>
	<ChartContainer
		height={540}
		option={option}
		loading={loading}
		empty={!loading && (!payload || activeMatrix.length === 0)}
		emptyMessage={error ?? "No correlation matrix available."}
		ariaLabel="Correlation heatmap"
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

	.research-card__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		flex-wrap: wrap;
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

	.toggle-strip {
		display: inline-flex;
		gap: 4px;
		padding: 4px;
		border: 1px solid var(--ii-border);
		border-radius: 999px;
		background: color-mix(in srgb, var(--ii-surface-elevated) 92%, transparent);
	}

	.toggle-strip button {
		border: 0;
		background: transparent;
		color: var(--ii-text-muted);
		padding: 6px 10px;
		border-radius: 999px;
		cursor: pointer;
		font-size: 0.8125rem;
	}

	.toggle-strip__active {
		background: color-mix(in srgb, var(--ii-brand-primary) 16%, transparent);
		color: var(--ii-text-secondary) !important;
	}
</style>
