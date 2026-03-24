<!--
  Model Portfolios — Strategy Laboratory.
  Grid view with KPI cards per strategy (Conservative, Moderate, Growth).
  "New Portfolio" dialog for INVESTMENT_TEAM role.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { PageHeader, Button, StatusBadge, EmptyState, formatDateTime, formatNumber } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { profileColor } from "$lib/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);
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
	let formInceptionDate = $state("");
	let formBacktestStart = $state("");

	let isFormValid = $derived(formProfile.trim() !== "" && formDisplayName.trim() !== "");

	function openDialog() {
		formProfile = "";
		formDisplayName = "";
		formDescription = "";
		formBenchmark = "";
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

				<label class="dialog-field">
					<span class="dialog-label">Benchmark Composite</span>
					<input
						type="text"
						class="dialog-input"
						placeholder="e.g. 60% IMA-B + 40% CDI"
						bind:value={formBenchmark}
					/>
				</label>

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
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.mp-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: var(--netz-space-stack-md, 16px);
	}

	.mp-card {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		text-align: left;
		cursor: pointer;
		font-family: var(--netz-font-sans);
		transition: border-color 120ms ease, box-shadow 120ms ease;
		overflow: hidden;
	}

	.mp-card:hover {
		border-color: var(--netz-border-accent);
		box-shadow: var(--netz-shadow-2);
	}

	.mp-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.mp-profile {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.mp-name {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px) 0;
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
	}

	.mp-desc {
		padding: var(--netz-space-stack-2xs, 4px) var(--netz-space-inline-md, 16px) 0;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		line-height: 1.5;
	}

	.mp-kpis {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		margin: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px) 0;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
		background: var(--netz-border-subtle);
	}

	.mp-kpi {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		background: var(--netz-surface-elevated);
	}

	.mp-kpi-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.mp-kpi-value {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.mp-card-footer {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		margin-top: auto;
	}

	.mp-created {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
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
		margin: var(--netz-space-inline-md, 16px);
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-lg, 16px);
		box-shadow: var(--netz-shadow-3);
		overflow: hidden;
	}

	.dialog-title {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.dialog-error {
		margin: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-lg, 24px) 0;
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 12px);
		border-radius: var(--netz-radius-sm, 8px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.dialog-error-dismiss {
		margin-left: var(--netz-space-inline-sm, 8px);
		text-decoration: underline;
		cursor: pointer;
		background: none;
		border: none;
		color: inherit;
		font-size: inherit;
	}

	.dialog-form {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-sm, 12px);
	}

	.dialog-field {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
		flex: 1;
	}

	.dialog-label {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-secondary);
	}

	.dialog-required {
		color: var(--netz-danger);
	}

	.dialog-input {
		height: var(--netz-space-control-height-sm, 36px);
		padding: 0 var(--netz-space-inline-sm, 10px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
	}

	.dialog-input:focus {
		outline: none;
		border-color: var(--netz-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--netz-brand-secondary) 20%, transparent);
	}

	.dialog-textarea {
		height: auto;
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-sm, 10px);
		resize: vertical;
	}

	.dialog-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--netz-space-inline-md, 16px);
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--netz-space-inline-sm, 8px);
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-lg, 24px);
		border-top: 1px solid var(--netz-border-subtle);
	}
</style>
