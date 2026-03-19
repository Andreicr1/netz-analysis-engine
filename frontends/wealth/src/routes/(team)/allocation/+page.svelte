<!--
  Allocation — strategic, tactical, and effective views with profile selector.
  Governed save flow: simulate → preview CVaR → ConsequenceDialog with rationale.
-->
<script lang="ts">
	import {
		BarChart,
		PageHeader,
		PageTabs,
		EmptyState,
		Button,
		Input,
		formatNumber,
		formatPercent,
		formatBps,
		MetricCard,
		ConsequenceDialog,
	} from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	// Inline SimulationResult type from API schema
	type SimulationResult = {
		profile: string;
		proposed_cvar_95_3m?: string | null;
		cvar_limit?: string | null;
		cvar_utilization_pct?: string | null;
		cvar_delta_vs_current?: string | null;
		tracking_error_expected?: string | null;
		within_limit: boolean;
		warnings: string[];
		computed_at: string;
	};

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type AllocationRow = {
		block: string;
		weight: number;
		min_weight: number | null;
		max_weight: number | null;
	};

	type TacticalPosition = {
		block: string;
		overweight: number;
		conviction: number | null;
	};

	type EffectiveRow = {
		block: string;
		strategic_weight: number;
		tactical_overweight: number;
		effective_weight: number;
	};

	let strategic = $derived((data.strategic ?? []) as AllocationRow[]);
	let tactical = $derived((data.tactical ?? []) as TacticalPosition[]);
	let effective = $derived((data.effective ?? []) as EffectiveRow[]);

	// svelte-ignore state_referenced_locally
	let activeProfile = $state(data.profile as string);
	const profiles = ["conservative", "moderate", "growth"];
	const profileLabels: Record<string, string> = {
		conservative: "Conservative",
		moderate: "Moderate",
		growth: "Growth",
	};

	type Tab = "strategic" | "tactical" | "effective";
	const tabs: { value: Tab; label: string }[] = [
		{ value: "strategic", label: "Strategic" },
		{ value: "tactical", label: "Tactical" },
		{ value: "effective", label: "Effective" },
	];

	function switchProfile(profile: string) {
		activeProfile = profile;
		goto(`/allocation?profile=${profile}`, { invalidateAll: true });
	}

	// Bar chart data
	let strategicChartData = $derived(
		strategic.map((r) => ({ name: r.block, value: r.weight * 100 })),
	);

	let effectiveChartData = $derived(
		effective.map((r) => ({ name: r.block, value: r.effective_weight * 100 })),
	);

	let totalWeight = $derived(
		effective.reduce((sum, r) => sum + r.effective_weight, 0),
	);

	let activeProfileLabel = $derived(profileLabels[activeProfile] ?? activeProfile);
	let tacticalCount = $derived(tactical.length);
	let activeBlockCount = $derived(strategic.length);
	let largestTacticalTilt = $derived.by(() => {
		if (tactical.length === 0) return null;
		return [...tactical].sort((left, right) => Math.abs(right.overweight) - Math.abs(left.overweight))[0] ?? null;
	});

	// ── Edit Mode ──
	let editing = $state(false);
	let saving = $state(false);
	let editError = $state<string | null>(null);

	// Editable copies for strategic weights
	let editWeights = $state<Record<string, number>>({});

	function startEditing() {
		editWeights = {};
		for (const row of strategic) {
			editWeights[row.block] = row.weight * 100;
		}
		editError = null;
		editing = true;
	}

	function cancelEditing() {
		editing = false;
		editError = null;
	}

	let editTotal = $derived(
		Object.values(editWeights).reduce((sum, v) => sum + v, 0),
	);

	let editDelta = $derived(Math.abs(editTotal - 100));
	let editValid = $derived(editDelta < 0.1); // must sum to 100%

	function fmtPercentPoint(value: number, decimals = 1): string {
		return `${formatNumber(value, decimals, "en-US")}%`;
	}

	function fmtSignedPercentPoint(value: number, decimals = 1): string {
		const formatted = formatNumber(value, decimals, "en-US");
		return value >= 0 ? `+${formatted}%` : `${formatted}%`;
	}

	// Tactical save
	let editTactical = $state<Record<string, number>>({});
	let editingTactical = $state(false);
	let savingTactical = $state(false);

	function startEditingTactical() {
		editTactical = {};
		for (const pos of tactical) {
			editTactical[pos.block] = pos.overweight * 100;
		}
		editingTactical = true;
	}

	// ── Simulation + Governance ──────────────────────────────────
	let simulationResult = $state<SimulationResult | null>(null);
	let simulating = $state(false);
	let simError = $state<string | null>(null);
	let showConfirmDialog = $state(false);
	let showTacticalDialog = $state(false);

	/** Opens tactical ConsequenceDialog instead of saving directly. */
	function handleSaveTacticalClick() {
		showTacticalDialog = true;
	}

	/** Final tactical save — called from ConsequenceDialog onConfirm. */
	async function confirmSaveTactical({ rationale }: { rationale?: string }) {
		savingTactical = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const tilts: Record<string, number> = {};
			for (const [block, w] of Object.entries(editTactical)) {
				tilts[block] = w / 100;
			}
			await api.put(`/allocation/${activeProfile}/tactical`, {
				tilts,
				...(rationale ? { rationale } : {}),
			});
			editingTactical = false;
			await invalidateAll();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to save tactical allocation";
		} finally {
			savingTactical = false;
		}
	}

	/**
	 * Runs simulation against the proposed strategic weights.
	 * Returns false if within_limit is false — callers should block submit.
	 */
	async function runSimulation(): Promise<boolean> {
		if (!editValid) return false;
		simulating = true;
		simError = null;
		simulationResult = null;
		try {
			const api = createClientApiClient(getToken);
			const weights: Record<string, number> = {};
			for (const [block, w] of Object.entries(editWeights)) {
				weights[block] = w / 100;
			}
			const result = await api.post<SimulationResult>(
				`/allocation/${activeProfile}/simulate`,
				{ weights, rationale: "pre-save simulation" },
			);
			simulationResult = result;
			return result.within_limit === true;
		} catch (e) {
			simError = e instanceof Error ? e.message : "Simulation failed";
			return false;
		} finally {
			simulating = false;
		}
	}

	/**
	 * Called when user clicks "Save" on strategic tab.
	 * Runs simulation first; opens ConsequenceDialog only when within_limit.
	 */
	async function handleSaveStrategicClick() {
		const withinLimit = await runSimulation();
		if (!withinLimit) {
			// Block — simulationResult.within_limit === false, error shown in UI
			return;
		}
		showConfirmDialog = true;
	}

	/** Final save — called from ConsequenceDialog onConfirm with rationale. */
	async function confirmSaveStrategic({ rationale }: { rationale?: string }) {
		if (!editValid) return;
		saving = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const weights: Record<string, number> = {};
			for (const [block, w] of Object.entries(editWeights)) {
				weights[block] = w / 100;
			}
			await api.put(`/allocation/${activeProfile}/strategic`, {
				weights,
				...(rationale ? { rationale } : {}),
			});
			editing = false;
			simulationResult = null;
			await invalidateAll();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to save allocation";
		} finally {
			saving = false;
		}
	}

	// Simulation metric helpers
	function fmtSimBps(v: string | number | null | undefined): string {
		if (v == null) return "—";
		const n = typeof v === "string" ? parseFloat(v) : v;
		return isNaN(n) ? "—" : formatBps(n);
	}

	function fmtSimPct(v: string | number | null | undefined): string {
		if (v == null) return "—";
		const n = typeof v === "string" ? parseFloat(v) : v;
		return isNaN(n) ? "—" : formatPercent(n, 2, "en-US");
	}

	function convictionWidth(conviction: number | null): string {
		if (conviction == null) return "0%";
		return `${Math.min(Math.max(conviction, 0), 5) * 20}%`;
	}

	function convictionLabel(conviction: number | null): string {
		if (conviction == null) return "Unspecified";
		if (conviction >= 4) return "High";
		if (conviction >= 2.5) return "Medium";
		return "Low";
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Allocation">
		{#snippet actions()}
			<div class="flex gap-1">
				{#each profiles as profile (profile)}
					<button
						class="rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors {activeProfile === profile
							? 'bg-(--netz-primary) text-white'
							: 'text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)'}"
						onclick={() => switchProfile(profile)}
					>
						{profile}
					</button>
				{/each}
			</div>
		{/snippet}
	</PageHeader>
	<p class="mt-1 text-sm text-(--netz-text-muted)">
		Strategic targets, tactical tilts, and effective exposure for the {activeProfileLabel} profile.
	</p>

	<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
		<MetricCard label="Active Profile" value={activeProfileLabel} sublabel="Current allocation lens" />
		<MetricCard label="Strategic Blocks" value={String(activeBlockCount)} sublabel="Configured allocation buckets" />
		<MetricCard label="Tactical Tilts" value={String(tacticalCount)} sublabel="Live model adjustments" />
		<MetricCard
			label="Largest Tilt"
			value={largestTacticalTilt ? fmtSignedPercentPoint(largestTacticalTilt.overweight, 1) : "—"}
			sublabel={largestTacticalTilt?.block ?? "No tactical positions"}
			status={largestTacticalTilt && Math.abs(largestTacticalTilt.overweight) >= 0.03 ? "warn" : undefined}
		/>
	</div>

	{#if editError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{editError}
			<button class="ml-2 underline" onclick={() => editError = null}>dismiss</button>
		</div>
	{/if}

	<PageTabs tabs={tabs} defaultTab="effective">
		{#snippet children(activeTab)}

	<!-- Strategic View -->
	{#if activeTab === "strategic"}
		{#if strategic.length > 0}
			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-5">
					<div class="mb-4 flex items-center justify-between">
						<h3 class="text-sm font-semibold text-(--netz-text-primary)">Strategic Weights</h3>
						{#if !editing}
							<Button size="sm" variant="outline" onclick={startEditing}>Edit</Button>
						{:else}
							<div class="flex items-center gap-2">
								<span class="text-xs {editValid ? 'text-(--netz-success,#22c55e)' : 'text-(--netz-danger,#ef4444)'}">
									Total: {fmtPercentPoint(editTotal)} {editValid ? "✓" : `(${fmtSignedPercentPoint(editTotal - 100)})`}
								</span>
								<Button size="sm" variant="outline" onclick={cancelEditing}>Cancel</Button>
								<ActionButton
									size="sm"
									onclick={handleSaveStrategicClick}
									loading={simulating || saving}
									loadingText={simulating ? "Simulating…" : "Saving…"}
									disabled={!editValid}
								>
									Review & Save
								</ActionButton>
							</div>
						{/if}
					</div>
					<div class="space-y-3">
						{#each strategic as row (row.block)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-(--netz-text-primary)">{row.block}</span>
								<div class="flex items-center gap-2">
									{#if row.min_weight !== null && row.max_weight !== null}
										<span class="text-xs text-(--netz-text-muted)">
											[{formatPercent(row.min_weight, 0, "en-US")}–{formatPercent(row.max_weight, 0, "en-US")}]
										</span>
									{/if}
									{#if editing}
										{@const blockWeight = editWeights[row.block] ?? 0}
										{@const belowMin = row.min_weight !== null && blockWeight < row.min_weight * 100}
										{@const aboveMax = row.max_weight !== null && blockWeight > row.max_weight * 100}
										{@const outOfBounds = belowMin || aboveMax}
										<Input
											type="number"
											class="w-20 text-right {outOfBounds ? 'border-(--netz-danger)' : ''}"
											bind:value={editWeights[row.block]}
											min={row.min_weight !== null ? row.min_weight * 100 : 0}
											max={row.max_weight !== null ? row.max_weight * 100 : 100}
											step="0.1"
											title={outOfBounds ? `Out of bounds: min ${row.min_weight !== null ? row.min_weight * 100 : 0}% — max ${row.max_weight !== null ? row.max_weight * 100 : 100}%` : undefined}
										/>
										{#if outOfBounds}
											<span class="text-xs text-(--netz-danger)">{belowMin ? "↓ min" : "↑ max"}</span>
										{/if}
									{:else}
										<span class="font-medium text-(--netz-text-primary)">
											{formatPercent(row.weight, 1, "en-US")}
										</span>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
				<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-5">
					<h3 class="mb-4 text-sm font-semibold text-(--netz-text-primary)">Distribution</h3>
					<div class="h-64">
						<BarChart data={strategicChartData} orientation="horizontal" />
					</div>
				</div>
			</div>
		{:else}
			<EmptyState title="No Strategic Allocation" message="Strategic allocation has not been configured." />
		{/if}

		<!-- Simulation error -->
		{#if simError}
			<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{simError}
				<button class="ml-2 underline" onclick={() => simError = null}>dismiss</button>
			</div>
		{/if}

		<!-- Simulation result panel -->
		{#if simulationResult}
			<div class="rounded-lg border {simulationResult.within_limit ? 'border-(--netz-border)' : 'border-(--netz-status-error)'} bg-(--netz-surface-elevated) p-5">
				<div class="mb-3 flex items-center justify-between">
					<h3 class="text-sm font-semibold text-(--netz-text-primary)">CVaR Simulation Preview</h3>
					{#if simulationResult.within_limit}
						<span class="inline-flex items-center gap-1 rounded-full bg-(--netz-success,#22c55e)/15 px-2 py-0.5 text-xs font-medium text-(--netz-success,#22c55e)">
							Within Limit
						</span>
					{:else}
						<span class="inline-flex items-center gap-1 rounded-full bg-(--netz-status-error)/15 px-2 py-0.5 text-xs font-medium text-(--netz-status-error)">
							Exceeds CVaR Limit — Submit Blocked
						</span>
					{/if}
				</div>
				<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
					<MetricCard
						label="Proposed CVaR 95%"
						value={fmtSimBps(simulationResult.proposed_cvar_95_3m)}
						sublabel="3-month horizon"
						status={simulationResult.within_limit ? undefined : "breach"}
					/>
					<MetricCard
						label="CVaR Utilization"
						value={fmtSimPct(simulationResult.cvar_utilization_pct)}
						sublabel="of limit"
						status={
							simulationResult.cvar_utilization_pct != null &&
							parseFloat(String(simulationResult.cvar_utilization_pct)) > 1
								? "breach"
								: simulationResult.cvar_utilization_pct != null &&
								  parseFloat(String(simulationResult.cvar_utilization_pct)) > 0.8
								? "warn"
								: undefined
						}
					/>
					<MetricCard
						label="CVaR Delta vs Current"
						value={fmtSimBps(simulationResult.cvar_delta_vs_current)}
						sublabel="change from current"
					/>
					<MetricCard
						label="CVaR Limit"
						value={fmtSimBps(simulationResult.cvar_limit)}
						sublabel="hard limit"
					/>
				</div>

				<!-- Warnings from simulation -->
				{#if simulationResult.warnings.length > 0}
					<div class="mt-4 rounded-md border border-(--netz-status-warning,#f59e0b) bg-(--netz-status-warning,#f59e0b)/10 p-3">
						<p class="mb-1 text-xs font-semibold uppercase tracking-wider text-(--netz-status-warning,#f59e0b)">Warnings</p>
						<ul class="space-y-1">
							{#each simulationResult.warnings as warning, i (i)}
								<li class="text-sm text-(--netz-text-primary)">• {warning}</li>
							{/each}
						</ul>
					</div>
				{/if}

				<!-- Block message when limit exceeded -->
				{#if !simulationResult.within_limit}
					<p class="mt-3 text-sm font-medium text-(--netz-status-error)">
						This allocation exceeds the CVaR limit. Adjust weights before submitting.
					</p>
				{/if}
			</div>
		{/if}
	{/if}

	<!-- Tactical View -->
	{#if activeTab === "tactical"}
		{#if tactical.length > 0}
			<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-5">
				<div class="mb-4 flex items-center justify-between">
					<h3 class="text-sm font-semibold text-(--netz-text-primary)">Tactical Positions</h3>
					{#if !editingTactical}
						<Button size="sm" variant="outline" onclick={startEditingTactical}>Edit</Button>
					{:else}
						<div class="flex gap-2">
							<Button size="sm" variant="outline" onclick={() => editingTactical = false}>Cancel</Button>
							<ActionButton size="sm" onclick={handleSaveTacticalClick} loading={savingTactical} loadingText="Saving...">
								Save
							</ActionButton>
						</div>
					{/if}
				</div>
				<div class="space-y-3">
					{#each tactical as pos (pos.block)}
						<div class="grid gap-3 rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-4 py-3 lg:grid-cols-[minmax(0,1.5fr)_140px_120px] lg:items-center">
							<div class="space-y-2">
								<span class="text-sm text-(--netz-text-primary)">{pos.block}</span>
								<div class="space-y-1">
									<div class="flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-(--netz-text-muted)">
										<span>Conviction</span>
										<span>{convictionLabel(pos.conviction)}</span>
									</div>
									<div class="h-2 overflow-hidden rounded-full bg-(--netz-surface-inset)">
										<div class="h-full rounded-full bg-(--netz-border-accent)" style:width={convictionWidth(pos.conviction)}></div>
									</div>
								</div>
							</div>
							<div class="text-xs text-(--netz-text-muted)">
								{#if pos.conviction !== null}
									Signal strength {formatNumber(pos.conviction, 0, "en-US")} / 5
								{:else}
									No conviction score
								{/if}
							</div>
							<div class="flex items-center justify-end gap-3">
								{#if editingTactical}
									<Input
										type="number"
										class="w-20 text-right"
										bind:value={editTactical[pos.block]}
										step="0.1"
									/>
								{:else}
									<span class="font-medium {pos.overweight >= 0 ? 'text-(--netz-success,#22c55e)' : 'text-(--netz-danger,#ef4444)'}">
										{formatPercent(pos.overweight, 1, "en-US", true)}
									</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<EmptyState title="No Tactical Positions" message="No active tactical overweights." />
		{/if}
	{/if}

	<!-- Effective View -->
	{#if activeTab === "effective"}
		{#if effective.length > 0}
			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-5">
					<div class="mb-4 flex items-center justify-between">
						<h3 class="text-sm font-semibold text-(--netz-text-primary)">Effective Allocation</h3>
						<span class="text-xs text-(--netz-text-muted)">
							Total: {formatPercent(totalWeight, 1, "en-US")}
						</span>
					</div>
					<div class="space-y-3">
						{#each effective as row (row.block)}
							<div class="flex items-center justify-between">
								<span class="text-sm text-(--netz-text-primary)">{row.block}</span>
								<div class="flex items-center gap-2 text-xs">
									<span class="text-(--netz-text-muted)">
										{formatPercent(row.strategic_weight, 1, "en-US")}
									</span>
									{#if row.tactical_overweight !== 0}
										<span class="{row.tactical_overweight >= 0 ? 'text-(--netz-success,#22c55e)' : 'text-(--netz-danger,#ef4444)'}">
											{formatPercent(row.tactical_overweight, 1, "en-US", true)}
										</span>
									{/if}
									<span class="font-medium text-(--netz-text-primary)">
										= {formatPercent(row.effective_weight, 1, "en-US")}
									</span>
								</div>
							</div>
						{/each}
					</div>
				</div>
				<div class="rounded-lg border border-(--netz-border) bg-(--netz-surface-elevated) p-5">
					<h3 class="mb-4 text-sm font-semibold text-(--netz-text-primary)">Distribution</h3>
					<div class="h-64">
						<BarChart data={effectiveChartData} orientation="horizontal" />
					</div>
				</div>
			</div>
		{:else}
			<EmptyState title="No Allocation Data" message="Effective allocation will appear once strategic weights are set." />
		{/if}
	{/if}

		{/snippet}
	</PageTabs>
</div>

<!-- Governed submit: ConsequenceDialog with mandatory rationale -->
<ConsequenceDialog
	bind:open={showConfirmDialog}
	title="Confirm Strategic Allocation Change"
	impactSummary="This will update the strategic weights for the {activeProfile} profile. The change will affect effective allocation and CVaR calculations for all portfolios using this profile."
	scopeText="Profile: {activeProfile} — affects all model portfolios using this allocation profile."
	requireRationale
	rationaleLabel="Rationale for allocation change"
	rationalePlaceholder="State the investment thesis, market conditions, or committee direction behind this strategic change."
	rationaleMinLength={20}
	confirmLabel="Submit Allocation Change"
	metadata={simulationResult
		? [
				{ label: "Proposed CVaR 95%", value: fmtSimBps(simulationResult.proposed_cvar_95_3m), emphasis: true },
				{ label: "CVaR Utilization", value: fmtSimPct(simulationResult.cvar_utilization_pct), emphasis: true },
				{ label: "CVaR Delta vs Current", value: fmtSimBps(simulationResult.cvar_delta_vs_current) },
				{ label: "Within Limit", value: simulationResult.within_limit ? "Yes" : "No", emphasis: !simulationResult.within_limit },
		  ]
		: []}
	onConfirm={confirmSaveStrategic}
	onCancel={() => showConfirmDialog = false}
>
	{#snippet consequenceList()}
		<ul class="space-y-1.5">
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>This will update the strategic allocation for <strong class="text-(--netz-text-primary)">{activeProfile}</strong></span>
			</li>
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>Affects all portfolios using this profile</span>
			</li>
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>CVaR recalculation will be triggered</span>
			</li>
		</ul>
	{/snippet}
</ConsequenceDialog>

<!-- Governed tactical submit: ConsequenceDialog with mandatory rationale -->
<ConsequenceDialog
	bind:open={showTacticalDialog}
	title="Confirm Tactical Allocation Change"
	impactSummary="This will update tactical tilts for the {activeProfile} profile. Tilts adjust effective allocation away from strategic weights."
	scopeText="Profile: {activeProfile} — affects effective allocation for all model portfolios using this profile."
	requireRationale
	rationaleLabel="Rationale for tactical change"
	rationalePlaceholder="State the market signal, CIO directive, or tactical thesis driving this tilt."
	rationaleMinLength={20}
	confirmLabel="Submit Tactical Change"
	onConfirm={confirmSaveTactical}
	onCancel={() => showTacticalDialog = false}
>
	{#snippet consequenceList()}
		<ul class="space-y-1.5">
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>This will update tactical tilts for <strong class="text-(--netz-text-primary)">{activeProfile}</strong></span>
			</li>
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>Affects all portfolios using this profile</span>
			</li>
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>Effective allocation will be recalculated immediately</span>
			</li>
		</ul>
	{/snippet}
</ConsequenceDialog>
