<!--
  Construction Advisor Panel — diagnoses CVaR coverage gaps, shows ranked candidates
  grouped by block in accordion tables, and offers single-add / batch-add actions.
  Shown inline when construct produces cvar_within_limit: false.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		formatPercent, formatNumber, ConsequenceDialog, Toast,
	} from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$lib/api/client";
	import { blockLabel, profileColor } from "$lib/types/model-portfolio";
	import type {
		ConstructionAdvice, CandidateFund, BlockGap,
	} from "$lib/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Props ──────────────────────────────────────────────────────────────
	interface Props {
		portfolioId: string;
		/** When provided, component skips its own fetch and renders this data. */
		externalAdvice?: ConstructionAdvice | null;
		/** True when parent is loading advice externally. */
		externalLoading?: boolean;
		/** Error message from external fetch. */
		externalError?: string | null;
		onReconstruct?: () => void;
	}

	let {
		portfolioId,
		externalAdvice = undefined,
		externalLoading = false,
		externalError = undefined,
		onReconstruct,
	}: Props = $props();

	// ── State machine ─────────────────────────────────────────────────────
	type AdvisorState =
		| { status: "idle" }
		| { status: "loading" }
		| { status: "error"; message: string }
		| { status: "loaded"; data: ConstructionAdvice };

	/** Internal state — only used when externalAdvice is not provided. */
	let internalState = $state<AdvisorState>({ status: "idle" });

	/** Resolved state: prefer external props, fall back to internal. */
	let advisorState = $derived.by((): AdvisorState => {
		if (externalAdvice !== undefined) {
			if (externalLoading) return { status: "loading" };
			if (externalError) return { status: "error", message: externalError };
			if (externalAdvice) return { status: "loaded", data: externalAdvice };
			return { status: "idle" };
		}
		return internalState;
	});
	let addedFunds = $state<Set<string>>(new Set());
	let expandedBlocks = $state<Set<string>>(new Set());
	let addingFund = $state<string | null>(null);
	let showBatchDialog = $state(false);
	let batchAdding = $state(false);
	let toastMessage = $state<string | null>(null);
	let toastType = $state<"success" | "error">("success");

	// ── Derived ───────────────────────────────────────────────────────────
	let advice = $derived(
		advisorState.status === "loaded" ? advisorState.data : null,
	);

	let candidatesByBlock = $derived.by(() => {
		if (!advice) return new Map<string, CandidateFund[]>();
		const groups = new Map<string, CandidateFund[]>();
		for (const c of advice.candidates) {
			const list = groups.get(c.block_id) ?? [];
			list.push(c);
			groups.set(c.block_id, list);
		}
		return groups;
	});

	let blockGapMap = $derived.by(() => {
		if (!advice) return new Map<string, BlockGap>();
		const map = new Map<string, BlockGap>();
		for (const gap of advice.coverage.block_gaps) {
			map.set(gap.block_id, gap);
		}
		return map;
	});

	/** Blocks with candidates, sorted by gap priority */
	let sortedBlocks = $derived.by(() => {
		if (!advice) return [] as string[];
		const blocks = [...candidatesByBlock.keys()];
		blocks.sort((a, b) => {
			const pa = blockGapMap.get(a)?.priority ?? 99;
			const pb = blockGapMap.get(b)?.priority ?? 99;
			return pa - pb;
		});
		return blocks;
	});

	let mvsNames = $derived.by(() => {
		if (!advice?.minimum_viable_set) return [] as string[];
		const idSet = new Set(advice.minimum_viable_set.funds);
		return advice.candidates
			.filter((c) => idSet.has(c.instrument_id))
			.map((c) => c.ticker ?? c.name);
	});

	let pendingMvsFunds = $derived.by(() => {
		if (!advice?.minimum_viable_set) return [] as CandidateFund[];
		const idSet = new Set(advice.minimum_viable_set.funds);
		return advice.candidates.filter(
			(c) => idSet.has(c.instrument_id) && !addedFunds.has(c.instrument_id),
		);
	});

	// ── Auto-expand first 3 blocks ────────────────────────────────────────
	$effect(() => {
		if (sortedBlocks.length > 0 && expandedBlocks.size === 0) {
			expandedBlocks = new Set(sortedBlocks.slice(0, 3));
		}
	});

	// ── Fetch advice (internal — skipped when externalAdvice is provided) ──
	export async function fetchAdvice() {
		if (externalAdvice !== undefined) return; // managed externally
		internalState = { status: "loading" };
		addedFunds = new Set();
		try {
			const api = createClientApiClient(getToken);
			const data = await api.post<ConstructionAdvice>(
				`/model-portfolios/${portfolioId}/construction-advice`,
				{},
			);
			internalState = { status: "loaded", data };
		} catch (e) {
			internalState = {
				status: "error",
				message: e instanceof Error ? e.message : "Failed to load construction advice",
			};
		}
	}

	// ── Single fund add ───────────────────────────────────────────────────
	async function addFund(candidate: CandidateFund) {
		addingFund = candidate.instrument_id;
		try {
			const api = createClientApiClient(getToken);

			let instrumentId = candidate.instrument_id;

			// Import if not yet in org universe
			if (!candidate.in_universe) {
				const identifier = candidate.ticker ?? candidate.external_id;
				const result = await api.post<{ instrument_id: string }>(
					`/screener/import/${encodeURIComponent(identifier)}`,
					{},
				);
				instrumentId = result.instrument_id;
			}

			// Assign to block
			await api.patch(`/instruments/${instrumentId}/org`, {
				block_id: candidate.block_id,
			});

			addedFunds = new Set([...addedFunds, candidate.instrument_id]);
			toastType = "success";
			toastMessage = `${candidate.ticker ?? candidate.name} added to ${blockLabel(candidate.block_id)}`;
		} catch (e) {
			toastType = "error";
			toastMessage = e instanceof Error ? e.message : "Failed to add fund";
		} finally {
			addingFund = null;
		}
	}

	// ── Batch add (minimum viable set) ────────────────────────────────────
	async function batchAddAndReconstruct() {
		batchAdding = true;
		try {
			const api = createClientApiClient(getToken);

			for (const candidate of pendingMvsFunds) {
				let instrumentId = candidate.instrument_id;
				if (!candidate.in_universe) {
					const identifier = candidate.ticker ?? candidate.external_id;
					const result = await api.post<{ instrument_id: string }>(
						`/screener/import/${encodeURIComponent(identifier)}`,
						{},
					);
					instrumentId = result.instrument_id;
				}
				await api.patch(`/instruments/${instrumentId}/org`, {
					block_id: candidate.block_id,
				});
				addedFunds = new Set([...addedFunds, candidate.instrument_id]);
			}

			// Re-construct
			await api.post(`/model-portfolios/${portfolioId}/construct`, {});
			await invalidateAll();
			onReconstruct?.();

			toastType = "success";
			toastMessage = `${pendingMvsFunds.length} funds added — portfolio re-constructed`;
		} catch (e) {
			toastType = "error";
			toastMessage = e instanceof Error ? e.message : "Batch add failed";
		} finally {
			batchAdding = false;
			showBatchDialog = false;
		}
	}

	// ── Toggle block accordion ────────────────────────────────────────────
	function toggleBlock(blockId: string) {
		const next = new Set(expandedBlocks);
		if (next.has(blockId)) {
			next.delete(blockId);
		} else {
			next.add(blockId);
		}
		expandedBlocks = next;
	}
