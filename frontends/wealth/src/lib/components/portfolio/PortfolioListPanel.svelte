<!--
  PortfolioListPanel — Permanent left column (280px) of the 3-column
  Builder grid (Phase 11 "Million Dollar" refactor).

  Always visible. Replaces the old full-screen PortfolioSelector by
  rendering a compact vertical list grouped by state (Active / Drafts /
  Archived). The selected portfolio gets a left accent border so the PM
  always knows which portfolio is being edited in Columns 2 and 3.

  "+ New Portfolio" is pinned at the top (never scrolls away).
-->
<script lang="ts">
	import { resolve } from "$app/paths";
	import { StatusBadge, formatDateTime } from "@investintell/ui";
	import Plus from "lucide-svelte/icons/plus";
	import ChevronDown from "lucide-svelte/icons/chevron-down";
	import ChevronRight from "lucide-svelte/icons/chevron-right";
	import SlidersHorizontal from "lucide-svelte/icons/sliders-horizontal";
	import type { ModelPortfolio } from "$wealth/types/model-portfolio";
	import { profileColor } from "$wealth/types/model-portfolio";
	import { portfolioDisplayName } from "$wealth/constants/blocks";
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";

	interface Props {
		portfolios: ModelPortfolio[];
		onSelect: (portfolio: ModelPortfolio) => void;
		onNewPortfolio: () => void;
	}

	let { portfolios, onSelect, onNewPortfolio }: Props = $props();

	const active = $derived(
		portfolios.filter((p) => p.state !== "draft" && p.state !== "archived"),
	);
	const drafts = $derived(portfolios.filter((p) => p.state === "draft"));
	const archived = $derived(portfolios.filter((p) => p.state === "archived"));

	let archivedOpen = $state(false);

	const selectedId = $derived(workspace.portfolio?.id ?? null);
</script>

