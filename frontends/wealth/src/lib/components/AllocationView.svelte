<!--
  AllocationView — strategic, tactical, and effective views with cross-profile comparison table.
  Hierarchical L1 (Geography) / L2 (Asset Class) grouping.
  Governed save flow: simulate → preview CVaR → ConsequenceDialog with rationale.
-->
<script lang="ts">
	import {
		PageTabs,
		EmptyState,
		Button,
		Input,
		Skeleton,
		formatNumber,
		formatPercent,
		formatBps,
		MetricCard,
		ConsequenceDialog,
	} from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import AllocationTable from "./allocation/AllocationTable.svelte";
	import type { BlockMeta, AllocationRow as TableAllocationRow } from "./allocation/types";

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

	type StrategicRow = {
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

	// ── Profile & Block state ──
	const profiles = ["conservative", "moderate", "growth"];
	const profileLabels: Record<string, string> = {
		conservative: "Conservative",
		moderate: "Moderate",
		growth: "Growth",
	};

	let blocks = $state<BlockMeta[]>([]);
	let loading = $state(true);

	// All profiles' data fetched in parallel
	let strategicByProfile = $state<Record<string, StrategicRow[]>>({});
	let tacticalByProfile = $state<Record<string, TacticalPosition[]>>({});
	let effectiveByProfile = $state<Record<string, EffectiveRow[]>>({});

	// For editing, we work on a single profile
	// svelte-ignore state_referenced_locally
	let editingProfile = $state<string | null>(null);

	type Tab = "strategic" | "tactical" | "effective";
	const tabs: { value: Tab; label: string }[] = [
		{ value: "strategic", label: "Strategic" },
		{ value: "tactical", label: "Tactical" },
		{ value: "effective", label: "Effective" },
	];

	// ── Cross-profile table data transforms ──
	let strategicTableData = $derived.by((): Record<string, TableAllocationRow[]> => {
		const result: Record<string, TableAllocationRow[]> = {};
		for (const p of profiles) {
			result[p] = (strategicByProfile[p] ?? []).map((r) => ({
				block_id: r.block,
				weight: r.weight,
			}));
		}
		return result;
	});

	let tacticalTableData = $derived.by((): Record<string, TableAllocationRow[]> => {
		const result: Record<string, TableAllocationRow[]> = {};
		for (const p of profiles) {
			result[p] = (tacticalByProfile[p] ?? []).map((r) => ({
				block_id: r.block,
				weight: r.overweight,
			}));
		}
		return result;
	});

	let effectiveTableData = $derived.by((): Record<string, TableAllocationRow[]> => {
		const result: Record<string, TableAllocationRow[]> = {};
		for (const p of profiles) {
			result[p] = (effectiveByProfile[p] ?? []).map((r) => ({
				block_id: r.block,
				weight: r.effective_weight,
			}));
		}
		return result;
	});

	// ── Fetch all profiles in parallel ──
	async function fetchAllData() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);

			// Fetch blocks metadata + all 3 profiles × 3 tabs in parallel
			const [blocksRes, ...profileResults] = await Promise.allSettled([
				api.get("/blended-benchmarks/blocks"),
				...profiles.flatMap((p) => [
					api.get(`/allocation/${p}/strategic`),
					api.get(`/allocation/${p}/tactical`),
					api.get(`/allocation/${p}/effective`),
				]),
			]);

			blocks = blocksRes.status === "fulfilled" ? (blocksRes.value as BlockMeta[]) : [];

			// Map results back to profiles (3 results per profile: strategic, tactical, effective)
			for (let i = 0; i < profiles.length; i++) {
				const p = profiles[i]!;
				const sIdx = i * 3;
				const sRes = profileResults[sIdx]!;
				const tRes = profileResults[sIdx + 1]!;
				const eRes = profileResults[sIdx + 2]!;
				strategicByProfile[p] = sRes.status === "fulfilled" ? (sRes.value as StrategicRow[]) : [];
				tacticalByProfile[p] = tRes.status === "fulfilled" ? (tRes.value as TacticalPosition[]) : [];
				effectiveByProfile[p] = eRes.status === "fulfilled" ? (eRes.value as EffectiveRow[]) : [];
			}
		} finally {
			loading = false;
		}
	}

	// ── Summary metrics ──
	let totalStrategicBlocks = $derived(
		new Set(profiles.flatMap((p) => (strategicByProfile[p] ?? []).map((r) => r.block))).size,
	);

	let totalTacticalTilts = $derived(
		profiles.reduce((sum, p) => sum + (tacticalByProfile[p]?.length ?? 0), 0),
	);

	// ── Edit Mode (per-profile) ──
	let editing = $state(false);
	let saving = $state(false);
	let editError = $state<string | null>(null);
	let editWeights = $state<Record<string, number>>({});

	function startEditing(profile: string) {
		const rows = strategicByProfile[profile] ?? [];
		editWeights = {};
		for (const row of rows) {
			editWeights[row.block] = row.weight * 100;
		}
		editError = null;
		editing = true;
		editingProfile = profile;
	}

	function cancelEditing() {
		editing = false;
		editingProfile = null;
		editError = null;
	}

	let editTotal = $derived(
		Object.values(editWeights).reduce((sum, v) => sum + v, 0),
	);
	let editDelta = $derived(Math.abs(editTotal - 100));
	let editValid = $derived(editDelta < 0.1);

	function fmtPercentPoint(value: number, decimals = 1): string {
		return `${formatNumber(value, decimals, "en-US")}%`;
	}

	function fmtSignedPercentPoint(value: number, decimals = 1): string {
		const formatted = formatNumber(value, decimals, "en-US");
		return value >= 0 ? `+${formatted}%` : `${formatted}%`;
	}

	// Tactical edit (per-profile)
	let editTactical = $state<Record<string, number>>({});
	let editingTactical = $state(false);
	let savingTactical = $state(false);

	function startEditingTactical(profile: string) {
		const positions = tacticalByProfile[profile] ?? [];
		editTactical = {};
		for (const pos of positions) {
			editTactical[pos.block] = pos.overweight * 100;
		}
		editingTactical = true;
		editingProfile = profile;
	}

	// ── Simulation + Governance ──
	let simulationResult = $state<SimulationResult | null>(null);
	let simulating = $state(false);
	let simError = $state<string | null>(null);
	let showConfirmDialog = $state(false);
	let showTacticalDialog = $state(false);

	function handleSaveTacticalClick() {
		showTacticalDialog = true;
	}

	async function confirmSaveTactical({ rationale }: { rationale?: string }) {
		if (!editingProfile) return;
		savingTactical = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const tilts: Record<string, number> = {};
			for (const [block, w] of Object.entries(editTactical)) {
				tilts[block] = w / 100;
			}
			await api.put(`/allocation/${editingProfile}/tactical`, {
				tilts,
				...(rationale ? { rationale } : {}),
			});
			editingTactical = false;
			editingProfile = null;
			await fetchAllData();
		} catch (e) {
			editError =
				e instanceof Error ? e.message : "Failed to save tactical allocation";
		} finally {
			savingTactical = false;
		}
	}

	async function runSimulation(): Promise<boolean> {
		if (!editValid || !editingProfile) return false;
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
				`/allocation/${editingProfile}/simulate`,
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

	async function handleSaveStrategicClick() {
		const withinLimit = await runSimulation();
		if (!withinLimit) return;
		showConfirmDialog = true;
	}

	async function confirmSaveStrategic({ rationale }: { rationale?: string }) {
		if (!editValid || !editingProfile) return;
		saving = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const weights: Record<string, number> = {};
			for (const [block, w] of Object.entries(editWeights)) {
				weights[block] = w / 100;
			}
			await api.put(`/allocation/${editingProfile}/strategic`, {
				weights,
				...(rationale ? { rationale } : {}),
			});
			editing = false;
			editingProfile = null;
			simulationResult = null;
			await fetchAllData();
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to save allocation";
		} finally {
			saving = false;
		}
	}

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

	// Load on mount
	fetchAllData();
