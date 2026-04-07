<!--
  IC Views Panel — CRUD for Black-Litterman expected return views.
  Shows active views table + add form (IC role only).
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatPercent, formatDate, DatePicker } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Label } from "@investintell/ui/components/ui/label";
	import { createClientApiClient } from "$lib/api/client";
	import type { PortfolioView } from "$lib/types/model-portfolio";
	import type { UniverseAsset } from "$lib/types/universe";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface Props {
		portfolioId: string;
		views?: PortfolioView[];
		instruments?: UniverseAsset[];
		canEdit?: boolean;
	}

	let { portfolioId, views = [], instruments = [], canEdit = false }: Props = $props();

	// ── Local reactive state ────────────────────────────────────────────
	let localViews = $state<PortfolioView[]>([]);
	let prevViewIds = "";
	$effect(() => {
		const ids = views.map((v) => v.id).join(",");
		if (ids !== prevViewIds) {
			prevViewIds = ids;
			localViews = [...views];
		}
	});

	let submitting = $state(false);
	let deleting = $state<string | null>(null);
	let error = $state<string | null>(null);
	let confirmDeleteId = $state<string | null>(null);

	// ── Form state ──────────────────────────────────────────────────────
	let formType = $state<"absolute" | "relative">("absolute");
	let formInstrumentId = $state("");
	let formPeerId = $state("");
	let formExpectedReturnPct = $state<number | null>(null);
	let formConfidencePct = $state(70);
	let formEffectiveFrom = $state(new Date().toISOString().slice(0, 10));
	let formEffectiveTo = $state("");
	let formRationale = $state("");

	// ── Instrument search ───────────────────────────────────────────────
	let instrumentQuery = $state("");
	let peerQuery = $state("");
	let instrumentDropdownOpen = $state(false);
	let peerDropdownOpen = $state(false);

	let filteredInstruments = $derived(
		instrumentQuery.length >= 2
			? instruments.filter((i) =>
					i.fund_name.toLowerCase().includes(instrumentQuery.toLowerCase())
				).slice(0, 10)
			: []
	);

	let filteredPeers = $derived(
		peerQuery.length >= 2
			? instruments.filter((i) =>
					i.fund_name.toLowerCase().includes(peerQuery.toLowerCase()) &&
					i.instrument_id !== formInstrumentId
				).slice(0, 10)
			: []
	);

	let selectedInstrumentName = $derived(
		instruments.find((i) => i.instrument_id === formInstrumentId)?.fund_name ?? ""
	);

	let selectedPeerName = $derived(
		instruments.find((i) => i.instrument_id === formPeerId)?.fund_name ?? ""
	);

	// ── Validation ──────────────────────────────────────────────────────
	let isFormValid = $derived(
		formInstrumentId !== "" &&
		formExpectedReturnPct !== null &&
		formConfidencePct >= 1 &&
		formConfidencePct <= 100 &&
		formEffectiveFrom !== "" &&
		(formType === "absolute" || formPeerId !== "")
	);

	// ── Instrument name lookup ──────────────────────────────────────────
	function instrumentName(id: string | null): string {
		if (!id) return "—";
		return instruments.find((i) => i.instrument_id === id)?.fund_name ?? id.slice(0, 8);
	}

	// ── Actions ─────────────────────────────────────────────────────────
	async function addView() {
		if (!isFormValid || formExpectedReturnPct === null) return;
		submitting = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const body = {
				view_type: formType,
				asset_instrument_id: formInstrumentId,
				peer_instrument_id: formType === "relative" ? formPeerId : null,
				expected_return: formExpectedReturnPct / 100,
				confidence: formConfidencePct / 100,
				rationale: formRationale.trim() || null,
				effective_from: formEffectiveFrom,
				effective_to: formEffectiveTo || null,
			};
			const created = await api.post<PortfolioView>(
				`/model-portfolios/${portfolioId}/views`,
				body,
			);
			localViews = [...localViews, created];
			resetForm();
		} catch (e: unknown) {
			if (e instanceof Error && e.message.includes("403")) {
				error = "Permission denied. Only Investment Committee members can manage views.";
			} else {
				error = e instanceof Error ? e.message : "Failed to add view";
			}
		} finally {
			submitting = false;
		}
	}

	async function deleteView(viewId: string) {
		deleting = viewId;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.delete(`/model-portfolios/${portfolioId}/views/${viewId}`);
			localViews = localViews.filter((v) => v.id !== viewId);
		} catch (e: unknown) {
			if (e instanceof Error && e.message.includes("403")) {
				error = "Permission denied. Only Investment Committee members can manage views.";
			} else {
				error = e instanceof Error ? e.message : "Failed to delete view";
			}
		} finally {
			deleting = null;
			confirmDeleteId = null;
		}
	}

	function resetForm() {
		formType = "absolute";
		formInstrumentId = "";
		formPeerId = "";
		formExpectedReturnPct = null;
		formConfidencePct = 70;
		formEffectiveFrom = new Date().toISOString().slice(0, 10);
		formEffectiveTo = "";
		formRationale = "";
		instrumentQuery = "";
		peerQuery = "";
	}

	function selectInstrument(asset: UniverseAsset) {
		formInstrumentId = asset.instrument_id;
		instrumentQuery = asset.fund_name;
		instrumentDropdownOpen = false;
	}

	function selectPeer(asset: UniverseAsset) {
		formPeerId = asset.instrument_id;
		peerQuery = asset.fund_name;
		peerDropdownOpen = false;
	}
