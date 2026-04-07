<!--
  FundSelectionEditor — inline panel for editing fund selection on a draft model portfolio.
  Block sidebar (left) + checkbox fund list (right). Soft removal only.
  Apply triggers re-construction via ConsequenceDialog.
-->
<script lang="ts">
	import { ConsequenceDialog, Button, formatPercent } from "@investintell/ui";
	import type { InstrumentWeight } from "$lib/types/model-portfolio";
	import type { UniverseAsset } from "$lib/types/universe";
	import { blockLabel } from "$lib/constants/blocks";

	interface Props {
		portfolioId: string;
		currentFunds: InstrumentWeight[];
		instruments: UniverseAsset[];
		onApply: () => void | Promise<void>;
		onCancel: () => void;
	}

	let { portfolioId, currentFunds, instruments, onApply, onCancel }: Props = $props();

	// Only approved instruments
	let approvedFunds = $derived(instruments.filter(f => f.approval_decision === "approved"));

	// Build set of currently selected fund IDs from portfolio
	let initialSelected = $derived(new Set(currentFunds.map(f => f.instrument_id)));

	// Mutable selection state: Map<block_id, Set<instrument_id>>
	let selectedByBlock = $state<Map<string, Set<string>>>(new Map());
	let initialized = $state(false);

	// Initialize from current portfolio funds (once)
	$effect(() => {
		if (!initialized && currentFunds.length > 0) {
			const map = new Map<string, Set<string>>();
			for (const f of currentFunds) {
				const set = map.get(f.block_id) ?? new Set();
				set.add(f.instrument_id);
				map.set(f.block_id, set);
			}
			// Also include empty blocks from approved instruments
			for (const f of approvedFunds) {
				if (f.block_id && !map.has(f.block_id)) {
					map.set(f.block_id, new Set());
				}
			}
			selectedByBlock = map;
			initialized = true;
		}
	});

	// All block IDs (from current funds + approved universe)
	let blockIds = $derived.by(() => {
		const blocks = new Set<string>();
		for (const f of currentFunds) blocks.add(f.block_id);
		for (const f of approvedFunds) {
			if (f.block_id) blocks.add(f.block_id);
		}
		return [...blocks].sort();
	});

	let selectedBlockId = $state<string | null>(null);

	let fundsForBlock = $derived.by(() => {
		if (!selectedBlockId) return [];
		return approvedFunds.filter(f => f.block_id === selectedBlockId);
	});

	let selectedIdsForBlock = $derived.by((): Set<string> => {
		if (!selectedBlockId) return new Set();
		return selectedByBlock.get(selectedBlockId) ?? new Set();
	});

	// Current weight lookup (instrument_id -> weight from optimizer)
	let weightMap = $derived.by(() => {
		const map = new Map<string, number>();
		for (const f of currentFunds) map.set(f.instrument_id, f.weight);
		return map;
	});


	function toggleFund(fundId: string) {
		if (!selectedBlockId) return;
		const next = new Map(selectedByBlock);
		const blockSet = new Set(next.get(selectedBlockId) ?? []);
		if (blockSet.has(fundId)) {
			blockSet.delete(fundId);
		} else {
			blockSet.add(fundId);
		}
		next.set(selectedBlockId, blockSet);
		selectedByBlock = next;
	}

	// ── Change summary ────────────────────────────────────────────────────
	let allSelectedIds = $derived.by(() => {
		const ids = new Set<string>();
		for (const set of selectedByBlock.values()) {
			for (const id of set) ids.add(id);
		}
		return ids;
	});

	let addedFunds = $derived.by(() => {
		const added: string[] = [];
		for (const id of allSelectedIds) {
			if (!initialSelected.has(id)) added.push(id);
		}
		return added;
	});

	let removedFunds = $derived.by(() => {
		const removed: string[] = [];
		for (const id of initialSelected) {
			if (!allSelectedIds.has(id)) removed.push(id);
		}
		return removed;
	});

	let hasChanges = $derived(addedFunds.length > 0 || removedFunds.length > 0);

	// ── Manual weight editing ─────────────────────────────────────────────
	let weightOverrides = $state<Map<string, number>>(new Map());
	let weightEditMode = $state(false);

	function effectiveWeight(fundId: string): number {
		return weightOverrides.get(fundId) ?? weightMap.get(fundId) ?? 0;
	}

	function setWeight(fundId: string, value: number) {
		const clamped = Math.max(0, Math.min(1, value));
		const next = new Map(weightOverrides);
		next.set(fundId, Math.round(clamped * 10000) / 10000);
		weightOverrides = next;
	}

	let totalEffectiveWeight = $derived.by(() => {
		let sum = 0;
		for (const id of allSelectedIds) {
			sum += effectiveWeight(id);
		}
		return sum;
	});

	let weightBudgetWarning = $derived(allSelectedIds.size > 0 && (totalEffectiveWeight < 0.98 || totalEffectiveWeight > 1.02));

	function normalizeWeights() {
		const total = totalEffectiveWeight;
		if (total <= 0 || allSelectedIds.size === 0) return;
		const next = new Map<string, number>();
		for (const id of allSelectedIds) {
			const w = effectiveWeight(id);
			next.set(id, Math.round((w / total) * 10000) / 10000);
		}
		const adjusted = [...next.entries()];
		const rSum = adjusted.reduce((s, [, v]) => s + v, 0);
		if (adjusted.length > 0 && Math.abs(rSum - 1.0) > 0.00001) {
			const top = adjusted.sort((a, b) => b[1] - a[1])[0];
			if (top) {
				top[1] = Math.round((top[1] + 1.0 - rSum) * 10000) / 10000;
			}
		}
		weightOverrides = new Map(adjusted);
	}

	// Fund name lookup
	let nameMap = $derived.by(() => {
		const map = new Map<string, string>();
		for (const f of instruments) map.set(f.instrument_id, f.fund_name);
		for (const f of currentFunds) map.set(f.instrument_id, f.fund_name);
		return map;
	});

	function fundName(id: string): string {
		return nameMap.get(id) ?? id.slice(0, 8);
	}

	// ── ConsequenceDialog ─────────────────────────────────────────────────
	let showConfirm = $state(false);
	let applying = $state(false);

	async function handleApply() {
		applying = true;
		try {
			await onApply();
		} finally {
			applying = false;
			showConfirm = false;
		}
	}