</script>

<div class="space-y-6">
	{#if loading}
		<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
			{#each Array(3) as _}
				<Skeleton class="h-24 rounded-xl" />
			{/each}
		</div>
		<Skeleton class="h-64 rounded-xl" />
	{:else}
		<!-- Summary metrics -->
		<div class="grid gap-4 md:grid-cols-3">
			<MetricCard label="Allocation Blocks" value={String(totalStrategicBlocks)} sublabel="Configured across profiles" />
			<MetricCard label="Active Profiles" value={String(profiles.length)} sublabel="Conservative · Moderate · Growth" />
			<MetricCard label="Tactical Tilts" value={String(totalTacticalTilts)} sublabel="Active across all profiles" />
		</div>

		{#if editError}
			<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{editError}
				<button class="ml-2 underline" onclick={() => (editError = null)}>dismiss</button>
			</div>
		{/if}

		<PageTabs {tabs} defaultTab="strategic">
			{#snippet children(activeTab)}
				<!-- ═══════════ STRATEGIC ═══════════ -->
				{#if activeTab === "strategic"}
					{#if !editing}
						<div class="av-tab-header">
							<p class="av-tab-desc">IC-approved strategic weights by geography and asset class.</p>
							<div class="av-edit-btns">
								{#each profiles as profile (profile)}
									<Button size="sm" variant="outline" onclick={() => startEditing(profile)}>
										Edit {profileLabels[profile]}
									</Button>
								{/each}
							</div>
						</div>
						<AllocationTable
							{blocks}
							data={strategicTableData}
							{profiles}
							{profileLabels}
							mode="strategic"
						/>
					{:else if editingProfile}
						<!-- Per-profile editor -->
						<div class="av-editor">
							<div class="av-editor-header">
								<h3 class="av-editor-title">Editing: {profileLabels[editingProfile]}</h3>
								<div class="flex items-center gap-2">
									<span class="text-xs {editValid ? 'text-(--netz-success,#22c55e)' : 'text-(--netz-danger,#ef4444)'}">
										Total: {fmtPercentPoint(editTotal)}
										{editValid ? "" : `(${fmtSignedPercentPoint(editTotal - 100)})`}
									</span>
									<Button size="sm" variant="outline" onclick={cancelEditing}>Cancel</Button>
									<ActionButton
										size="sm"
										onclick={handleSaveStrategicClick}
										loading={simulating || saving}
										loadingText={simulating ? "Simulating..." : "Saving..."}
										disabled={!editValid}
									>
										Review & Save
									</ActionButton>
								</div>
							</div>
							<div class="av-editor-rows">
								{#each strategicByProfile[editingProfile] ?? [] as row (row.block)}
									{@const blockWeight = editWeights[row.block] ?? 0}
									{@const belowMin = row.min_weight !== null && blockWeight < row.min_weight * 100}
									{@const aboveMax = row.max_weight !== null && blockWeight > row.max_weight * 100}
									{@const outOfBounds = belowMin || aboveMax}
									<div class="av-editor-row">
										<span class="av-editor-block">{row.block}</span>
										{#if row.min_weight !== null && row.max_weight !== null}
											<span class="av-editor-bounds">
												[{formatPercent(row.min_weight, 0, "en-US")}–{formatPercent(row.max_weight, 0, "en-US")}]
											</span>
										{/if}
										<Input
											type="number"
											class="w-20 text-right {outOfBounds ? 'border-(--netz-danger)' : ''}"
											bind:value={editWeights[row.block]}
											min={row.min_weight !== null ? row.min_weight * 100 : 0}
											max={row.max_weight !== null ? row.max_weight * 100 : 100}
											step="0.1"
										/>
										{#if outOfBounds}
											<span class="text-xs text-(--netz-danger)">{belowMin ? "below min" : "above max"}</span>
										{/if}
									</div>
								{/each}
							</div>
						</div>

						{#if simError}
							<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
								{simError}
								<button class="ml-2 underline" onclick={() => (simError = null)}>dismiss</button>
							</div>
						{/if}

						{#if simulationResult}
							<div class="rounded-lg border {simulationResult.within_limit ? 'border-(--netz-border)' : 'border-(--netz-status-error)'} bg-(--netz-surface-elevated) p-5">
								<div class="mb-3 flex items-center justify-between">
									<h3 class="text-sm font-semibold text-(--netz-text-primary)">CVaR Simulation Preview</h3>
									{#if simulationResult.within_limit}
										<span class="inline-flex items-center gap-1 rounded-full bg-(--netz-success,#22c55e)/15 px-2 py-0.5 text-xs font-medium text-(--netz-success,#22c55e)">Within Limit</span>
									{:else}
										<span class="inline-flex items-center gap-1 rounded-full bg-(--netz-status-error)/15 px-2 py-0.5 text-xs font-medium text-(--netz-status-error)">Exceeds CVaR Limit</span>
									{/if}
								</div>
								<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
									<MetricCard label="Proposed CVaR 95%" value={fmtSimBps(simulationResult.proposed_cvar_95_3m)} sublabel="3-month horizon" status={simulationResult.within_limit ? undefined : "breach"} />
									<MetricCard
										label="CVaR Utilization"
										value={fmtSimPct(simulationResult.cvar_utilization_pct)}
										sublabel="of limit"
									/>
									<MetricCard label="CVaR Delta" value={fmtSimBps(simulationResult.cvar_delta_vs_current)} sublabel="change from current" />
									<MetricCard label="CVaR Limit" value={fmtSimBps(simulationResult.cvar_limit)} sublabel="hard limit" />
								</div>
								{#if !simulationResult.within_limit}
									<p class="mt-3 text-sm font-medium text-(--netz-status-error)">
										This allocation exceeds the CVaR limit. Adjust weights before submitting.
									</p>
								{/if}
							</div>
						{/if}
					{/if}
				{/if}

				<!-- ═══════════ TACTICAL ═══════════ -->
				{#if activeTab === "tactical"}
					{#if !editingTactical}
						<div class="av-tab-header">
							<p class="av-tab-desc">Active tactical overweights — deviations from strategic weights. <span class="text-(--netz-success)">Green</span> = overweight, <span class="text-(--netz-danger)">red</span> = underweight.</p>
							<div class="av-edit-btns">
								{#each profiles as profile (profile)}
									<Button size="sm" variant="outline" onclick={() => startEditingTactical(profile)}>
										Edit {profileLabels[profile]}
									</Button>
								{/each}
							</div>
						</div>
						<AllocationTable
							{blocks}
							data={tacticalTableData}
							{profiles}
							{profileLabels}
							mode="tactical"
						/>
					{:else if editingProfile}
						<div class="av-editor">
							<div class="av-editor-header">
								<h3 class="av-editor-title">Tactical Tilts: {profileLabels[editingProfile]}</h3>
								<div class="flex gap-2">
									<Button size="sm" variant="outline" onclick={() => { editingTactical = false; editingProfile = null; }}>Cancel</Button>
									<ActionButton size="sm" onclick={handleSaveTacticalClick} loading={savingTactical} loadingText="Saving...">
										Save
									</ActionButton>
								</div>
							</div>
							<div class="av-editor-rows">
								{#each tacticalByProfile[editingProfile] ?? [] as pos (pos.block)}
									<div class="av-editor-row">
										<span class="av-editor-block">{pos.block}</span>
										<Input type="number" class="w-20 text-right" bind:value={editTactical[pos.block]} step="0.1" />
									</div>
								{/each}
							</div>
						</div>
					{/if}
				{/if}

				<!-- ═══════════ EFFECTIVE ═══════════ -->
				{#if activeTab === "effective"}
					<div class="av-tab-header">
						<p class="av-tab-desc">Combined allocation: strategic weight + tactical tilt = effective exposure.</p>
					</div>
					<AllocationTable
						{blocks}
						data={effectiveTableData}
						{profiles}
						{profileLabels}
						mode="effective"
					/>
				{/if}
			{/snippet}
		</PageTabs>
	{/if}
</div>

<!-- Governed strategic submit -->
<ConsequenceDialog
	bind:open={showConfirmDialog}
	title="Confirm Strategic Allocation Change"
	impactSummary="This will update the strategic weights for the {editingProfile ?? ''} profile. The change will affect effective allocation and CVaR calculations."
	scopeText="Profile: {editingProfile ?? ''} — affects all model portfolios using this allocation profile."
	requireRationale
	rationaleLabel="Rationale for allocation change"
	rationalePlaceholder="State the investment thesis, market conditions, or committee direction behind this strategic change."
	rationaleMinLength={20}
	confirmLabel="Submit Allocation Change"
	metadata={simulationResult
		? [
				{ label: "Proposed CVaR 95%", value: fmtSimBps(simulationResult.proposed_cvar_95_3m), emphasis: true },
				{ label: "CVaR Utilization", value: fmtSimPct(simulationResult.cvar_utilization_pct), emphasis: true },
				{ label: "CVaR Delta", value: fmtSimBps(simulationResult.cvar_delta_vs_current) },
				{ label: "Within Limit", value: simulationResult.within_limit ? "Yes" : "No", emphasis: !simulationResult.within_limit },
			]
		: []}
	onConfirm={confirmSaveStrategic}
	onCancel={() => (showConfirmDialog = false)}
>
	{#snippet consequenceList()}
		<ul class="space-y-1.5">
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>This will update the strategic allocation for <strong class="text-(--netz-text-primary)">{editingProfile}</strong></span>
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

<!-- Governed tactical submit -->
<ConsequenceDialog
	bind:open={showTacticalDialog}
	title="Confirm Tactical Allocation Change"
	impactSummary="This will update tactical tilts for the {editingProfile ?? ''} profile. Tilts adjust effective allocation away from strategic weights."
	scopeText="Profile: {editingProfile ?? ''} — affects effective allocation for all model portfolios using this profile."
	requireRationale
	rationaleLabel="Rationale for tactical change"
	rationalePlaceholder="State the market signal, CIO directive, or tactical thesis driving this tilt."
	rationaleMinLength={20}
	confirmLabel="Submit Tactical Change"
	onConfirm={confirmSaveTactical}
	onCancel={() => (showTacticalDialog = false)}
>
	{#snippet consequenceList()}
		<ul class="space-y-1.5">
			<li class="flex items-start gap-2">
				<span class="mt-0.5 text-(--netz-warning)">&#9679;</span>
				<span>This will update tactical tilts for <strong class="text-(--netz-text-primary)">{editingProfile}</strong></span>
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

<style>
	.av-tab-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 16px;
		flex-wrap: wrap;
	}

	.av-tab-desc {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		margin: 0;
	}

	.av-edit-btns {
		display: flex;
		gap: 6px;
		flex-shrink: 0;
	}

	/* Editor */
	.av-editor {
		border: 1px solid var(--netz-border-accent);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
	}

	.av-editor-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 12px 16px;
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
		flex-wrap: wrap;
	}

	.av-editor-title {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		margin: 0;
	}

	.av-editor-rows {
		padding: 12px 16px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.av-editor-row {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.av-editor-block {
		flex: 1;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.av-editor-bounds {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		white-space: nowrap;
	}
</style>