</script>

<section class="mp-section mp-section--full">
	<h3 class="mp-section-title">
		IC Views
		{#if localViews.length > 0}
			<span class="mp-section-count">{localViews.length} active</span>
		{/if}
	</h3>

	{#if error}
		<div class="views-error">
			{error}
			<button class="views-error-dismiss" onclick={() => (error = null)}>dismiss</button>
		</div>
	{/if}

	<div class="views-content">
		<!-- ── Views table ────────────────────────────────────────────── -->
		{#if localViews.length === 0}
			<div class="mp-empty">
				<p>No views registered. The optimizer is using market equilibrium prior.</p>
			</div>
		{:else}
			<div class="views-table-wrap">
				<table class="views-table">
					<thead>
						<tr>
							<th class="th-instrument">Instrument</th>
							<th class="th-peer">Peer</th>
							<th class="th-type">Type</th>
							<th class="th-return">Expected Return</th>
							<th class="th-confidence">Confidence</th>
							<th class="th-from">Valid From</th>
							<th class="th-to">Valid To</th>
							{#if canEdit}
								<th class="th-actions"></th>
							{/if}
						</tr>
					</thead>
					<tbody>
						{#each localViews as view (view.id)}
							<tr class="views-row">
								<td class="td-instrument">
									{instrumentName(view.asset_instrument_id)}
									{#if view.rationale}
										<span class="rationale-icon" title={view.rationale}>i</span>
									{/if}
								</td>
								<td class="td-peer">
									{#if view.view_type === "relative"}
										{instrumentName(view.peer_instrument_id)}
									{:else}
										—
									{/if}
								</td>
								<td class="td-type">
									<span
										class="type-badge"
										class:type-badge-relative={view.view_type === "relative"}
									>
										{view.view_type === "absolute" ? "Absolute" : "Relative"}
									</span>
								</td>
								<td class="td-return">{formatPercent(view.expected_return)}</td>
								<td class="td-confidence">
									<div class="confidence-bar-track">
										<div
											class="confidence-bar-fill"
											style:width="{view.confidence * 100}%"
										></div>
									</div>
									<span class="confidence-value">{formatPercent(view.confidence)}</span>
								</td>
								<td class="td-from">{formatDate(view.effective_from)}</td>
								<td class="td-to">{view.effective_to ? formatDate(view.effective_to) : "—"}</td>
								{#if canEdit}
									<td class="td-actions">
										{#if confirmDeleteId === view.id}
											<div class="confirm-delete">
												<span class="confirm-text">Remove?</span>
												<button
													class="confirm-yes"
													onclick={() => deleteView(view.id)}
													disabled={deleting === view.id}
												>
													{deleting === view.id ? "..." : "Yes"}
												</button>
												<button
													class="confirm-no"
													onclick={() => (confirmDeleteId = null)}
												>
													No
												</button>
											</div>
										{:else}
											<button
												class="delete-btn"
												onclick={() => (confirmDeleteId = view.id)}
											>
												Delete
											</button>
										{/if}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		<!-- ── Add view form (IC role only) ───────────────────────────── -->
		{#if canEdit}
			<div class="add-view-form">
				<h4 class="form-title">Add IC View</h4>
				<div class="form-grid">
					<!-- View type -->
					<div class="form-field">
						<label class="form-label" for="view-type">Type</label>
						<select id="view-type" class="form-select" bind:value={formType}>
							<option value="absolute">Absolute</option>
							<option value="relative">Relative</option>
						</select>
					</div>

					<!-- Instrument picker -->
					<div class="form-field">
						<label class="form-label" for="view-instrument">Instrument</label>
						<div class="picker-wrap">
							<input
								id="view-instrument"
								type="text"
								class="form-input"
								placeholder="Search funds..."
								value={formInstrumentId ? selectedInstrumentName : instrumentQuery}
								oninput={(e) => {
									instrumentQuery = e.currentTarget.value;
									formInstrumentId = "";
								}}
								onfocus={() => (instrumentDropdownOpen = true)}
								onblur={() => setTimeout(() => (instrumentDropdownOpen = false), 200)}
								autocomplete="off"
							/>
							{#if instrumentDropdownOpen && filteredInstruments.length > 0}
								<div class="picker-dropdown">
									{#each filteredInstruments as asset (asset.instrument_id)}
										<button
											class="picker-option"
											type="button"
											onmousedown={(e) => { e.preventDefault(); selectInstrument(asset); }}
										>
											{asset.fund_name}
										</button>
									{/each}
								</div>
							{/if}
						</div>
					</div>

					<!-- Peer picker (relative only) -->
					{#if formType === "relative"}
						<div class="form-field">
							<label class="form-label" for="view-peer">Peer</label>
							<div class="picker-wrap">
								<input
									id="view-peer"
									type="text"
									class="form-input"
									placeholder="Search peer fund..."
									value={formPeerId ? selectedPeerName : peerQuery}
									oninput={(e) => {
										peerQuery = e.currentTarget.value;
										formPeerId = "";
									}}
									onfocus={() => (peerDropdownOpen = true)}
									onblur={() => setTimeout(() => (peerDropdownOpen = false), 200)}
									autocomplete="off"
								/>
								{#if peerDropdownOpen && filteredPeers.length > 0}
									<div class="picker-dropdown">
										{#each filteredPeers as asset (asset.instrument_id)}
											<button
												class="picker-option"
												type="button"
												onmousedown={(e) => { e.preventDefault(); selectPeer(asset); }}
											>
												{asset.fund_name}
											</button>
										{/each}
									</div>
								{/if}
							</div>
						</div>
					{/if}

					<!-- Expected return -->
					<div class="form-field">
						<label class="form-label" for="view-return">Expected Return (%)</label>
						<input
							id="view-return"
							type="number"
							class="form-input"
							placeholder="e.g. 8.5"
							step="0.1"
							bind:value={formExpectedReturnPct}
						/>
					</div>

					<!-- Confidence -->
					<div class="form-field">
						<label class="form-label" for="view-confidence">Confidence (%)</label>
						<div class="confidence-input-wrap">
							<input
								id="view-confidence"
								type="range"
								class="form-range"
								min="1"
								max="100"
								bind:value={formConfidencePct}
							/>
							<span class="confidence-display">{formConfidencePct}%</span>
						</div>
					</div>

					<!-- Effective from -->
					<div class="form-field">
						<Label for="view-from">Valid From</Label>
						<DatePicker
							bind:value={formEffectiveFrom}
							placeholder="Select start date"
						/>
					</div>

					<!-- Effective to -->
					<div class="form-field">
						<Label for="view-to">Valid To (optional)</Label>
						<DatePicker
							bind:value={formEffectiveTo}
							placeholder="Select end date"
						/>
					</div>

					<!-- Rationale -->
					<div class="form-field form-field--wide">
						<label class="form-label" for="view-rationale">Rationale (optional)</label>
						<textarea
							id="view-rationale"
							class="form-textarea"
							rows="2"
							placeholder="IC justification for this view..."
							bind:value={formRationale}
						></textarea>
					</div>
				</div>

				<div class="form-actions">
					<Button size="sm" onclick={addView} disabled={!isFormValid || submitting}>
						{submitting ? "Adding..." : "Add View"}
					</Button>
				</div>
			</div>
		{/if}
	</div>
</section>

<style>
	/* ── Reuse page-level section styles via class names ──────────── */
	.mp-section {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.mp-section--full {
		grid-column: 1 / -1;
	}

	.mp-section-title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.mp-section-count {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 400;
		color: var(--ii-text-muted);
	}

	.mp-empty {
		padding: var(--ii-space-stack-lg, 32px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Error ────────────────────────────────────────────────────── */
	.views-error {
		margin: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px) 0;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 12px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.views-error-dismiss {
		margin-left: var(--ii-space-inline-sm, 8px);
		text-decoration: underline;
		cursor: pointer;
		background: none;
		border: none;
		color: inherit;
		font-size: inherit;
	}

	.views-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	/* ── Views table ──────────────────────────────────────────────── */
	.views-table-wrap {
		overflow-x: auto;
	}

	.views-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.views-table th {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.views-table td {
		padding: var(--ii-space-stack-2xs, 8px) var(--ii-space-inline-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
		vertical-align: middle;
	}

	.views-row:hover {
		background: var(
			--ii-surface-highlight,
			color-mix(in srgb, var(--ii-brand-primary) 4%, transparent)
		);
	}

	.th-instrument { min-width: 180px; }
	.th-peer { min-width: 140px; }
	.th-type { min-width: 80px; }
	.th-return { min-width: 110px; text-align: right; }
	.th-confidence { min-width: 130px; }
	.th-from { min-width: 100px; }
	.th-to { min-width: 100px; }
	.th-actions { width: 90px; }

	.td-instrument {
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.rationale-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		margin-left: 4px;
		border-radius: 50%;
		background: color-mix(in srgb, var(--ii-brand-primary) 12%, transparent);
		color: var(--ii-brand-primary);
		font-size: 10px;
		font-weight: 700;
		font-style: italic;
		cursor: help;
		vertical-align: middle;
	}

	.td-peer {
		color: var(--ii-text-secondary);
	}

	.td-return {
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.type-badge {
		display: inline-block;
		padding: 1px 8px;
		border-radius: var(--ii-radius-pill, 999px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
	}

	.type-badge-relative {
		background: color-mix(in srgb, var(--ii-warning) 12%, transparent);
		color: var(--ii-warning);
	}

	/* ── Confidence bar ───────────────────────────────────────────── */
	.td-confidence {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.confidence-bar-track {
		flex: 1;
		height: 6px;
		background: var(--ii-surface-alt);
		border-radius: 3px;
		overflow: hidden;
		min-width: 60px;
	}

	.confidence-bar-fill {
		height: 100%;
		background: var(--ii-brand-primary);
		border-radius: 3px;
		transition: width 200ms ease;
	}

	.confidence-value {
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-secondary);
		white-space: nowrap;
	}

	/* ── Delete confirm ───────────────────────────────────────────── */
	.td-actions {
		text-align: center;
	}

	.delete-btn {
		padding: 2px 8px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface);
		color: var(--ii-danger);
		font-size: var(--ii-text-label, 0.75rem);
		cursor: pointer;
	}

	.delete-btn:hover {
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
	}

	.confirm-delete {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--ii-text-label, 0.75rem);
	}

	.confirm-text {
		color: var(--ii-danger);
		font-weight: 500;
	}

	.confirm-yes,
	.confirm-no {
		padding: 1px 6px;
		border: 1px solid var(--ii-border);
		border-radius: 4px;
		font-size: var(--ii-text-label, 0.75rem);
		cursor: pointer;
		background: var(--ii-surface);
	}

	.confirm-yes {
		color: var(--ii-danger);
	}

	.confirm-no {
		color: var(--ii-text-secondary);
	}

	/* ── Add view form ────────────────────────────────────────────── */
	.add-view-form {
		margin-top: var(--ii-space-stack-md, 16px);
		padding-top: var(--ii-space-stack-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.form-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.form-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.form-field--wide {
		grid-column: 1 / -1;
	}

	.form-label {
		display: block;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
		color: var(--ii-text-muted);
		margin-bottom: 4px;
	}

	.form-input,
	.form-select,
	.form-textarea {
		width: 100%;
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.form-textarea {
		height: auto;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		resize: vertical;
	}

	.form-input:focus,
	.form-select:focus,
	.form-textarea:focus {
		outline: none;
		border-color: var(--ii-brand-primary);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	/* ── Instrument picker dropdown ───────────────────────────────── */
	.picker-wrap {
		position: relative;
	}

	.picker-dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		z-index: 10;
		max-height: 200px;
		overflow-y: auto;
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
	}

	.picker-option {
		display: block;
		width: 100%;
		padding: 6px 10px;
		border: none;
		background: none;
		text-align: left;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-primary);
		cursor: pointer;
	}

	.picker-option:hover {
		background: var(--ii-surface-alt);
	}

	/* ── Confidence slider ────────────────────────────────────────── */
	.confidence-input-wrap {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.form-range {
		flex: 1;
		accent-color: var(--ii-brand-primary);
	}

	.confidence-display {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
		min-width: 40px;
		text-align: right;
	}

	/* ── Form actions ─────────────────────────────────────────────── */
	.form-actions {
		margin-top: var(--ii-space-stack-sm, 12px);
		display: flex;
		justify-content: flex-end;
	}
</style>