</script>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- ADVISOR PANEL                                                          -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

{#if advisorState.status === "loading"}
	<section class="ca-panel">
		<div class="ca-loading">
			<span class="ca-spinner"></span>
			Analyzing portfolio coverage and screening candidates…
		</div>
	</section>
{:else if advisorState.status === "error"}
	<section class="ca-panel">
		<div class="ca-error">{advisorState.message}</div>
	</section>
{:else if advice}
	<section class="ca-panel">
		<!-- Header -->
		<div class="ca-header">
			<div class="ca-header-left">
				<h3 class="ca-title">Construction Advisor</h3>
				<span class="ca-subtitle">
					{advice.profile} — CVaR {formatPercent(advice.current_cvar_95)} (limit {formatPercent(advice.cvar_limit)})
				</span>
			</div>
			{#if advice.projected_cvar_is_heuristic}
				<span class="ca-heuristic-badge">Projected — heuristic</span>
			{/if}
		</div>

		<!-- Coverage bar -->
		<div class="ca-coverage">
			<div class="ca-coverage-bar-track">
				<div
					class="ca-coverage-bar-fill"
					style:width="{Math.round(advice.coverage.covered_pct * 100)}%"
				></div>
			</div>
			<span class="ca-coverage-label">
				{Math.round(advice.coverage.covered_pct * 100)}% blocks covered ({advice.coverage.covered_blocks}/{advice.coverage.total_blocks})
			</span>
		</div>

		<!-- Block accordions -->
		<div class="ca-blocks">
			{#each sortedBlocks as blockId (blockId)}
				{@const gap = blockGapMap.get(blockId)}
				{@const candidates = candidatesByBlock.get(blockId) ?? []}
				{@const isExpanded = expandedBlocks.has(blockId)}

				<div class="ca-block" class:ca-block--expanded={isExpanded}>
					<button class="ca-block-header" onclick={() => toggleBlock(blockId)}>
						<span class="ca-block-chevron">{isExpanded ? "▾" : "▸"}</span>
						<span class="ca-block-name">{gap?.display_name ?? blockLabel(blockId)}</span>
						<span class="ca-block-asset-class">{gap?.asset_class ?? ""}</span>
						<span class="ca-block-gap">
							target: {formatPercent(gap?.target_weight ?? 0)} · gap: {formatPercent(gap?.gap_weight ?? 0)}
						</span>
						<span class="ca-block-count">{candidates.length} candidate{candidates.length !== 1 ? "s" : ""}</span>
					</button>

					{#if isExpanded}
						<div class="ca-block-body">
							{#if candidates.length === 0}
								<div class="ca-empty">No candidates found for this block. <a href="/screener?asset_class={gap?.asset_class ?? ''}">Browse Catalog</a></div>
							{:else}
								<div class="ca-table-wrap">
									<table class="ca-table">
										<thead>
											<tr>
												<th class="ca-th-name">Fund</th>
												<th class="ca-th-num">Vol 1Y</th>
												<th class="ca-th-num">Corr</th>
												<th class="ca-th-num">Overlap</th>
												<th class="ca-th-num">Proj CVaR</th>
												<th class="ca-th-num">Improv.</th>
												<th class="ca-th-action"></th>
											</tr>
										</thead>
										<tbody>
											{#each candidates as c (c.instrument_id)}
												{@const isAdded = addedFunds.has(c.instrument_id)}
												<tr class="ca-row" class:ca-row--added={isAdded}>
													<td class="ca-td-name">
														<span class="ca-fund-name">{c.name}</span>
														{#if c.ticker}
															<span class="ca-fund-ticker">{c.ticker}</span>
														{/if}
														{#if !c.in_universe && !isAdded}
															<span class="ca-badge-ext">catalog</span>
														{/if}
														{#if !c.has_holdings_data}
															<span class="ca-badge-warn" title="Holdings data unavailable — overlap not computed">⚠</span>
														{/if}
													</td>
													<td class="ca-td-num">{c.volatility_1y != null ? formatPercent(c.volatility_1y) : "—"}</td>
													<td class="ca-td-num" class:ca-corr-neg={c.correlation_with_portfolio < 0}>
														{c.correlation_with_portfolio != null ? c.correlation_with_portfolio.toFixed(2) : "—"}
													</td>
													<td class="ca-td-num">{formatPercent(c.overlap_pct)}</td>
													<td class="ca-td-num">{c.projected_cvar_95 != null ? formatPercent(c.projected_cvar_95) : "—"}</td>
													<td class="ca-td-num ca-improvement">
														{#if c.cvar_improvement > 0}
															+{formatPercent(c.cvar_improvement)}
														{:else}
															{formatPercent(c.cvar_improvement)}
														{/if}
													</td>
													<td class="ca-td-action">
														{#if isAdded}
															<span class="ca-added-check">✓</span>
														{:else}
															<Button
																size="sm"
																variant="outline"
																onclick={() => addFund(c)}
																disabled={addingFund === c.instrument_id}
															>
																{addingFund === c.instrument_id ? "…" : "Add"}
															</Button>
														{/if}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>

		<!-- Alternative profiles -->
		{#if advice.alternative_profiles.length > 0}
			{@const passing = advice.alternative_profiles.filter((p) => p.current_cvar_would_pass)}
			{#if passing.length > 0}
				<div class="ca-alt-profiles">
					<span class="ca-alt-label">Alternative:</span>
					{#each passing as alt (alt.profile)}
						<span class="ca-alt-option">
							Switch to <strong style:color={profileColor(alt.profile)}>{alt.profile}</strong>
							(CVaR limit {formatPercent(alt.cvar_limit)}) — current portfolio would pass.
						</span>
					{/each}
				</div>
			{/if}
		{/if}

		<!-- Sticky footer — minimum viable set -->
		{#if advice.minimum_viable_set && pendingMvsFunds.length > 0}
			<div class="ca-sticky-footer">
				<div class="ca-mvs-info">
					<span class="ca-mvs-label">Quick Path:</span>
					Add {mvsNames.join(" + ")} → projected CVaR: {formatPercent(advice.minimum_viable_set.projected_cvar_95)}
					{#if advice.minimum_viable_set.projected_within_limit}
						<span class="ca-mvs-pass">✓ within limit</span>
					{/if}
				</div>
				<Button size="sm" onclick={() => (showBatchDialog = true)} disabled={batchAdding}>
					{batchAdding ? "Adding…" : "Add All & Re-construct"}
				</Button>
			</div>
		{:else if addedFunds.size > 0}
			<div class="ca-sticky-footer">
				<div class="ca-mvs-info">
					<span class="ca-mvs-label">{addedFunds.size} fund{addedFunds.size !== 1 ? "s" : ""} added.</span>
					Re-construct to apply changes.
				</div>
				<Button size="sm" onclick={onReconstruct}>Re-construct</Button>
			</div>
		{/if}

		{#if advice.minimum_viable_set == null && addedFunds.size === 0}
			<div class="ca-no-solution">
				Available catalog cannot bring portfolio within limits. Consider expanding the catalog, adjusting the risk profile, or removing concentrated risk contributors.
			</div>
		{/if}
	</section>
{/if}

<!-- Batch confirmation dialog -->
<ConsequenceDialog
	bind:open={showBatchDialog}
	title="Add Funds & Re-construct"
	impactSummary="Import {pendingMvsFunds.length} fund{pendingMvsFunds.length !== 1 ? 's' : ''} into the portfolio universe, assign to recommended blocks, and re-run portfolio construction."
	confirmLabel={batchAdding ? "Adding…" : "Add All & Re-construct"}
	metadata={[
		{ label: "Funds", value: mvsNames.join(", "), emphasis: true },
		{ label: "Projected CVaR", value: advice?.minimum_viable_set ? formatPercent(advice.minimum_viable_set.projected_cvar_95) : "—" },
		{ label: "Within limit", value: advice?.minimum_viable_set?.projected_within_limit ? "Yes" : "No" },
	]}
	onConfirm={batchAddAndReconstruct}
	onCancel={() => (showBatchDialog = false)}
/>

<!-- Toast -->
{#if toastMessage}
	<Toast
		message={toastMessage}
		type={toastType}
		duration={4000}
		onDismiss={() => (toastMessage = null)}
	/>
{/if}

<style>
	/* ── Panel container ─────────────────────────────────────────────────── */
	.ca-panel {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	/* ── Header ──────────────────────────────────────────────────────────── */
	.ca-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.ca-header-left {
		display: flex;
		align-items: baseline;
		gap: var(--ii-space-inline-md, 16px);
	}

	.ca-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		margin: 0;
	}

	.ca-subtitle {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.ca-heuristic-badge {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		padding: 2px 8px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-pill, 999px);
	}

	/* ── Coverage bar ────────────────────────────────────────────────────── */
	.ca-coverage {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-md, 16px);
	}

	.ca-coverage-bar-track {
		flex: 1;
		height: 8px;
		background: var(--ii-surface-alt);
		border-radius: 4px;
		overflow: hidden;
	}

	.ca-coverage-bar-fill {
		height: 100%;
		background: var(--ii-warning);
		border-radius: 4px;
		transition: width 300ms ease;
	}

	.ca-coverage-label {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		white-space: nowrap;
	}

	/* ── Blocks accordion ────────────────────────────────────────────────── */
	.ca-blocks {
		display: flex;
		flex-direction: column;
	}

	.ca-block {
		border-top: 1px solid var(--ii-border-subtle);
	}

	.ca-block-header {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
		width: 100%;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		background: none;
		border: none;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		text-align: left;
		color: var(--ii-text-primary);
	}

	.ca-block-header:hover {
		background: var(--ii-surface-highlight, color-mix(in srgb, var(--ii-brand-primary) 4%, transparent));
	}

	.ca-block-chevron {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		width: 14px;
		flex-shrink: 0;
	}

	.ca-block-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
	}

	.ca-block-asset-class {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.ca-block-gap {
		margin-left: auto;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.ca-block-count {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		flex-shrink: 0;
	}

	.ca-block-body {
		padding: 0 var(--ii-space-inline-md, 16px) var(--ii-space-stack-sm, 12px);
	}

	.ca-empty {
		padding: var(--ii-space-stack-sm, 12px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.ca-empty a {
		color: var(--ii-brand-primary);
		text-decoration: underline;
	}

	/* ── Candidate table ─────────────────────────────────────────────────── */
	.ca-table-wrap {
		overflow-x: auto;
	}

	.ca-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.ca-table thead th {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.ca-table td {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid var(--ii-border-subtle);
		vertical-align: middle;
	}

	.ca-th-name { min-width: 200px; }
	.ca-th-num { width: 80px; text-align: right; }
	.ca-th-action { width: 70px; text-align: center; }

	.ca-td-name {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}

	.ca-fund-name {
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.ca-fund-ticker {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-family: var(--ii-font-mono, monospace);
	}

	.ca-badge-ext {
		font-size: 0.625rem;
		padding: 1px 5px;
		border-radius: var(--ii-radius-pill, 999px);
		background: color-mix(in srgb, var(--ii-info) 12%, transparent);
		color: var(--ii-info);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.ca-badge-warn {
		cursor: help;
		font-size: 0.75rem;
	}

	.ca-td-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-secondary);
	}

	.ca-corr-neg {
		color: var(--ii-success);
	}

	.ca-improvement {
		color: var(--ii-success);
		font-weight: 600;
	}

	.ca-td-action {
		text-align: center;
	}

	.ca-row--added {
		opacity: 0.5;
		text-decoration: line-through;
	}

	.ca-row:hover:not(.ca-row--added) {
		background: var(--ii-surface-highlight, color-mix(in srgb, var(--ii-brand-primary) 4%, transparent));
	}

	.ca-added-check {
		color: var(--ii-success);
		font-weight: 700;
		font-size: 1rem;
	}

	/* ── Alternative profiles ────────────────────────────────────────────── */
	.ca-alt-profiles {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
		background: color-mix(in srgb, var(--ii-info) 4%, transparent);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		display: flex;
		flex-wrap: wrap;
		gap: var(--ii-space-inline-sm, 8px);
	}

	.ca-alt-label {
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	/* ── Sticky footer ───────────────────────────────────────────────────── */
	.ca-sticky-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--ii-space-inline-md, 16px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-top: 2px solid var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 4%, transparent);
	}

	.ca-mvs-info {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
	}

	.ca-mvs-label {
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.ca-mvs-pass {
		color: var(--ii-success);
		font-weight: 600;
	}

	/* ── No solution ─────────────────────────────────────────────────────── */
	.ca-no-solution {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
		background: color-mix(in srgb, var(--ii-warning) 6%, transparent);
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Loading & error ─────────────────────────────────────────────────── */
	.ca-loading {
		padding: var(--ii-space-stack-lg, 32px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.ca-spinner {
		display: inline-block;
		width: 16px;
		height: 16px;
		border: 2px solid var(--ii-border);
		border-top-color: var(--ii-brand-primary);
		border-radius: 50%;
		animation: ca-spin 0.7s linear infinite;
	}

	@keyframes ca-spin {
		to { transform: rotate(360deg); }
	}

	.ca-error {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
