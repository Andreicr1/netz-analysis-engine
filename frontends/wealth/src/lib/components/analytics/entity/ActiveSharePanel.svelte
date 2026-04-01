<!--
  Active Share Panel — eVestment p.73.
  Handles three states:
  1. No benchmark selected → empty state with benchmark selector
  2. Benchmark selected but no data → error/loading message
  3. Data available → hero metric + classification badge + stats
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type { ActiveShareResult } from "$lib/types/analytics";
	import { createClientApiClient } from "$lib/api/client";

	interface Props {
		data: ActiveShareResult | null;
		benchmarkId: string | null;
	}

	let { data, benchmarkId }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Benchmark selector state
	interface BenchmarkOption {
		id: string;
		name: string;
		ticker: string | null;
	}

	let benchmarks: BenchmarkOption[] = $state([]);
	let loadingBenchmarks = $state(false);

	async function fetchBenchmarks() {
		if (benchmarks.length > 0 || loadingBenchmarks) return;
		loadingBenchmarks = true;
		try {
			const api = createClientApiClient(getToken);
			const instruments = await api.get<
				{ instrument_id: string; name: string; ticker: string | null }[]
			>("/instruments", { instrument_type: "fund", is_active: "true" });
			benchmarks = instruments.map((i) => ({
				id: i.instrument_id,
				name: i.name,
				ticker: i.ticker,
			}));
		} catch {
			benchmarks = [];
		} finally {
			loadingBenchmarks = false;
		}
	}

	function selectBenchmark(id: string) {
		if (!id) return;
		const currentUrl = $page.url;
		const params = new URLSearchParams(currentUrl.searchParams);
		params.set("benchmark_id", id);
		goto(`${currentUrl.pathname}?${params.toString()}`, { replaceState: true });
	}

	function fmtPct(v: number): string {
		return formatPercent(v / 100, 2, "en-US", false);
	}

	function fmtEfficiency(v: number | null): string {
		if (v == null) return "\u2014";
		return formatNumber(v, 2, "en-US", { signDisplay: "exceptZero" });
	}

	const classificationMap: Record<string, { color: string; label: string }> = {
		"Stock Picker": { color: "var(--ii-success)", label: "Stock Picker" },
		Active: { color: "var(--ii-brand-primary)", label: "Active" },
		"Moderately Active": { color: "var(--ii-warning)", label: "Moderately Active" },
		"Closet Indexer": { color: "var(--ii-danger)", label: "Closet Indexer" },
	};

	let classification = $derived.by(() => {
		if (!data) return null;
		const as = data.active_share;
		if (as >= 80) return classificationMap["Stock Picker"];
		if (as >= 60) return classificationMap["Active"];
		if (as >= 30) return classificationMap["Moderately Active"];
		return classificationMap["Closet Indexer"];
	});
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Active Share</h2>
	<p class="ea-panel-sub">Holdings-based overlap analysis (eVestment p.73)</p>

	{#if data && classification}
		<!-- ── State 3: Data available ── -->
		<div class="as-hero">
			<div class="as-ring">
				<span class="as-ring-value" style:color={classification.color}>
					{fmtPct(data.active_share)}
				</span>
				<span class="as-ring-label">Active Share</span>
				<span class="as-ring-badge" style:color={classification.color}>
					{classification.label}
				</span>
			</div>
		</div>

		<div class="as-stats">
			<div class="ea-stat">
				<span class="ea-stat-label">Overlap</span>
				<span class="ea-stat-value">{fmtPct(data.overlap)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Efficiency</span>
				<span class="ea-stat-value">{fmtEfficiency(data.active_share_efficiency)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Portfolio Pos.</span>
				<span class="ea-stat-value">{data.n_portfolio_positions}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Benchmark Pos.</span>
				<span class="ea-stat-value">{data.n_benchmark_positions}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Common Pos.</span>
				<span class="ea-stat-value">{data.n_common_positions}</span>
			</div>
		</div>

		{#if data.as_of_date}
			<p class="as-date">As of {data.as_of_date}</p>
		{/if}
	{:else if benchmarkId}
		<!-- ── State 2: Benchmark selected but no data ── -->
		<div class="as-empty">
			<p>Unable to compute Active Share for this benchmark. Both fund and benchmark must have N-PORT holdings data.</p>
		</div>
	{:else}
		<!-- ── State 1: No benchmark selected ── -->
		<div class="as-empty">
			<p>Select a benchmark to compute Active Share</p>
			<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
			<div class="as-selector" onfocusin={fetchBenchmarks} onclick={fetchBenchmarks}>
				{#if loadingBenchmarks}
					<select class="as-select" disabled>
						<option>Loading instruments…</option>
					</select>
				{:else}
					<select
						class="as-select"
						onchange={(e) => selectBenchmark(e.currentTarget.value)}
						value=""
					>
						<option value="" disabled>Choose benchmark fund…</option>
						{#each benchmarks as bm (bm.id)}
							<option value={bm.id}>
								{bm.ticker ? `${bm.ticker} — ` : ""}{bm.name}
							</option>
						{/each}
					</select>
				{/if}
			</div>
		</div>
	{/if}
</section>

<style>
	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 4px;
	}

	.ea-panel-sub {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		margin: 0 0 16px;
	}

	.as-hero {
		display: flex;
		justify-content: center;
		margin-bottom: 20px;
	}

	.as-ring {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}

	.as-ring-value {
		font-size: 2.5rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}

	.as-ring-label {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted);
	}

	.as-ring-badge {
		font-size: 0.7rem;
		font-weight: 700;
		padding: 2px 10px;
		border-radius: 6px;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}

	.as-stats {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
	}

	.ea-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ea-stat-label {
		font-size: 0.7rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
	}

	.ea-stat-value {
		font-size: 1.1rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.as-date {
		font-size: 0.7rem;
		color: var(--ii-text-muted);
		text-align: right;
		margin: 12px 0 0;
	}

	.as-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		padding: 24px 0;
		color: var(--ii-text-muted);
		font-size: 0.85rem;
	}

	.as-selector {
		width: 100%;
		max-width: 360px;
	}

	.as-select {
		width: 100%;
		padding: 8px 12px;
		font-size: 0.8rem;
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
		cursor: pointer;
		appearance: auto;
	}

	.as-select:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
