<!--
  MacroRegimePanel -- 4-region dense regime table for Live Workbench.

  Data source: GET /macro/regional-regime.
  Renders US / EU / EM / BR rows with quadrant label, stress badge,
  and directional growth trend.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { createClientApiClient } from "../../../api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface RegionalRegimeRow {
		region_code: string;
		regime_label: string;
		stress_level: "LOW" | "MED" | "HIGH";
		trend_up: boolean;
		growth_score: number | null;
		inflation_score: number | null;
	}

	let regions = $state<RegionalRegimeRow[]>([]);
	let loading = $state(true);

	async function fetchRegimes(cancelled: () => boolean) {
		loading = true;
		try {
			const res = await api.get<{ regions: RegionalRegimeRow[] }>("/macro/regional-regime");
			if (!cancelled()) {
				regions = res.regions ?? [];
			}
		} catch {
			if (!cancelled()) {
				regions = [];
			}
		} finally {
			if (!cancelled()) {
				loading = false;
			}
		}
	}

	$effect(() => {
		let dead = false;
		void fetchRegimes(() => dead);
		const id = setInterval(() => void fetchRegimes(() => dead), 60_000);
		return () => {
			dead = true;
			clearInterval(id);
		};
	});

	function regimeToneClass(label: string): string {
		const normalized = label.toUpperCase();
		if (normalized === "GOLDILOCKS") return "mrg-goldilocks";
		if (normalized === "OVERHEATING") return "mrg-overheating";
		if (normalized === "STAGFLATION") return "mrg-stagflation";
		if (normalized === "REFLATION") return "mrg-reflation";
		return "";
	}
</script>

<div class="mrg-root">
	<div class="mrg-header">
		<span class="mrg-title">MACRO REGIME</span>
		{#if loading}<span class="mrg-loading">...</span>{/if}
	</div>

	<div class="mrg-table">
		{#each regions as region (region.region_code)}
			<div class="mrg-row">
				<span class="mrg-code">{region.region_code}</span>
				<span class="mrg-label {regimeToneClass(region.regime_label)}">
					{region.regime_label}
				</span>
				<span class="mrg-stress mrg-stress-{region.stress_level.toLowerCase()}">
					{region.stress_level}
				</span>
				<span class="mrg-trend" class:up={region.trend_up} class:down={!region.trend_up}>
					{region.trend_up ? "↑" : "↓"}
				</span>
			</div>
		{/each}
		{#if !loading && regions.length === 0}
			<div class="mrg-empty">No regime data</div>
		{/if}
	</div>
</div>

<style>
	.mrg-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.mrg-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.mrg-title,
	.mrg-loading {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.mrg-loading {
		color: var(--terminal-fg-muted);
	}

	.mrg-table {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: var(--terminal-space-1) 0;
	}

	.mrg-row {
		display: grid;
		grid-template-columns: 36px 1fr auto auto;
		align-items: center;
		gap: 8px;
		height: 22px;
		padding: 0 var(--terminal-space-2);
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
		font-size: var(--terminal-text-10);
	}

	.mrg-code {
		color: var(--terminal-fg-secondary);
		font-weight: 700;
		letter-spacing: 0.06em;
	}

	.mrg-label {
		overflow: hidden;
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-overflow: ellipsis;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.mrg-goldilocks { color: var(--terminal-status-success); }
	.mrg-overheating { color: var(--terminal-status-warn, var(--terminal-accent-amber)); }
	.mrg-stagflation { color: var(--terminal-status-error); }
	.mrg-reflation { color: var(--terminal-accent-cyan); }

	.mrg-stress {
		border: 1px solid currentColor;
		border-radius: 2px;
		padding: 1px 5px;
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.06em;
	}

	.mrg-stress-low { color: var(--terminal-status-success); }
	.mrg-stress-med { color: var(--terminal-status-warn, var(--terminal-accent-amber)); }
	.mrg-stress-high { color: var(--terminal-status-error); }

	.mrg-trend {
		font-size: 12px;
		font-weight: 700;
		line-height: 1;
	}

	.mrg-trend.up { color: var(--terminal-status-success); }
	.mrg-trend.down { color: var(--terminal-status-error); }

	.mrg-empty {
		padding: 24px 12px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-10);
		text-align: center;
	}
</style>
