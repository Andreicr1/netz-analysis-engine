<!--
  DD Reports — fund selector to navigate into fund-specific DD reports.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { PageHeader, Card, EmptyState, StatusBadge } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	interface FundBrief {
		id: string;
		name: string;
		ticker: string | null;
		isin: string | null;
		asset_class: string | null;
		geography: string | null;
	}

	let funds = $derived((data.funds ?? []) as FundBrief[]);
	let search = $state("");

	let filtered = $derived.by(() => {
		if (!search) return funds;
		const q = search.toLowerCase();
		return funds.filter((f) =>
			f.name.toLowerCase().includes(q) ||
			f.ticker?.toLowerCase().includes(q) ||
			f.isin?.toLowerCase().includes(q)
		);
	});
</script>

<PageHeader title="Due Diligence Reports" />

<div class="dd-list">
	<div class="dd-search">
		<input
			type="text"
			class="dd-search-input"
			placeholder="Search funds by name, ticker, or ISIN…"
			bind:value={search}
		/>
	</div>

	{#if filtered.length === 0}
		<EmptyState title={funds.length === 0 ? "No funds in universe yet" : "No funds match your search"} />
	{:else}
		<div class="dd-fund-grid">
			{#each filtered as fund (fund.id)}
				<button
					class="dd-fund-card"
					onclick={() => goto(`/dd-reports/${fund.id}`)}
				>
					<span class="dd-fund-name">{fund.name}</span>
					<span class="dd-fund-meta">
						{#if fund.ticker}{fund.ticker}{/if}
						{#if fund.ticker && fund.isin} · {/if}
						{#if fund.isin}{fund.isin}{/if}
					</span>
					<span class="dd-fund-tags">
						{#if fund.asset_class}
							<span class="dd-fund-tag">{fund.asset_class}</span>
						{/if}
						{#if fund.geography}
							<span class="dd-fund-tag">{fund.geography}</span>
						{/if}
					</span>
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.dd-list {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.dd-search {
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	.dd-search-input {
		width: 100%;
		max-width: 400px;
		height: var(--netz-space-control-height-md, 40px);
		padding: 0 var(--netz-space-inline-sm, 12px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-body, 0.9375rem);
		font-family: var(--netz-font-sans);
	}

	.dd-search-input:focus {
		outline: none;
		border-color: var(--netz-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--netz-brand-secondary) 20%, transparent);
	}

	.dd-search-input::placeholder {
		color: var(--netz-text-muted);
	}

	.dd-fund-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--netz-space-stack-sm, 12px);
	}

	.dd-fund-card {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
		padding: var(--netz-space-stack-sm, 14px) var(--netz-space-inline-md, 16px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		text-align: left;
		cursor: pointer;
		transition: border-color 120ms ease, box-shadow 120ms ease;
		font-family: var(--netz-font-sans);
	}

	.dd-fund-card:hover {
		border-color: var(--netz-border-accent);
		box-shadow: var(--netz-shadow-1);
	}

	.dd-fund-name {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	.dd-fund-meta {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
	}

	.dd-fund-tags {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
		margin-top: var(--netz-space-stack-2xs, 4px);
	}

	.dd-fund-tag {
		font-size: var(--netz-text-label, 0.75rem);
		padding: 1px 8px;
		border-radius: var(--netz-radius-pill, 999px);
		background: var(--netz-surface-alt);
		color: var(--netz-text-secondary);
	}
</style>
