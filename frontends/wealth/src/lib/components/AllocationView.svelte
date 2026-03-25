<!--
  AllocationView — Figma redesign: profile tabs, KPI row, view sub-tabs,
  hierarchical table (group → block → instruments).
  Governed save flow: simulate → preview CVaR → ConsequenceDialog with rationale.
-->
<script lang="ts">
	import {
		Button,
		formatNumber,
		formatPercent,
		formatBps,
		MetricCard,
		ConsequenceDialog,
		ActionButton,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import { BLOCK_INSTRUMENTS } from "./allocation/BLOCK_INSTRUMENTS";
	import type { BlockMeta } from "./allocation/types";

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

	// ── Profile state ──
	type Profile = "conservative" | "moderate" | "growth";
	type ViewTab = "target" | "adjustments" | "effective";

	const PROFILES: { id: Profile; label: string }[] = [
		{ id: "conservative", label: "Conservative Profile" },
		{ id: "moderate", label: "Moderate Profile" },
		{ id: "growth", label: "Growth Profile" },
	];

	const VIEW_TABS: { id: ViewTab; label: string }[] = [
		{ id: "target", label: "Long-term Target" },
		{ id: "adjustments", label: "Active Adjustments" },
		{ id: "effective", label: "Final Portfolio" },
	];

	let activeProfile = $state<Profile>("moderate");
	let activeView = $state<ViewTab>("effective");
	let loading = $state(true);

	// ── Backend data ──
	type StrategicRow = {
		block: string;
		weight: number;
		min_weight: number | null;
		max_weight: number | null;
	};
	type TacticalRow = {
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

	let blocks = $state<BlockMeta[]>([]);
	let strategic = $state<StrategicRow[]>([]);
	let tactical = $state<TacticalRow[]>([]);
	let effective = $state<EffectiveRow[]>([]);

	async function fetchProfile(profile: Profile) {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const [b, s, t, e] = await Promise.all([
				api.get<BlockMeta[]>("/blended-benchmarks/blocks"),
				api.get<StrategicRow[]>(`/allocation/${profile}/strategic`),
				api.get<TacticalRow[]>(`/allocation/${profile}/tactical`),
				api.get<EffectiveRow[]>(`/allocation/${profile}/effective`),
			]);
			blocks = b;
			strategic = s;
			tactical = t;
			effective = e;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchProfile(activeProfile);
	});

	// ── KPI computation ──
	let assetCategoryCount = $derived(strategic.filter((r) => r.weight > 0).length);

	let activeAdjustmentCount = $derived(
		tactical.filter((r) => Math.abs(r.overweight) > 0.001).length,
	);

	let topOverweight = $derived.by(() => {
		if (tactical.length === 0) return null;
		const sorted = [...tactical].sort((a, b) => b.overweight - a.overweight);
		const top = sorted[0];
		if (!top || top.overweight <= 0) return null;
		const blockMeta = blocks.find((b) => b.block_id === top.block);
		return {
			name: blockMeta?.display_name ?? top.block,
			overweight: top.overweight,
		};
	});

	// ── Table data building ──
	const GROUP_ORDER = ["equity", "fixed_income", "bond", "alternatives", "cash"];
	const GROUP_LABELS: Record<string, string> = {
		equity: "EQUITIES",
		fixed_income: "FIXED INCOME",
		bond: "FIXED INCOME",
		alternatives: "ALTERNATIVES",
		cash: "CASH & EQUIVALENTS",
	};

	type TableRow =
		| { kind: "group"; label: string }
		| {
				kind: "block";
				block_id: string;
				display_name: string;
				target: number;
				adjustment: number;
				final: number;
		  }
		| {
				kind: "instrument";
				ticker: string;
				name: string;
				target: number;
				adjustment: number;
				final: number;
		  };

	let tableRows = $derived.by((): TableRow[] => {
		if (blocks.length === 0 || strategic.length === 0) return [];

		const tacMap: Record<string, number> = {};
		for (const t of tactical) tacMap[t.block] = t.overweight;

		const strMap: Record<string, number> = {};
		for (const s of strategic) strMap[s.block] = s.weight;

		const effMap: Record<string, number> = {};
		for (const e of effective) effMap[e.block] = e.effective_weight;

		// Group blocks by asset class
		const groups: Record<string, BlockMeta[]> = {};
		for (const b of blocks) {
			const ac = b.asset_class?.toLowerCase() ?? "other";
			if (!groups[ac]) groups[ac] = [];
			groups[ac].push(b);
		}

		const rows: TableRow[] = [];
		const seenGroups = new Set<string>();

		const orderedKeys = [
			...GROUP_ORDER.filter((k) => groups[k]),
			...Object.keys(groups).filter((k) => !GROUP_ORDER.includes(k)),
		];

		for (const key of orderedKeys) {
			const groupBlocks = groups[key] ?? [];
			const label = GROUP_LABELS[key] ?? key.toUpperCase();

			if (!seenGroups.has(label)) {
				seenGroups.add(label);
				rows.push({ kind: "group", label });
			}

			for (const b of groupBlocks) {
				const str = strMap[b.block_id] ?? 0;
				const tac = tacMap[b.block_id] ?? 0;
				const eff = effMap[b.block_id] ?? str + tac;

				rows.push({
					kind: "block",
					block_id: b.block_id,
					display_name: b.display_name,
					target: str,
					adjustment: tac,
					final: eff,
				});

				const instruments = BLOCK_INSTRUMENTS[b.block_id] ?? [];
				for (const inst of instruments) {
					rows.push({
						kind: "instrument",
						ticker: inst.ticker,
						name: inst.name,
						target: str * inst.weight,
						adjustment: tac * inst.weight,
						final: eff * inst.weight,
					});
				}
			}
		}

		return rows;
	});

	// ── Formatting helpers ──
	function fmtPct(v: number): string {
		return `${formatNumber(v * 100, 1, "en-US")}%`;
	}

	function fmtAdj(v: number): string {
		if (Math.abs(v) < 0.0005) return "—";
		const sign = v > 0 ? "+" : "";
		return `${sign}${formatNumber(v * 100, 1, "en-US")}%`;
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

	// ── Strategic edit state ──
	let editing = $state(false);
	let editWeights = $state<Record<string, number>>({});
	let editError = $state<string | null>(null);
	let saving = $state(false);
	let simulating = $state(false);
	let simulationResult = $state<SimulationResult | null>(null);
	let simError = $state<string | null>(null);
	let showConfirmDialog = $state(false);

	function startEditing() {
		editWeights = {};
		for (const row of strategic) editWeights[row.block] = row.weight * 100;
		editError = null;
		simError = null;
		simulationResult = null;
		editing = true;
	}

	function cancelEditing() {
		editing = false;
		editError = null;
		simError = null;
		simulationResult = null;
	}

	let editTotal = $derived(Object.values(editWeights).reduce((s, v) => s + v, 0));
	let editValid = $derived(Math.abs(editTotal - 100) < 0.1);

	async function handleSaveClick() {
		if (!editValid) return;
		simulating = true;
		simError = null;
		simulationResult = null;
		try {
			const api = createClientApiClient(getToken);
			const weights: Record<string, number> = {};
			for (const [b, w] of Object.entries(editWeights)) weights[b] = w / 100;
			const result = await api.post<SimulationResult>(
				`/allocation/${activeProfile}/simulate`,
				{ weights, rationale: "pre-save simulation" },
			);
			simulationResult = result;
			if (result.within_limit) {
				showConfirmDialog = true;
			}
		} catch (e) {
			simError = e instanceof Error ? e.message : "Simulation failed";
		} finally {
			simulating = false;
		}
	}

	async function confirmSave({ rationale }: { rationale?: string }) {
		saving = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const weights: Record<string, number> = {};
			for (const [b, w] of Object.entries(editWeights)) weights[b] = w / 100;
			await api.put(`/allocation/${activeProfile}/strategic`, {
				weights,
				...(rationale ? { rationale } : {}),
			});
			editing = false;
			simulationResult = null;
			await fetchProfile(activeProfile);
		} catch (e) {
			editError = e instanceof Error ? e.message : "Save failed";
		} finally {
			saving = false;
		}
	}

	// ── Tactical edit state ──
	let editingTactical = $state(false);
	let editTactical = $state<Record<string, number>>({});
	let savingTactical = $state(false);
	let showTacticalDialog = $state(false);

	function startEditingTactical() {
		editTactical = {};
		for (const pos of tactical) editTactical[pos.block] = pos.overweight * 100;
		editError = null;
		editingTactical = true;
	}

	function cancelEditingTactical() {
		editingTactical = false;
		editError = null;
	}

	function handleSaveTacticalClick() {
		showTacticalDialog = true;
	}

	async function confirmSaveTactical({ rationale }: { rationale?: string }) {
		savingTactical = true;
		editError = null;
		try {
			const api = createClientApiClient(getToken);
			const tilts: Record<string, number> = {};
			for (const [block, w] of Object.entries(editTactical)) tilts[block] = w / 100;
			await api.put(`/allocation/${activeProfile}/tactical`, {
				tilts,
				...(rationale ? { rationale } : {}),
			});
			editingTactical = false;
			await fetchProfile(activeProfile);
		} catch (e) {
			editError = e instanceof Error ? e.message : "Failed to save tactical allocation";
		} finally {
			savingTactical = false;
		}
	}
</script>

<div class="alloc">
	<!-- PROFILE TABS -->
	<div class="alloc-profile-tabs">
		{#each PROFILES as p (p.id)}
			<button
				class="alloc-profile-tab"
				class:alloc-profile-tab--active={activeProfile === p.id}
				onclick={() => {
					activeProfile = p.id;
					editing = false;
					editingTactical = false;
				}}
			>{p.label}</button>
		{/each}
	</div>

	{#if loading}
		<div class="alloc-loading">Loading…</div>
	{:else}
		<!-- KPI ROW -->
		<div class="alloc-kpis">
			<div class="alloc-kpi">
				<span class="alloc-kpi-heading">ASSET CATEGORIES</span>
				<span class="alloc-kpi-value">{assetCategoryCount}</span>
				<span class="alloc-kpi-label">core building blocks</span>
			</div>
			<div class="alloc-kpi">
				<span class="alloc-kpi-heading">ACTIVE ADJUSTMENTS</span>
				<span class="alloc-kpi-value">{activeAdjustmentCount}</span>
				<span class="alloc-kpi-label">market deviations</span>
			</div>
			<div class="alloc-kpi">
				<span class="alloc-kpi-heading">TOP OVERWEIGHT</span>
				{#if topOverweight}
					<span class="alloc-kpi-value">{topOverweight.name}</span>
					<span class="alloc-kpi-overweight">↗ +{formatNumber(topOverweight.overweight * 100, 1, "en-US")}% vs Target</span>
				{:else}
					<span class="alloc-kpi-value">—</span>
				{/if}
			</div>
		</div>

		<!-- VIEW TABS + ACTIONS -->
		<div class="alloc-view-bar">
			<div class="alloc-view-tabs">
				{#each VIEW_TABS as vt (vt.id)}
					<button
						class="alloc-view-tab"
						class:alloc-view-tab--active={activeView === vt.id}
						onclick={() => {
							activeView = vt.id;
							editing = false;
							editingTactical = false;
						}}
					>{vt.label}</button>
				{/each}
			</div>
			<div class="alloc-view-actions">
				{#if !editing && !editingTactical && activeView === "target"}
					<Button size="sm" variant="outline" onclick={startEditing}>Edit Weights</Button>
				{/if}
				{#if !editing && !editingTactical && activeView === "adjustments"}
					<Button size="sm" variant="outline" onclick={startEditingTactical}>Edit Tilts</Button>
				{/if}
				{#if editing}
					<span class="alloc-edit-total" class:alloc-edit-total--ok={editValid}>
						Total: {formatNumber(editTotal, 1, "en-US")}%
					</span>
					<Button size="sm" variant="outline" onclick={cancelEditing}>Cancel</Button>
					<ActionButton
						size="sm"
						onclick={handleSaveClick}
						loading={simulating || saving}
						loadingText={simulating ? "Simulating…" : "Saving…"}
						disabled={!editValid}
					>Review & Save</ActionButton>
				{/if}
				{#if editingTactical}
					<Button size="sm" variant="outline" onclick={cancelEditingTactical}>Cancel</Button>
					<ActionButton
						size="sm"
						onclick={handleSaveTacticalClick}
						loading={savingTactical}
						loadingText="Saving…"
					>Save Tilts</ActionButton>
				{/if}
			</div>
		</div>

		{#if editError}
			<div class="alloc-error">{editError}</div>
		{/if}

		{#if simError}
			<div class="alloc-error">{simError}</div>
		{/if}

		{#if simulationResult && !simulationResult.within_limit}
			<div class="alloc-sim-preview">
				<div class="alloc-sim-header">
					<h3 class="alloc-sim-title">CVaR Simulation Preview</h3>
					<span class="alloc-sim-badge alloc-sim-badge--breach">Exceeds CVaR Limit</span>
				</div>
				<div class="alloc-sim-grid">
					<MetricCard label="Proposed CVaR 95%" value={fmtSimBps(simulationResult.proposed_cvar_95_3m)} sublabel="3-month horizon" status="breach" />
					<MetricCard label="CVaR Utilization" value={fmtSimPct(simulationResult.cvar_utilization_pct)} sublabel="of limit" />
					<MetricCard label="CVaR Delta" value={fmtSimBps(simulationResult.cvar_delta_vs_current)} sublabel="change from current" />
					<MetricCard label="CVaR Limit" value={fmtSimBps(simulationResult.cvar_limit)} sublabel="hard limit" />
				</div>
				<p class="alloc-sim-warning">This allocation exceeds the CVaR limit. Adjust weights before submitting.</p>
			</div>
		{/if}

		<!-- TABLE -->
		<div class="alloc-table-wrap">
			<table class="alloc-table">
				<thead>
					<tr>
						<th class="alloc-th">ASSET CLASS / COMPONENT / INSTRUMENT</th>
						<th class="alloc-th alloc-th--right">TARGET</th>
						<th class="alloc-th alloc-th--right">ADJUSTMENT</th>
						<th class="alloc-th alloc-th--right alloc-th--final">FINAL PORTFOLIO</th>
					</tr>
				</thead>
				<tbody>
					{#each tableRows as row (row.kind === "group" ? `g:${row.label}` : row.kind === "block" ? `b:${row.block_id}` : `i:${row.ticker}`)}
						{#if row.kind === "group"}
							<tr class="alloc-row-group">
								<td colspan="4" class="alloc-td-group">{row.label}</td>
							</tr>
						{:else if row.kind === "block"}
							<tr class="alloc-row-block">
								<td class="alloc-td alloc-td--block">
									{#if editing}
										<div class="alloc-edit-row">
											<span>{row.display_name}</span>
											<input
												type="number"
												class="alloc-edit-input"
												bind:value={editWeights[row.block_id]}
												step="0.1"
												min="0"
												max="100"
											/>
										</div>
									{:else if editingTactical}
										<div class="alloc-edit-row">
											<span>{row.display_name}</span>
											<input
												type="number"
												class="alloc-edit-input"
												bind:value={editTactical[row.block_id]}
												step="0.1"
											/>
										</div>
									{:else}
										{row.display_name}
									{/if}
								</td>
								<td class="alloc-td alloc-td--right">
									{activeView === "adjustments" ? "—" : fmtPct(row.target)}
								</td>
								<td
									class="alloc-td alloc-td--right"
									class:alloc-positive={row.adjustment > 0.0005}
									class:alloc-negative={row.adjustment < -0.0005}
								>
									{activeView === "target" ? "—" : fmtAdj(row.adjustment)}
								</td>
								<td class="alloc-td alloc-td--right alloc-td--final">
									{activeView === "target"
										? fmtPct(row.target)
										: activeView === "adjustments"
											? fmtAdj(row.adjustment)
											: fmtPct(row.final)}
								</td>
							</tr>
						{:else}
							<tr class="alloc-row-instrument">
								<td class="alloc-td alloc-td--instrument">{row.ticker} — {row.name}</td>
								<td class="alloc-td alloc-td--right alloc-td--muted">
									{activeView === "adjustments" ? "—" : fmtPct(row.target)}
								</td>
								<td
									class="alloc-td alloc-td--right alloc-td--muted"
									class:alloc-positive={row.adjustment > 0.0005}
									class:alloc-negative={row.adjustment < -0.0005}
								>
									{activeView === "target" ? "—" : fmtAdj(row.adjustment)}
								</td>
								<td class="alloc-td alloc-td--right alloc-td--muted">
									{activeView === "target"
										? fmtPct(row.target)
										: activeView === "adjustments"
											? fmtAdj(row.adjustment)
											: fmtPct(row.final)}
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<!-- Governed strategic submit -->
<ConsequenceDialog
	bind:open={showConfirmDialog}
	title="Confirm Strategic Allocation Change"
	impactSummary="This will update strategic weights for the {activeProfile} profile."
	scopeText="Profile: {activeProfile} — affects all model portfolios using this allocation profile."
	requireRationale
	rationaleLabel="Rationale for allocation change"
	rationalePlaceholder="State the investment thesis or committee direction behind this change."
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
	onConfirm={confirmSave}
	onCancel={() => (showConfirmDialog = false)}
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

<!-- Governed tactical submit -->
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
	onCancel={() => (showTacticalDialog = false)}
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

<style>
	/* Profile tabs */
	.alloc-profile-tabs {
		display: flex;
		gap: 0;
		border-bottom: 1px solid var(--netz-border-subtle);
		margin-bottom: 0;
	}

	.alloc-profile-tab {
		padding: 14px 24px 12px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		font-size: 14px;
		font-weight: 500;
		color: var(--netz-text-muted);
		cursor: pointer;
		font-family: var(--netz-font-sans);
		transition: color 120ms, border-color 120ms;
		margin-bottom: -1px;
	}

	.alloc-profile-tab:hover {
		color: var(--netz-text-primary);
	}

	.alloc-profile-tab--active {
		color: var(--netz-brand-primary);
		border-bottom-color: var(--netz-brand-primary);
		font-weight: 600;
	}

	/* KPI row */
	.alloc-kpis {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
	}

	.alloc-kpi {
		display: flex;
		flex-direction: column;
		padding: 24px 32px;
		border-right: 1px solid var(--netz-border-subtle);
	}

	.alloc-kpi:last-child {
		border-right: none;
	}

	.alloc-kpi-heading {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--netz-text-muted);
		margin-bottom: 8px;
	}

	.alloc-kpi-value {
		font-size: 22px;
		font-weight: 700;
		color: var(--netz-text-primary);
		line-height: 1.2;
	}

	.alloc-kpi-label {
		font-size: 13px;
		color: var(--netz-text-muted);
		margin-top: 2px;
	}

	.alloc-kpi-overweight {
		font-size: 13px;
		font-weight: 600;
		color: #22c55e;
		margin-top: 4px;
	}

	/* View bar */
	.alloc-view-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 24px 0 0;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
	}

	.alloc-view-tabs {
		display: flex;
	}

	.alloc-view-tab {
		padding: 12px 24px 10px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		font-size: 13px;
		font-weight: 500;
		color: var(--netz-text-muted);
		cursor: pointer;
		font-family: var(--netz-font-sans);
		transition: color 120ms, border-color 120ms;
		margin-bottom: -1px;
	}

	.alloc-view-tab:hover {
		color: var(--netz-text-primary);
	}

	.alloc-view-tab--active {
		color: var(--netz-text-primary);
		border-bottom-color: var(--netz-text-primary);
		font-weight: 600;
	}

	.alloc-view-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.alloc-edit-total {
		font-size: 13px;
		font-weight: 600;
		color: var(--netz-danger, #ef4444);
	}

	.alloc-edit-total--ok {
		color: #22c55e;
	}

	/* Table */
	.alloc-table-wrap {
		overflow-x: auto;
		background: var(--netz-surface-elevated);
	}

	.alloc-table {
		width: 100%;
		border-collapse: collapse;
	}

	.alloc-th {
		padding: 10px 24px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--netz-text-muted);
		text-align: left;
		background: color-mix(in srgb, var(--netz-surface-alt) 50%, transparent);
		border-bottom: 1px solid var(--netz-border-subtle);
		white-space: nowrap;
	}

	.alloc-th--right {
		text-align: right;
	}

	.alloc-th--final {
		color: var(--netz-text-primary);
		font-weight: 800;
	}

	/* Group row */
	.alloc-row-group {
		background: color-mix(in srgb, var(--netz-surface-alt) 60%, transparent);
	}

	.alloc-td-group {
		padding: 8px 24px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--netz-text-muted);
	}

	/* Block row */
	.alloc-row-block {
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.alloc-row-block:last-child {
		border-bottom: none;
	}

	.alloc-td--block {
		padding: 14px 24px;
		font-size: 14px;
		font-weight: 700;
		color: var(--netz-text-primary);
	}

	/* Instrument row */
	.alloc-row-instrument {
		border-bottom: 1px solid color-mix(in srgb, var(--netz-border-subtle) 50%, transparent);
	}

	.alloc-td--instrument {
		padding: 10px 24px 10px 40px;
		font-size: 12px;
		color: var(--netz-text-muted);
	}

	.alloc-td {
		padding: 14px 24px;
		vertical-align: middle;
		font-variant-numeric: tabular-nums;
	}

	.alloc-td--right {
		text-align: right;
	}

	.alloc-td--muted {
		color: var(--netz-text-muted);
	}

	.alloc-td--final {
		font-weight: 900;
		color: var(--netz-text-primary);
	}

	.alloc-positive {
		color: #22c55e;
		font-weight: 600;
	}

	.alloc-negative {
		color: var(--netz-danger, #ef4444);
		font-weight: 600;
	}

	.alloc-loading {
		padding: 48px;
		text-align: center;
		color: var(--netz-text-muted);
	}

	.alloc-error {
		padding: 12px 24px;
		background: color-mix(in srgb, var(--netz-danger, #ef4444) 8%, transparent);
		color: var(--netz-danger, #ef4444);
		font-size: 13px;
	}

	/* Edit input */
	.alloc-edit-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.alloc-edit-input {
		width: 72px;
		padding: 4px 8px;
		text-align: right;
		font-size: 13px;
		border: 1px solid var(--netz-border);
		border-radius: 6px;
		background: var(--netz-surface-alt);
		color: var(--netz-text-primary);
		font-family: var(--netz-font-mono);
	}

	/* Simulation preview (breach) */
	.alloc-sim-preview {
		padding: 20px 24px;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: color-mix(in srgb, var(--netz-danger, #ef4444) 4%, var(--netz-surface-elevated));
	}

	.alloc-sim-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
	}

	.alloc-sim-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--netz-text-primary);
		margin: 0;
	}

	.alloc-sim-badge--breach {
		font-size: 12px;
		font-weight: 600;
		color: var(--netz-danger, #ef4444);
		background: color-mix(in srgb, var(--netz-danger, #ef4444) 12%, transparent);
		padding: 2px 10px;
		border-radius: 12px;
	}

	.alloc-sim-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 12px;
	}

	.alloc-sim-warning {
		margin: 12px 0 0;
		font-size: 13px;
		font-weight: 500;
		color: var(--netz-danger, #ef4444);
	}
</style>