<div class="plp-root">
	<!-- Pinned header — never scrolls -->
	<div class="plp-header">
		<span class="plp-title">Portfolios</span>
		<button type="button" class="plp-new-btn" onclick={onNewPortfolio}>
			<Plus size={14} />
			<span>New</span>
		</button>
	</div>

	<!-- PR-A26.3 Section H — entry point to per-profile Strategic IPS. -->
	<a
		href={resolve("/allocation")}
		class="plp-allocations-link"
		title="Review and approve Strategic allocations by profile"
	>
		<SlidersHorizontal size={14} />
		<span>Allocations</span>
	</a>

	<!-- Scrollable list -->
	<div class="plp-list" role="listbox" aria-label="Model portfolios">
		{#if portfolios.length === 0}
			<div class="plp-empty">
				<p>No model portfolios yet.</p>
				<p class="plp-empty-hint">Create your first to begin.</p>
			</div>
		{:else}
			{#if active.length > 0}
				<div class="plp-section">
					<span class="plp-section-title">Active</span>
					{#each active as mp (mp.id)}
						{@const isSelected = mp.id === selectedId}
						<button
							type="button"
							class="plp-row"
							class:plp-row--active={isSelected}
							role="option"
							aria-selected={isSelected}
							onclick={() => onSelect(mp)}
						>
							<div class="plp-row-top">
								<span class="plp-row-name">{mp.display_name}</span>
								<StatusBadge status={mp.state} />
							</div>
							<div class="plp-row-meta">
								<span
									class="plp-row-profile"
									style:color={profileColor(mp.profile)}
								>
									{portfolioDisplayName(mp.profile)}
								</span>
								{#if mp.fund_selection_schema}
									<span>{mp.fund_selection_schema.funds.length} funds</span>
								{/if}
							</div>
						</button>
					{/each}
				</div>
			{/if}

			{#if drafts.length > 0}
				<div class="plp-section">
					<span class="plp-section-title">Drafts</span>
					{#each drafts as mp (mp.id)}
						{@const isSelected = mp.id === selectedId}
						<button
							type="button"
							class="plp-row"
							class:plp-row--active={isSelected}
							role="option"
							aria-selected={isSelected}
							onclick={() => onSelect(mp)}
						>
							<div class="plp-row-top">
								<span class="plp-row-name">{mp.display_name}</span>
							</div>
							<div class="plp-row-meta">
								<span
									class="plp-row-profile"
									style:color={profileColor(mp.profile)}
								>
									{portfolioDisplayName(mp.profile)}
								</span>
								<span>{formatDateTime(mp.created_at)}</span>
							</div>
						</button>
					{/each}
				</div>
			{/if}

			{#if archived.length > 0}
				<div class="plp-section">
					<button
						type="button"
						class="plp-section-toggle"
						onclick={() => (archivedOpen = !archivedOpen)}
					>
						{#if archivedOpen}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<span class="plp-section-title">Archived</span>
						<span class="plp-section-count">{archived.length}</span>
					</button>
					{#if archivedOpen}
						{#each archived as mp (mp.id)}
							{@const isSelected = mp.id === selectedId}
							<button
								type="button"
								class="plp-row plp-row--archived"
								class:plp-row--active={isSelected}
								role="option"
								aria-selected={isSelected}
								onclick={() => onSelect(mp)}
							>
								<span class="plp-row-name">{mp.display_name}</span>
								<div class="plp-row-meta">
									<span>{formatDateTime(mp.created_at)}</span>
								</div>
							</button>
						{/each}
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.plp-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
		border-right: 1px solid rgba(64, 66, 73, 0.4);
	}

	/* ── Pinned header ──────────────────────────────────────── */
	.plp-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.4);
		flex-shrink: 0;
	}
	.plp-title {
		font-size: 13px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", sans-serif;
	}
	.plp-new-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 6px 14px;
		border: 1px solid rgba(255, 255, 255, 0.2);
		border-radius: 999px;
		background: transparent;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: all 120ms ease;
	}
	.plp-new-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		border-color: rgba(255, 255, 255, 0.35);
	}
	.plp-new-btn:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}

	/* PR-A26.3 Section H — Allocations entry link. */
	.plp-allocations-link {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0 12px 4px 12px;
		padding: 8px 10px;
		border-radius: 6px;
		font-size: 12px;
		font-weight: 500;
		color: rgba(255, 255, 255, 0.75);
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid rgba(255, 255, 255, 0.1);
		text-decoration: none;
		transition: background-color 120ms ease, border-color 120ms ease;
	}
	.plp-allocations-link:hover {
		background: rgba(255, 255, 255, 0.08);
		border-color: rgba(255, 255, 255, 0.25);
		color: rgba(255, 255, 255, 0.95);
	}

	/* ── Scrollable list ────────────────────────────────────── */
	.plp-list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 8px 0;
	}

	/* ── Section groups ─────────────────────────────────────── */
	.plp-section {
		padding: 0 8px;
		margin-bottom: 8px;
	}
	.plp-section-title {
		display: block;
		padding: 8px 8px 4px;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--ii-text-muted, #85a0bd);
		font-family: "Urbanist", sans-serif;
	}
	.plp-section-toggle {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 8px 8px 4px;
		background: transparent;
		border: none;
		cursor: pointer;
		color: var(--ii-text-muted, #85a0bd);
	}
	.plp-section-toggle .plp-section-title {
		padding: 0;
	}
	.plp-section-count {
		font-size: 10px;
		font-weight: 600;
		color: var(--ii-text-muted, #85a0bd);
		margin-left: 4px;
	}

	/* ── Portfolio rows ─────────────────────────────────────── */
	.plp-row {
		display: flex;
		flex-direction: column;
		gap: 4px;
		width: 100%;
		padding: 10px 12px;
		background: transparent;
		border: none;
		border-left: 3px solid transparent;
		border-radius: 0;
		cursor: pointer;
		text-align: left;
		font-family: "Urbanist", sans-serif;
		transition: background 100ms ease, border-color 100ms ease;
	}
	.plp-row:hover {
		background: rgba(255, 255, 255, 0.03);
	}
	.plp-row:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: -2px;
	}

	/* Active selection — left accent border */
	.plp-row--active {
		background: rgba(1, 119, 251, 0.08);
		border-left-color: #0177fb;
	}
	.plp-row--active:hover {
		background: rgba(1, 119, 251, 0.12);
	}

	.plp-row--archived {
		opacity: 0.6;
	}

	.plp-row-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		min-width: 0;
	}
	.plp-row-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--ii-text-primary, #ffffff);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.plp-row-meta {
		display: flex;
		gap: 8px;
		font-size: 10px;
		color: var(--ii-text-muted, #85a0bd);
	}
	.plp-row-profile {
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	/* ── Empty state ────────────────────────────────────────── */
	.plp-empty {
		padding: 32px 16px;
		text-align: center;
		color: var(--ii-text-muted, #85a0bd);
		font-size: 13px;
		font-family: "Urbanist", sans-serif;
	}
	.plp-empty-hint {
		font-size: 11px;
		margin-top: 4px;
		opacity: 0.7;
	}
</style>
