<!--
  Model Portfolios — Strategy Laboratory.
  Grid view with KPI cards per strategy (Conservative, Moderate, Growth).
  "New Portfolio" dialog for INVESTMENT_TEAM role.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { PageHeader, StatusBadge, EmptyState, formatDateTime, formatNumber } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { profileColor } from "$lib/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	interface BlockBrief {
		block_id: string;
		display_name: string;
		benchmark_ticker: string | null;
		geography: string;
		asset_class: string;
	}

	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);
	let blocks = $derived((data.blocks ?? []) as BlockBrief[]);
	let actorRole = $derived((data.actorRole ?? null) as string | null);

	const IC_ROLES = ["investment_team", "director", "admin"];
	let canCreate = $derived(actorRole !== null && IC_ROLES.includes(actorRole));

	// ── Creation dialog ──────────────────────────────────────────────────

	let dialogOpen = $state(false);
	let submitting = $state(false);
	let formError = $state<string | null>(null);

	let formProfile = $state("");
	let formDisplayName = $state("");
	let formDescription = $state("");
	let formBenchmark = $state("");
	let benchmarkQuery = $state("");
	let benchmarkDropdownOpen = $state(false);
	let benchmarkSuggestions = $derived.by(() => {
		if (!benchmarkQuery) return blocks.slice(0, 10);
		const q = benchmarkQuery.toLowerCase();
		return blocks.filter(
			(b) =>
				b.display_name.toLowerCase().includes(q) ||
				b.benchmark_ticker?.toLowerCase().includes(q) ||
				b.block_id.toLowerCase().includes(q)
		).slice(0, 10);
	});

	function selectBenchmark(block: BlockBrief) {
		formBenchmark = block.display_name;
		benchmarkQuery = block.display_name;
		benchmarkDropdownOpen = false;
	}

	function handleBenchmarkInput(e: Event) {
		benchmarkQuery = (e.target as HTMLInputElement).value;
		formBenchmark = benchmarkQuery;
		benchmarkDropdownOpen = true;
	}

	function handleBenchmarkFocus() {
		benchmarkDropdownOpen = true;
	}

	function handleBenchmarkBlur() {
		// Delay to allow click on dropdown item
		setTimeout(() => { benchmarkDropdownOpen = false; }, 200);
	}

	let formInceptionDate = $state("");
	let formBacktestStart = $state("");

	let isFormValid = $derived(formProfile.trim() !== "" && formDisplayName.trim() !== "");

	function openDialog() {
		formProfile = "";
		formDisplayName = "";
		formDescription = "";
		formBenchmark = "";
		benchmarkQuery = "";
		benchmarkDropdownOpen = false;
		formInceptionDate = "";
		formBacktestStart = "";
		formError = null;
		dialogOpen = true;
	}

	function closeDialog() {
		dialogOpen = false;
	}

	async function handleCreate() {
		if (!isFormValid) return;
		submitting = true;
		formError = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<ModelPortfolio>("/model-portfolios", {
				profile: formProfile.trim(),
				display_name: formDisplayName.trim(),
				description: formDescription.trim() || null,
				benchmark_composite: formBenchmark.trim() || null,
				inception_date: formInceptionDate || null,
				backtest_start_date: formBacktestStart || null,
			});
			dialogOpen = false;
			goto(`/model-portfolios/${result.id}`);
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				formError = "A portfolio with this profile already exists.";
			} else {
				formError = e instanceof Error ? e.message : "Failed to create portfolio.";
			}
		} finally {
			submitting = false;
		}
	}
</script>