</script>

<div class="fse-panel">
	<div class="fse-layout">
		<!-- Block sidebar -->
		<div class="fse-blocks">
			{#each blockIds as bid (bid)}
				{@const count = selectedByBlock.get(bid)?.size ?? 0}
				{@const available = approvedFunds.filter(f => f.block_id === bid).length}
				<button
					class="fse-block-item"
					class:fse-block-item--active={selectedBlockId === bid}
					class:fse-block-item--changed={(() => {
						const origCount = currentFunds.filter(f => f.block_id === bid).length;
						return count !== origCount;
					})()}
					onclick={() => (selectedBlockId = bid)}
					type="button"
				>
					<span class="fse-block-name">{blockLabel(bid)}</span>
					<span class="fse-block-count" class:fse-block-count--zero={count === 0}>
						{count}/{available}
					</span>
				</button>
			{/each}
		</div>

		<!-- Fund list -->
		<div class="fse-funds">
			{#if !selectedBlockId}
				<div class="fse-funds-empty">Select a block to view and toggle funds.</div>
			{:else if fundsForBlock.length === 0}
				<div class="fse-funds-empty">
					No approved funds for {blockLabel(selectedBlockId)}.
					<a href="/screener" class="fse-link">Import via Screener</a>
				</div>
			{:else}
				<div class="fse-funds-header">
					<span class="fse-funds-title">{blockLabel(selectedBlockId)}</span>
					<div class="fse-funds-header-right">
						<span class="fse-funds-count">{selectedIdsForBlock.size} / {fundsForBlock.length} selected</span>
						<button
							class="fse-weight-toggle"
							class:fse-weight-toggle--active={weightEditMode}
							type="button"
							onclick={() => (weightEditMode = !weightEditMode)}
						>
							{weightEditMode ? "Hide Weights" : "Edit Weights"}
						</button>
					</div>
				</div>
				<div class="fse-fund-items">
					{#each fundsForBlock as fund (fund.instrument_id)}
						{@const isSelected = selectedIdsForBlock.has(fund.instrument_id)}
						{@const wasInPortfolio = initialSelected.has(fund.instrument_id)}
						{@const currentWeight = weightMap.get(fund.instrument_id)}
						<button
							class="fse-fund-item"
							class:fse-fund-item--selected={isSelected}
							class:fse-fund-item--dimmed={!isSelected && wasInPortfolio}
							onclick={() => toggleFund(fund.instrument_id)}
							type="button"
						>
							<span class="fse-fund-check">{isSelected ? "\u2713" : "+"}</span>
							<div class="fse-fund-info">
								<span class="fse-fund-name">{fund.fund_name}</span>
								{#if fund.ticker}
									<span class="fse-fund-ticker">{fund.ticker}</span>
								{/if}
							</div>
							{#if weightEditMode && isSelected}
								<input
									type="number"
									class="fse-weight-input"
									min="0"
									max="100"
									step="0.1"
									value={Math.round(effectiveWeight(fund.instrument_id) * 10000) / 100}
									oninput={(e) => {
										const v = parseFloat((e.target as HTMLInputElement).value);
										if (!Number.isNaN(v)) setWeight(fund.instrument_id, v / 100);
									}}
									onclick={(e) => e.stopPropagation()}
								/>
								<span class="fse-weight-pct">%</span>
							{:else if currentWeight != null}
								<span class="fse-fund-weight">{formatPercent(currentWeight)}</span>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<!-- Weight budget bar (visible in weight edit mode) -->
	{#if weightEditMode && allSelectedIds.size > 0}
		<div class="fse-weight-budget">
			<span class="fse-weight-budget-label {weightBudgetWarning ? 'fse-weight-budget-label--warn' : ''}">
				Total: {formatPercent(totalEffectiveWeight * 100)}
			</span>
			<button
				class="fse-normalize-btn"
				type="button"
				onclick={normalizeWeights}
				disabled={totalEffectiveWeight <= 0}
			>
				Normalize to 100%
			</button>
		</div>
	{/if}

	<!-- Footer with change summary + actions -->
	{#if hasChanges}
		<div class="fse-footer">
			<span class="fse-summary">
				{#if addedFunds.length > 0}{addedFunds.length} added{/if}
				{#if addedFunds.length > 0 && removedFunds.length > 0}, {/if}
				{#if removedFunds.length > 0}{removedFunds.length} excluded{/if}
			</span>
			<div class="fse-actions">
				<Button size="sm" variant="ghost" onclick={onCancel}>Cancel</Button>
				<Button size="sm" onclick={() => (showConfirm = true)} disabled={applying}>
					{applying ? "Applying\u2026" : "Apply & Re-construct"}
				</Button>
			</div>
		</div>
	{:else}
		<div class="fse-footer fse-footer--muted">
			<span class="fse-summary">No changes</span>
			<Button size="sm" variant="ghost" onclick={onCancel}>Close</Button>
		</div>
	{/if}
</div>

<ConsequenceDialog
	bind:open={showConfirm}
	title="Re-construct Portfolio"
	impactSummary="Fund selection will be updated and the 4-phase CLARABEL cascade optimizer will re-run. This may take 5-10 seconds."
	scopeText="{addedFunds.length} fund{addedFunds.length !== 1 ? 's' : ''} added, {removedFunds.length} fund{removedFunds.length !== 1 ? 's' : ''} excluded"
	confirmLabel={applying ? "Applying\u2026" : "Apply & Re-construct"}
	metadata={[
		...addedFunds.slice(0, 5).map(id => ({ label: "Add", value: fundName(id) })),
		...removedFunds.slice(0, 5).map(id => ({ label: "Exclude", value: fundName(id) })),
		...(addedFunds.length + removedFunds.length > 10 ? [{ label: "More", value: `${addedFunds.length + removedFunds.length - 10} additional changes` }] : []),
	]}
	onConfirm={handleApply}
	onCancel={() => (showConfirm = false)}
/>

<style>
	.fse-panel {
		border-top: 1px solid var(--ii-border-subtle);
	}

	.fse-layout {
		display: grid;
		grid-template-columns: 220px 1fr;
		min-height: 300px;
		max-height: 480px;
	}

	/* ── Block sidebar ────────────────────────────────────────────────────── */
	.fse-blocks {
		border-right: 1px solid var(--ii-border-subtle);
		overflow-y: auto;
		padding: var(--ii-space-stack-xs, 8px) 0;
	}

	.fse-block-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 8px 14px;
		border: none;
		background: transparent;
		cursor: pointer;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		text-align: left;
		transition: background 120ms ease;
	}

	.fse-block-item:hover {
		background: var(--ii-surface-alt);
	}

	.fse-block-item--active {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
		font-weight: 600;
		border-left: 3px solid var(--ii-brand-primary);
	}

	.fse-block-item--changed .fse-block-count {
		color: var(--ii-warning);
		font-weight: 700;
	}

	.fse-block-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.fse-block-count {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		margin-left: 8px;
		flex-shrink: 0;
	}

	.fse-block-count--zero {
		color: var(--ii-text-muted);
		opacity: 0.5;
	}

	/* ── Fund list ─────────────────────────────────────────────────────────── */
	.fse-funds {
		overflow-y: auto;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
	}

	.fse-funds-empty {
		padding: 48px 24px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.fse-link {
		color: var(--ii-brand-primary);
		font-weight: 600;
		text-decoration: none;
	}
	.fse-link:hover { text-decoration: underline; }

	.fse-funds-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--ii-border-subtle);
		margin-bottom: 8px;
	}

	.fse-funds-title {
		font-weight: 600;
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-primary);
	}

	.fse-funds-count {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.fse-fund-items {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.fse-fund-item {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 8px 10px;
		border: 1px solid transparent;
		border-radius: var(--ii-radius-sm, 6px);
		background: transparent;
		cursor: pointer;
		text-align: left;
		transition: all 120ms ease;
	}

	.fse-fund-item:hover {
		background: var(--ii-surface-alt);
	}

	.fse-fund-item--selected {
		border-color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 5%, transparent);
	}

	.fse-fund-item--dimmed {
		opacity: 0.45;
	}

	.fse-fund-check {
		width: 22px;
		height: 22px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 4px;
		font-size: 13px;
		font-weight: 700;
		flex-shrink: 0;
		background: var(--ii-surface-alt);
		color: var(--ii-text-muted);
	}

	.fse-fund-item--selected .fse-fund-check {
		background: var(--ii-brand-primary);
		color: white;
	}

	.fse-fund-info {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 1px;
		overflow: hidden;
	}

	.fse-fund-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.fse-fund-ticker {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-family: var(--ii-font-mono, monospace);
	}

	.fse-fund-weight {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	/* ── Weight editing controls ───────────────────────────────────────────── */
	.fse-funds-header-right {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.fse-weight-toggle {
		padding: 2px 8px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 6px);
		background: transparent;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
		cursor: pointer;
		transition: all 120ms ease;
	}
	.fse-weight-toggle:hover {
		border-color: var(--ii-brand-primary);
		color: var(--ii-text-primary);
	}
	.fse-weight-toggle--active {
		border-color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
	}

	.fse-weight-input {
		width: 60px;
		padding: 2px 4px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 4px;
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-label, 0.75rem);
		font-variant-numeric: tabular-nums;
		text-align: right;
		flex-shrink: 0;
	}
	.fse-weight-input:focus {
		outline: none;
		border-color: var(--ii-brand-primary);
	}

	.fse-weight-pct {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		flex-shrink: 0;
		margin-left: -2px;
	}

	.fse-weight-budget {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 16px;
		border-top: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.fse-weight-budget-label {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-success, #11ec79);
	}
	.fse-weight-budget-label--warn {
		color: var(--ii-warning, #f59e0b);
	}

	.fse-normalize-btn {
		padding: 4px 12px;
		border: 1px solid var(--ii-brand-primary);
		border-radius: var(--ii-radius-sm, 6px);
		background: transparent;
		color: var(--ii-brand-primary);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		cursor: pointer;
		transition: all 120ms ease;
	}
	.fse-normalize-btn:hover:not(:disabled) {
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
	}
	.fse-normalize-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* ── Footer ────────────────────────────────────────────────────────────── */
	.fse-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 16px;
		border-top: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.fse-footer--muted .fse-summary {
		color: var(--ii-text-muted);
	}

	.fse-summary {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.fse-actions {
		display: flex;
		gap: 8px;
	}

	@media (max-width: 700px) {
		.fse-layout {
			grid-template-columns: 1fr;
		}
		.fse-blocks {
			border-right: none;
			border-bottom: 1px solid var(--ii-border-subtle);
			display: flex;
			overflow-x: auto;
			padding: 0;
		}
		.fse-block-item {
			white-space: nowrap;
			flex-shrink: 0;
		}
		.fse-block-item--active {
			border-left: none;
			border-bottom: 3px solid var(--ii-brand-primary);
		}
	}
</style>
