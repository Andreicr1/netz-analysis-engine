<!--
  FactSheetPanel — col3 quick-read panel that fetches the fund fact sheet
  via the discovery API and renders core metrics + share classes.
  Any deeper analytics live in the standalone Analysis page (Phase 5+).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatAUM, formatPercent } from "@investintell/ui";
	import { fetchFundFactSheet } from "$lib/discovery/api";

	interface Props {
		fundId: string;
	}
	let { fundId }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface ShareClass {
		ticker: string | null;
		class_id: string;
		expense_ratio_pct: number | null;
	}
	interface FactSheet {
		fund?: {
			name?: string;
			ticker?: string | null;
			domicile?: string | null;
			currency?: string | null;
			aum_usd?: number | null;
			expense_ratio_pct?: number | null;
			strategy_label?: string | null;
		};
		classes?: ShareClass[];
	}

	let data = $state<FactSheet | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		const id = fundId;
		if (!id) return;
		const ctrl = new AbortController();
		data = null;
		error = null;
		fetchFundFactSheet(getToken, id, ctrl.signal)
			.then((d) => {
				data = d as FactSheet;
			})
			.catch((e: unknown) => {
				if ((e as Error).name !== "AbortError") {
					error = (e as Error).message;
				}
			});
		return () => ctrl.abort();
	});
</script>

<div class="fs-root">
	{#if error}
		<div class="fs-error">Failed to load: {error}</div>
	{:else if !data}
		<div class="fs-loading">Loading…</div>
	{:else}
		<header class="fs-header">
			<h2>{data.fund?.name ?? "—"}</h2>
			<div class="fs-meta">
				{data.fund?.ticker ?? "—"} · {data.fund?.domicile ?? "—"} · {data.fund
					?.currency ?? "—"}
			</div>
		</header>
		<section class="fs-metrics">
			<div class="metric">
				<span class="label">AUM</span>
				<strong>
					{data.fund?.aum_usd != null ? formatAUM(data.fund.aum_usd) : "—"}
				</strong>
			</div>
			<div class="metric">
				<span class="label">Expense Ratio</span>
				<strong>
					{data.fund?.expense_ratio_pct != null
						? formatPercent(data.fund.expense_ratio_pct / 100, 2)
						: "—"}
				</strong>
			</div>
			<div class="metric">
				<span class="label">Strategy</span>
				<strong>{data.fund?.strategy_label ?? "—"}</strong>
			</div>
		</section>
		{#if data.classes?.length}
			<section class="fs-classes">
				<h3>Share Classes</h3>
				<ul>
					{#each data.classes as cls (cls.class_id)}
						<li>
							{cls.ticker ?? cls.class_id} — ER {cls.expense_ratio_pct != null
								? formatPercent(cls.expense_ratio_pct / 100, 2)
								: "—"}
						</li>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}
</div>

<style>
	.fs-root {
		padding: 24px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.fs-header h2 {
		font-size: 20px;
		font-weight: 600;
		margin: 0 0 4px;
	}
	.fs-meta {
		color: var(--ii-text-muted);
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.fs-metrics {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 16px;
		margin: 24px 0;
	}
	.metric {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.metric .label {
		font-size: 11px;
		text-transform: uppercase;
		color: var(--ii-text-muted);
	}
	.metric strong {
		font-size: 18px;
		font-variant-numeric: tabular-nums;
	}
	.fs-classes h3 {
		font-size: 13px;
		font-weight: 600;
		margin: 0 0 8px;
	}
	.fs-classes ul {
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: 12px;
	}
	.fs-classes li {
		padding: 6px 0;
		border-bottom: 1px solid var(--ii-border-subtle);
		font-variant-numeric: tabular-nums;
	}
	.fs-loading,
	.fs-error {
		padding: 24px;
		text-align: center;
		color: var(--ii-text-muted);
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.fs-error {
		color: var(--ii-danger);
	}
</style>