<PageHeader title="Model Portfolios">
	{#snippet actions()}
		{#if canCreate}
			<Button size="sm" onclick={openDialog}>New Portfolio</Button>
		{/if}
	{/snippet}
</PageHeader>

<div class="mp-page">
	{#if portfolios.length === 0}
		<EmptyState title="No model portfolios" message="Create a strategy to begin portfolio construction." />
	{:else}
		<div class="mp-grid">
			{#each portfolios as mp (mp.id)}
				<button class="mp-card" onclick={() => goto(`/model-portfolios/${mp.id}`)}>
					<div class="mp-card-header">
						<span class="mp-profile" style:color={profileColor(mp.profile)}>
							{mp.profile}
						</span>
						<StatusBadge status={mp.status} />
					</div>

					<h3 class="mp-name">{mp.display_name}</h3>

					{#if mp.description}
						<p class="mp-desc">{mp.description}</p>
					{/if}

					<div class="mp-kpis">
						<div class="mp-kpi">
							<span class="mp-kpi-label">Inception NAV</span>
							<span class="mp-kpi-value">{formatNumber(mp.inception_nav)}</span>
						</div>
						{#if mp.inception_date}
							<div class="mp-kpi">
								<span class="mp-kpi-label">Inception</span>
								<span class="mp-kpi-value">{mp.inception_date}</span>
							</div>
						{/if}
						{#if mp.benchmark_composite}
							<div class="mp-kpi">
								<span class="mp-kpi-label">Benchmark</span>
								<span class="mp-kpi-value">{mp.benchmark_composite}</span>
							</div>
						{/if}
						{#if mp.fund_selection_schema}
							<div class="mp-kpi">
								<span class="mp-kpi-label">Funds</span>
								<span class="mp-kpi-value">{mp.fund_selection_schema.funds.length}</span>
							</div>
						{/if}
					</div>

					<div class="mp-card-footer">
						<span class="mp-created">{formatDateTime(mp.created_at)}</span>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- CREATE PORTFOLIO DIALOG                                                -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
{#if dialogOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="dialog-backdrop" onclick={closeDialog} onkeydown={(e) => e.key === "Escape" && closeDialog()}>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="dialog-panel" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
			<h2 class="dialog-title">New Model Portfolio</h2>

			{#if formError}
				<div class="dialog-error">
					{formError}
					<button class="dialog-error-dismiss" onclick={() => formError = null}>dismiss</button>
				</div>
			{/if}

			<div class="dialog-form">
				<label class="dialog-field">
					<span class="dialog-label">Profile <span class="dialog-required">*</span></span>
					<input
						type="text"
						class="dialog-input"
						placeholder="e.g. conservative, moderate, growth"
						bind:value={formProfile}
					/>
				</label>

				<label class="dialog-field">
					<span class="dialog-label">Display Name <span class="dialog-required">*</span></span>
					<input
						type="text"
						class="dialog-input"
						placeholder="Conservative Strategy"
						bind:value={formDisplayName}
					/>
				</label>

				<label class="dialog-field">
					<span class="dialog-label">Description</span>
					<textarea
						class="dialog-input dialog-textarea"
						placeholder="Optional description..."
						rows="2"
						bind:value={formDescription}
					></textarea>
				</label>

				<div class="dialog-field benchmark-field">
					<span class="dialog-label">Benchmark</span>
					<div class="benchmark-autocomplete">
						<input
							type="text"
							class="dialog-input"
							placeholder="Search benchmarks…"
							value={benchmarkQuery}
							oninput={handleBenchmarkInput}
							onfocus={handleBenchmarkFocus}
							onblur={handleBenchmarkBlur}
							autocomplete="off"
						/>
						{#if benchmarkDropdownOpen && benchmarkSuggestions.length > 0}
							<div class="benchmark-dropdown">
								{#each benchmarkSuggestions as block (block.block_id)}
									<button
										class="benchmark-option"
										type="button"
										onmousedown={(e) => { e.preventDefault(); selectBenchmark(block); }}
									>
										<span class="benchmark-option-name">{block.display_name}</span>
										<span class="benchmark-option-meta">
											{block.benchmark_ticker ?? ""} · {block.geography} · {block.asset_class}
										</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				<div class="dialog-row">
					<label class="dialog-field">
						<span class="dialog-label">Inception Date</span>
						<input type="date" class="dialog-input" bind:value={formInceptionDate} />
					</label>
					<label class="dialog-field">
						<span class="dialog-label">Backtest Start</span>
						<input type="date" class="dialog-input" bind:value={formBacktestStart} />
					</label>
				</div>
			</div>

			<div class="dialog-actions">
				<Button size="sm" variant="ghost" onclick={closeDialog} disabled={submitting}>Cancel</Button>
				<Button size="sm" onclick={handleCreate} disabled={!isFormValid || submitting}>
					{submitting ? "Creating…" : "Create Portfolio"}
				</Button>
			</div>
		</div>
	</div>
{/if}

<style>
	.mp-page {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
	}

	.mp-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: var(--ii-space-stack-md, 16px);
	}

	.mp-card {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		text-align: left;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: border-color 120ms ease, box-shadow 120ms ease;
		overflow: hidden;
	}

	.mp-card:hover {
		border-color: var(--ii-border-accent);
		box-shadow: var(--ii-shadow-2);
	}

	.mp-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.mp-profile {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.mp-name {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px) 0;
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.mp-desc {
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px) 0;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		line-height: 1.5;
	}

	.mp-kpis {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		margin: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px) 0;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
		background: var(--ii-border-subtle);
	}

	.mp-kpi {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		background: var(--ii-surface-elevated);
	}

	.mp-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.mp-kpi-value {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.mp-card-footer {
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		margin-top: auto;
	}

	.mp-created {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	/* ── Dialog ───────────────────────────────────────────────────────────── */
	.dialog-backdrop {
		position: fixed;
		inset: 0;
		z-index: 50;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(0, 0, 0, 0.5);
	}

	.dialog-panel {
		width: 100%;
		max-width: 520px;
		margin: var(--ii-space-inline-md, 16px);
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-lg, 16px);
		box-shadow: var(--ii-shadow-3);
		overflow: hidden;
	}

	.dialog-title {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.dialog-error {
		margin: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-lg, 24px) 0;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 12px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.dialog-error-dismiss {
		margin-left: var(--ii-space-inline-sm, 8px);
		text-decoration: underline;
		cursor: pointer;
		background: none;
		border: none;
		color: inherit;
		font-size: inherit;
	}

	.dialog-form {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-sm, 12px);
	}

	.dialog-field {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
		flex: 1;
	}

	.dialog-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.dialog-required {
		color: var(--ii-danger);
	}

	.dialog-input {
		height: var(--ii-space-control-height-sm, 36px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.dialog-input:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-secondary) 20%, transparent);
	}

	.dialog-textarea {
		height: auto;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		resize: vertical;
	}

	/* ── Benchmark autocomplete ─────────────────────────────────────────── */
	.benchmark-field {
		position: relative;
	}

	.benchmark-autocomplete {
		position: relative;
	}

	.benchmark-dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		z-index: 10;
		max-height: 220px;
		overflow-y: auto;
		border: 1px solid var(--ii-border);
		border-top: none;
		border-radius: 0 0 var(--ii-radius-sm, 8px) var(--ii-radius-sm, 8px);
		background: var(--ii-surface-elevated);
		box-shadow: var(--ii-shadow-2);
	}

	.benchmark-option {
		display: flex;
		flex-direction: column;
		gap: 1px;
		width: 100%;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		border: none;
		background: transparent;
		text-align: left;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: background 80ms ease;
	}

	.benchmark-option:hover {
		background: var(--ii-surface-alt);
	}

	.benchmark-option-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.benchmark-option-meta {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.dialog-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--ii-space-inline-md, 16px);
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-lg, 24px);
		border-top: 1px solid var(--ii-border-subtle);
	}
</style>
