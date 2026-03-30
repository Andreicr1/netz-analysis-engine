<!--
  Portfolio Builder — Creation Wizard (5 steps).
  Step 1: Profile selection
  Step 2: Fund selection by block
  Step 3: Macro inputs (optional)
  Step 4: Construct (run optimizer for all 3 mandates)
  Step 5: Activate
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import {
		PageHeader, Button, StatusBadge, EmptyState,
		formatPercent, formatNumber, formatDate,
	} from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { UniverseAsset } from "$lib/types/universe";
	import type { ModelPortfolio, SelectionSchema } from "$lib/types/model-portfolio";
	import { profileColor } from "$lib/types/model-portfolio";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── Data from loader ─────────────────────────────────────────────────

	interface StrategicBlock {
		allocation_id: string;
		profile: string;
		block_id: string;
		target_weight: number;
		min_weight: number;
		max_weight: number;
		risk_budget: number | null;
	}

	interface MacroReview {
		id: string;
		status: string;
		regime: string | null;
		score_deltas: Record<string, number> | null;
		review_date: string | null;
		created_at: string;
	}

	let universe = $derived((data.universe ?? []) as UniverseAsset[]);
	let strategic = $derived((data.strategic ?? []) as StrategicBlock[]);
	let macroReviews = $derived((data.macroReviews ?? []) as MacroReview[]);
	let existingPortfolios = $derived((data.existingPortfolios ?? []) as ModelPortfolio[]);

	// Approved funds only
	let approvedFunds = $derived(universe.filter((f) => f.approval_decision === "approved"));

	// ── Block display names ──────────────────────────────────────────────

	const BLOCK_DISPLAY_NAMES: Record<string, string> = {
		na_equity_large: "US Large Cap Equity",
		na_equity_value: "US Value Equity",
		na_equity_small: "NA Equity Small",
		fi_us_aggregate: "US Aggregate Fixed Income",
		fi_us_high_yield: "US High Yield",
		fi_us_tips: "US TIPS",
		fi_us_treasury: "US Treasury",
		fi_treasury: "Treasuries",
		fi_credit_ig: "Credit IG",
		fi_credit_hy: "Credit HY",
		dm_europe_equity: "DM Europe Equity",
		intl_equity_dm: "Intl Equity DM",
		intl_equity_em: "Intl Equity EM",
		em_equity: "Emerging Markets Equity",
		alt_gold: "Alternative — Gold",
		alt_real_estate: "Alternative — Real Estate",
		alt_reits: "REITs",
		cash: "Cash",
	};

	function blockDisplayName(blockId: string): string {
		return BLOCK_DISPLAY_NAMES[blockId]
			?? blockId.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	// Geography pre-filter mapping: block → expected investment geography
	const BLOCK_GEOGRAPHY: Record<string, string> = {
		na_equity_large: "US",
		na_equity_value: "US",
		na_equity_small: "US",
		fi_us_aggregate: "US",
		fi_us_high_yield: "US",
		fi_us_tips: "US",
		fi_us_treasury: "US",
		fi_treasury: "US",
		fi_credit_ig: "US",
		fi_credit_hy: "US",
		dm_europe_equity: "Europe",
		intl_equity_dm: "Global",
		intl_equity_em: "Emerging Markets",
		em_equity: "Emerging Markets",
		alt_gold: "Global",
		alt_real_estate: "US",
		alt_reits: "US",
		cash: "US",
	};

	let showAllGeographies = $state(false);

	// ── Block list from strategic allocation ─────────────────────────────

	let blockIds = $derived(strategic.map((s) => s.block_id));

	// ── Wizard state ─────────────────────────────────────────────────────

	let currentStep = $state(1);
	let selectedProfile = $state<"conservative" | "moderate" | "growth" | null>(null);
	let selectedFundsByBlock = $state<Map<string, Set<string>>>(new Map());
	let selectedBlockId = $state<string | null>(null);
	let macroReviewId = $state<string | null>(null);

	// Construction results
	interface ConstructResult {
		profile: string;
		portfolio: ModelPortfolio | null;
		error: string | null;
		optimization: {
			expected_return: number;
			portfolio_volatility: number;
			sharpe_ratio: number;
			cvar_95: number;
			cvar_limit: number;
			cvar_within_limit: boolean;
			solver: string;
			status: string;
			factor_exposures: Record<string, number> | null;
		} | null;
	}
	let constructionResults = $state<ConstructResult[]>([]);
	let isConstructing = $state(false);
	let constructError = $state<string | null>(null);

	// Activation state
	let portfolioName = $state("");
	let inceptionDate = $state(new Date().toISOString().slice(0, 10));
	let icApproved = $state(false);
	let isActivating = $state(false);
	let activateError = $state<string | null>(null);

	// ── Profile config ───────────────────────────────────────────────────

	const PROFILE_CONFIG = [
		{
			key: "conservative" as const,
			label: "Conservative",
			cvar: "−8%",
			maxFund: "10%",
			desc: "Lower drawdown tolerance, capital preservation focus",
		},
		{
			key: "moderate" as const,
			label: "Moderate",
			cvar: "−6%",
			maxFund: "12%",
			desc: "Balanced risk-return with moderate CVaR tolerance",
		},
		{
			key: "growth" as const,
			label: "Growth",
			cvar: "−12%",
			maxFund: "15%",
			desc: "Higher return potential with wider CVaR budget",
		},
	];

	// ── Derived helpers ──────────────────────────────────────────────────

	let totalSelectedFunds = $derived.by(() => {
		let total = 0;
		for (const set of selectedFundsByBlock.values()) {
			total += set.size;
		}
		return total;
	});

	let coveredBlocks = $derived.by(() => {
		let count = 0;
		for (const blockId of blockIds) {
			const set = selectedFundsByBlock.get(blockId);
			if (set && set.size > 0) count++;
		}
		return count;
	});

	let fundsForSelectedBlock = $derived.by(() => {
		if (!selectedBlockId) return [];
		let funds = approvedFunds.filter((f) => f.block_id === selectedBlockId);
		if (!showAllGeographies) {
			const expectedGeo = BLOCK_GEOGRAPHY[selectedBlockId];
			if (expectedGeo) {
				const geoFiltered = funds.filter((f) => f.investment_geography === expectedGeo);
				// Only apply filter if it leaves some results; otherwise show all
				if (geoFiltered.length > 0) funds = geoFiltered;
			}
		}
		return funds;
	});

	let selectedFundIdsForBlock = $derived.by(() => {
		if (!selectedBlockId) return new Set<string>();
		return selectedFundsByBlock.get(selectedBlockId) ?? new Set();
	});

	function getAllSelectedFundIds(): string[] {
		const ids: string[] = [];
		for (const set of selectedFundsByBlock.values()) {
			for (const id of set) ids.push(id);
		}
		return ids;
	}

	// ── Fund toggle ──────────────────────────────────────────────────────

	function toggleFund(fundId: string) {
		if (!selectedBlockId) return;
		const next = new Map(selectedFundsByBlock);
		const blockSet = new Set(next.get(selectedBlockId) ?? []);
		if (blockSet.has(fundId)) {
			blockSet.delete(fundId);
		} else {
			blockSet.add(fundId);
		}
		next.set(selectedBlockId, blockSet);
		selectedFundsByBlock = next;
	}

	// ── Step navigation ──────────────────────────────────────────────────

	function canAdvance(step: number): boolean {
		switch (step) {
			case 1: return selectedProfile !== null;
			case 2: return totalSelectedFunds > 0;
			case 3: return true; // optional
			case 4: return constructionResults.some((r) => r.optimization?.solver !== "heuristic_fallback" && r.optimization?.solver !== undefined);
			default: return true;
		}
	}

	// ── Construction ─────────────────────────────────────────────────────

	async function runConstruction() {
		isConstructing = true;
		constructError = null;
		constructionResults = [];

		try {
			const api = createClientApiClient(getToken);
			const profiles = ["conservative", "moderate", "growth"] as const;
			const fundIds = getAllSelectedFundIds();

			// Find or create model portfolios for each profile
			const portfolioIdsByProfile: Record<string, string> = {};
			for (const p of profiles) {
				const existing = existingPortfolios.find((mp) => mp.profile === p);
				if (existing) {
					portfolioIdsByProfile[p] = existing.id;
				} else {
					const created = await api.post<ModelPortfolio>("/model-portfolios", {
						profile: p,
						display_name: `${p.charAt(0).toUpperCase() + p.slice(1)} Portfolio`,
					});
					portfolioIdsByProfile[p] = created.id;
				}
			}

			// Run construct in parallel for all 3
			const results = await Promise.allSettled(
				profiles.map((profile) =>
					api.post<ModelPortfolio>(`/model-portfolios/${portfolioIdsByProfile[profile]}/construct`, {
						fund_ids: fundIds,
						macro_review_id: macroReviewId ?? undefined,
					})
				)
			);

			constructionResults = profiles.map((profile, i) => {
				const result = results[i]!;
				if (result.status === "fulfilled") {
					const mp = result.value;
					// The backend may include optimization metadata alongside fund_selection_schema
					const schema = mp.fund_selection_schema as unknown as Record<string, unknown> | null;
					const optimization = (schema?.optimization ?? null) as ConstructResult["optimization"];
					return {
						profile,
						portfolio: mp,
						error: null,
						optimization,
					};
				}
				return {
					profile,
					portfolio: null,
					error: result.reason instanceof Error ? result.reason.message : "Construction failed",
					optimization: null,
				};
			});

			// Refresh existing portfolios list
			existingPortfolios = await api.get<ModelPortfolio[]>("/model-portfolios").catch(() => existingPortfolios);
		} catch (e) {
			constructError = e instanceof Error ? e.message : "Construction failed";
		} finally {
			isConstructing = false;
		}
	}

	// ── Activation ───────────────────────────────────────────────────────

	async function activatePortfolios() {
		isActivating = true;
		activateError = null;

		try {
			const api = createClientApiClient(getToken);
			const profiles = ["conservative", "moderate", "growth"] as const;

			for (const profile of profiles) {
				const result = constructionResults.find((r) => r.profile === profile);
				if (!result?.portfolio) continue;

				await api.patch<ModelPortfolio>(`/model-portfolios/${result.portfolio.id}`, {
					display_name: portfolioName || `${profile.charAt(0).toUpperCase() + profile.slice(1)} Portfolio`,
					inception_date: inceptionDate || null,
					status: "approved",
				});
			}

			goto("/portfolios");
		} catch (e) {
			activateError = e instanceof Error ? e.message : "Activation failed";
		} finally {
			isActivating = false;
		}
	}

	// ── Solver badge colors ──────────────────────────────────────────────

	let allFactorNames = $derived.by(() => {
		const factors = new Set<string>();
		for (const r of constructionResults) {
			if (r.optimization?.factor_exposures) {
				for (const key of Object.keys(r.optimization.factor_exposures)) {
					factors.add(key);
				}
			}
		}
		return [...factors];
	});

	function solverColor(solver: string | undefined): string {
		if (!solver) return "var(--ii-text-muted)";
		if (solver === "CLARABEL") return "var(--ii-success)";
		if (solver === "SCS") return "var(--ii-warning)";
		return "var(--ii-danger)";
	}

	function cvarStatusColor(within: boolean | undefined, utilized: number): string {
		if (within === undefined) return "var(--ii-text-muted)";
		if (utilized >= 100) return "var(--ii-danger)";
		if (utilized >= 80) return "var(--ii-warning)";
		return "var(--ii-success)";
	}

	function cvarUtilized(cvar: number | undefined, limit: number | undefined): number {
		if (!cvar || !limit || limit === 0) return 0;
		return Math.abs(cvar / limit) * 100;
	}

	// ── Step labels ──────────────────────────────────────────────────────
	const STEP_LABELS = ["Profile", "Fund Selection", "Macro Inputs", "Construct", "Activate"];
</script>

<PageHeader
	title="Portfolio Builder"
	subtitle="Create model portfolios for each risk mandate"
	breadcrumbs={[{ label: "Model Portfolios", href: "/model-portfolios" }, { label: "Create" }]}
/>

<!-- Step indicator -->
<div class="wizard-steps">
	{#each STEP_LABELS as label, i (i)}
		{@const step = i + 1}
		<button
			class="wizard-step"
			class:wizard-step--active={currentStep === step}
			class:wizard-step--completed={currentStep > step}
			onclick={() => { if (step < currentStep) currentStep = step; }}
			disabled={step > currentStep}
			type="button"
		>
			<span class="wizard-step-number">{step}</span>
			<span class="wizard-step-label">{label}</span>
		</button>
		{#if i < STEP_LABELS.length - 1}
			<div class="wizard-step-connector" class:wizard-step-connector--done={currentStep > step}></div>
		{/if}
	{/each}
</div>

<div class="wizard-content">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- STEP 1 — Profile Selection                                        -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#if currentStep === 1}
		<div class="step-section">
			<h2 class="step-title">Select Primary Profile</h2>
			<p class="step-subtitle">The optimizer will build all 3 mandates simultaneously. Select the primary profile for naming.</p>

			<div class="profile-grid">
				{#each PROFILE_CONFIG as cfg (cfg.key)}
					<button
						class="profile-card"
						class:profile-card--selected={selectedProfile === cfg.key}
						onclick={() => selectedProfile = cfg.key}
						type="button"
					>
						<div class="profile-card-header">
							<span class="profile-label" style:color={profileColor(cfg.key)}>
								{cfg.label}
							</span>
							{#if selectedProfile === cfg.key}
								<span class="profile-check">&#10003;</span>
							{/if}
						</div>
						<div class="profile-kpis">
							<div class="profile-kpi">
								<span class="profile-kpi-label">CVaR Limit</span>
								<span class="profile-kpi-value">{cfg.cvar}</span>
							</div>
							<div class="profile-kpi">
								<span class="profile-kpi-label">Max Single Fund</span>
								<span class="profile-kpi-value">{cfg.maxFund}</span>
							</div>
						</div>
						<p class="profile-desc">{cfg.desc}</p>
					</button>
				{/each}
			</div>
		</div>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- STEP 2 — Fund Selection                                           -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{:else if currentStep === 2}
		<div class="step-section">
			<h2 class="step-title">Select Funds by Block</h2>
			<p class="step-subtitle">
				Choose approved funds for each allocation block.
				{totalSelectedFunds} fund{totalSelectedFunds !== 1 ? "s" : ""} selected across {coveredBlocks} / {blockIds.length} blocks.
			</p>

			<div class="fund-selection-layout">
				<!-- Block list sidebar -->
				<div class="block-list">
					{#each blockIds as blockId (blockId)}
						{@const count = selectedFundsByBlock.get(blockId)?.size ?? 0}
						{@const available = approvedFunds.filter((f) => f.block_id === blockId).length}
						<button
							class="block-item"
							class:block-item--active={selectedBlockId === blockId}
							class:block-item--empty={count === 0 && available > 0}
							onclick={() => selectedBlockId = blockId}
							type="button"
						>
							<span class="block-item-name">{blockDisplayName(blockId)}</span>
							<span class="block-item-count" class:block-item-count--zero={count === 0}>
								{count > 0 ? `${count} selected` : available > 0 ? "Empty" : "No funds"}
							</span>
						</button>
					{/each}
				</div>

				<!-- Fund list for selected block -->
				<div class="fund-list">
					{#if !selectedBlockId}
						<EmptyState title="Select a block" message="Click an allocation block on the left to see available funds." />
					{:else if fundsForSelectedBlock.length === 0}
						<EmptyState
							title="No approved funds"
							message="No funds have been approved for the {blockDisplayName(selectedBlockId)} block. Approve funds in the Assets Universe first."
						/>
					{:else}
						<div class="fund-list-header">
							<h3 class="fund-list-title">{blockDisplayName(selectedBlockId)}</h3>
							<span class="fund-list-count">{fundsForSelectedBlock.length} approved fund{fundsForSelectedBlock.length !== 1 ? "s" : ""}</span>
						</div>
						{#if BLOCK_GEOGRAPHY[selectedBlockId]}
							<label class="geo-toggle">
								<input type="checkbox" bind:checked={showAllGeographies} />
								<span>Show all geographies</span>
								{#if !showAllGeographies}
									<span class="geo-tag">{BLOCK_GEOGRAPHY[selectedBlockId]}</span>
								{/if}
							</label>
						{/if}
						<div class="fund-items">
							{#each fundsForSelectedBlock as fund (fund.fund_id)}
								{@const isSelected = selectedFundIdsForBlock.has(fund.fund_id)}
								<button
									class="fund-item"
									class:fund-item--selected={isSelected}
									onclick={() => toggleFund(fund.fund_id)}
									type="button"
								>
									<div class="fund-item-info">
										<span class="fund-item-name">{fund.fund_name}</span>
										<span class="fund-item-meta">
											{fund.investment_geography ?? fund.geography ?? ""}{(fund.investment_geography || fund.geography) && fund.asset_class ? " · " : ""}{fund.asset_class ?? ""}
										</span>
									</div>
									<span class="fund-item-toggle">
										{isSelected ? "✓ Remove" : "+ Add"}
									</span>
								</button>
							{/each}
						</div>
					{/if}
				</div>
			</div>

			{#if coveredBlocks < blockIds.length && totalSelectedFunds > 0}
				<div class="step-warning">
					Some blocks have no funds — the optimizer will exclude them from allocation.
				</div>
			{/if}
		</div>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- STEP 3 — Macro Inputs (Optional)                                  -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{:else if currentStep === 3}
		<div class="step-section">
			<h2 class="step-title">Macro Inputs</h2>
			<div class="step-optional-banner">
				This step is optional. If skipped, the optimizer uses Black-Litterman market equilibrium prior.
			</div>

			<h3 class="subsection-title">Macro Review</h3>
			{#if macroReviews.length === 0}
				<p class="step-subtitle">No approved macro reviews available.</p>
			{:else}
				<div class="macro-reviews">
					{#each macroReviews as review (review.id)}
						<button
							class="macro-card"
							class:macro-card--selected={macroReviewId === review.id}
							onclick={() => macroReviewId = macroReviewId === review.id ? null : review.id}
							type="button"
						>
							<div class="macro-card-header">
								<span class="macro-date">{review.review_date ?? formatDate(review.created_at)}</span>
								{#if review.regime}
									<StatusBadge status={review.regime} />
								{/if}
							</div>
							{#if review.score_deltas}
								<div class="macro-deltas">
									{#each Object.entries(review.score_deltas) as [region, delta] (region)}
										<span class="macro-delta" style:color={Number(delta) >= 0 ? "var(--ii-success)" : "var(--ii-danger)"}>
											{region} {Number(delta) >= 0 ? "+" : ""}{formatNumber(Number(delta), 1)}pt
										</span>
									{/each}
								</div>
							{/if}
							{#if macroReviewId === review.id}
								<span class="macro-selected-indicator">Selected</span>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- STEP 4 — Construct                                                -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{:else if currentStep === 4}
		<div class="step-section">
			<h2 class="step-title">Construct Portfolios</h2>

			{#if constructionResults.length === 0 && !isConstructing}
				<!-- Pre-construction summary -->
				<div class="construct-summary">
					<div class="construct-summary-row">
						<span class="construct-summary-label">Funds selected</span>
						<span class="construct-summary-value">{totalSelectedFunds} total, {coveredBlocks} blocks covered</span>
					</div>
					<div class="construct-summary-row">
						<span class="construct-summary-label">Macro Review</span>
						<span class="construct-summary-value">
							{macroReviewId ? macroReviews.find((r) => r.id === macroReviewId)?.review_date ?? "Selected" : "Market equilibrium prior"}
						</span>
					</div>
				</div>

				<div class="construct-action">
					<Button onclick={runConstruction} disabled={isConstructing}>
						Run optimizer for all 3 mandates
					</Button>
				</div>
			{/if}

			{#if isConstructing}
				<div class="construct-loading">
					<div class="construct-spinner"></div>
					<span>Running CLARABEL optimizer for 3 mandates...</span>
				</div>
			{/if}

			{#if constructError}
				<div class="step-error">{constructError}</div>
			{/if}

			{#if constructionResults.length > 0}
				<!-- Results cards -->
				<div class="construct-results">
					{#each constructionResults as result (result.profile)}
						<div class="construct-card" class:construct-card--error={result.error !== null}>
							<div class="construct-card-header">
								<span class="construct-profile" style:color={profileColor(result.profile)}>
									{result.profile}
								</span>
								{#if result.optimization?.solver}
									<span class="construct-solver" style:color={solverColor(result.optimization.solver)}>
										{result.optimization.solver}
									</span>
								{/if}
							</div>

							{#if result.error}
								<div class="construct-card-error">{result.error}</div>
							{:else if result.optimization}
								{@const opt = result.optimization}
								{@const utilized = cvarUtilized(opt.cvar_95, opt.cvar_limit)}
								<div class="construct-metrics">
									<div class="construct-metric">
										<span class="construct-metric-label">CVaR 95%</span>
										<span class="construct-metric-value">{formatPercent(opt.cvar_95)}</span>
									</div>
									<div class="construct-metric">
										<span class="construct-metric-label">CVaR Limit</span>
										<span class="construct-metric-value">{formatPercent(opt.cvar_limit)}</span>
									</div>
									<div class="construct-metric">
										<span class="construct-metric-label">Utilized</span>
										<span class="construct-metric-value" style:color={cvarStatusColor(opt.cvar_within_limit, utilized)}>
											{formatNumber(utilized, 0)}%
										</span>
									</div>
									<div class="construct-metric">
										<span class="construct-metric-label">Sharpe</span>
										<span class="construct-metric-value">{formatNumber(opt.sharpe_ratio, 2)}</span>
									</div>
									<div class="construct-metric">
										<span class="construct-metric-label">Volatility</span>
										<span class="construct-metric-value">{formatPercent(opt.portfolio_volatility)}</span>
									</div>
								</div>

								<div class="construct-status" style:color={cvarStatusColor(opt.cvar_within_limit, utilized)}>
									{#if utilized < 80}
										Within CVaR limit
									{:else if utilized < 100}
										Near limit — review fund selection
									{:else}
										Exceeds limit — cannot activate
									{/if}
								</div>
							{:else}
								<!-- Portfolio was created but no optimization data returned -->
								<div class="construct-card-info">
									Portfolio created. Run backtest from the detail page for full metrics.
								</div>
							{/if}
						</div>
					{/each}
				</div>

				<!-- Factor exposures table (if available) -->
				{#if constructionResults.some((r) => r.optimization?.factor_exposures)}
					<div class="factor-section">
						<h3 class="subsection-title">Factor Exposures</h3>
						<table class="factor-table">
							<thead>
								<tr>
									<th></th>
									{#each constructionResults as r (r.profile)}
										<th style:color={profileColor(r.profile)}>
											{r.profile.charAt(0).toUpperCase() + r.profile.slice(1)}
										</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each allFactorNames as factor (factor)}
									<tr>
										<td class="factor-name">{factor.replace(/_/g, " ")}</td>
										{#each constructionResults as r (r.profile)}
											{@const val = r.optimization?.factor_exposures?.[factor]}
											<td class="factor-value">
												{val !== undefined ? (val >= 0 ? "+" : "") + formatNumber(val, 3) : "—"}
											</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}

				{#if !isConstructing}
					<div class="construct-retry-actions">
						<Button variant="outline" onclick={() => { constructionResults = []; }}>
							Retry
						</Button>
					</div>
				{/if}
			{/if}
		</div>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- STEP 5 — Activate                                                 -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{:else if currentStep === 5}
		<div class="step-section">
			<h2 class="step-title">Activate Portfolios</h2>

			<div class="activate-form">
				<label class="activate-field">
					<span class="activate-label">Portfolio Name <span class="required">*</span></span>
					<input
						type="text"
						class="activate-input"
						placeholder="e.g. Moderate 2026"
						bind:value={portfolioName}
					/>
				</label>

				<label class="activate-field">
					<span class="activate-label">Inception Date</span>
					<input type="date" class="activate-input" bind:value={inceptionDate} />
				</label>
			</div>

			<!-- Summary table -->
			{#if constructionResults.length > 0}
				<h3 class="subsection-title">Construction Summary</h3>
				<table class="summary-table">
					<thead>
						<tr>
							<th>Profile</th>
							<th>Solver</th>
							<th>CVaR 95%</th>
							<th>Sharpe</th>
							<th>Status</th>
						</tr>
					</thead>
					<tbody>
						{#each constructionResults as r (r.profile)}
							<tr>
								<td style:color={profileColor(r.profile)} class="summary-profile">
									{r.profile.charAt(0).toUpperCase() + r.profile.slice(1)}
								</td>
								<td>
									{#if r.optimization?.solver}
										<span style:color={solverColor(r.optimization.solver)}>{r.optimization.solver}</span>
									{:else}
										—
									{/if}
								</td>
								<td>{r.optimization ? formatPercent(r.optimization.cvar_95) : "—"}</td>
								<td>{r.optimization ? formatNumber(r.optimization.sharpe_ratio, 2) : "—"}</td>
								<td>
									{#if r.error}
										<span style:color="var(--ii-danger)">Failed</span>
									{:else if r.optimization?.cvar_within_limit}
										<span style:color="var(--ii-success)">OK</span>
									{:else}
										<span style:color="var(--ii-warning)">Review</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}

			<!-- IC Approval checkbox -->
			<label class="activate-checkbox">
				<input type="checkbox" bind:checked={icApproved} />
				<span>I confirm this portfolio construction has been reviewed and approved by the Investment Committee.</span>
			</label>

			{#if activateError}
				<div class="step-error">{activateError}</div>
			{/if}

			<div class="activate-actions">
				<Button
					onclick={activatePortfolios}
					disabled={!portfolioName.trim() || !icApproved || isActivating}
				>
					{isActivating ? "Activating..." : "Activate Portfolios"}
				</Button>
			</div>
		</div>
	{/if}
</div>

<!-- Navigation footer -->
<div class="wizard-footer">
	{#if currentStep > 1}
		<Button variant="outline" onclick={() => currentStep--}>
			Back
		</Button>
	{:else}
		<Button variant="outline" onclick={() => goto("/model-portfolios")}>
			Cancel
		</Button>
	{/if}

	<div class="wizard-footer-right">
		{#if currentStep === 3}
			<Button variant="ghost" onclick={() => currentStep = 4}>
				Skip
			</Button>
		{/if}
		{#if currentStep < 5}
			<Button
				onclick={() => currentStep++}
				disabled={!canAdvance(currentStep)}
			>
				Next
			</Button>
		{/if}
	</div>
</div>

<style>
	/* ── Wizard steps indicator ─────────────────────────────────────────── */
	.wizard-steps {
		display: flex;
		align-items: center;
		gap: 0;
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.wizard-step {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		border: none;
		background: transparent;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: color 120ms ease;
	}

	.wizard-step:disabled { cursor: default; }
	.wizard-step:not(:disabled):hover { color: var(--ii-text-primary); }

	.wizard-step--active { color: var(--ii-brand-primary); font-weight: 600; }
	.wizard-step--completed { color: var(--ii-success); }

	.wizard-step-number {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		border: 1.5px solid currentColor;
		font-size: 11px;
		font-weight: 700;
		flex-shrink: 0;
	}

	.wizard-step--active .wizard-step-number {
		background: var(--ii-brand-primary);
		border-color: var(--ii-brand-primary);
		color: white;
	}

	.wizard-step--completed .wizard-step-number {
		background: var(--ii-success);
		border-color: var(--ii-success);
		color: white;
	}

	.wizard-step-label {
		white-space: nowrap;
	}

	.wizard-step-connector {
		flex: 1;
		height: 1px;
		min-width: 12px;
		background: var(--ii-border-subtle);
	}

	.wizard-step-connector--done {
		background: var(--ii-success);
	}

	/* ── Content area ───────────────────────────────────────────────────── */
	.wizard-content {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		min-height: 400px;
	}

	.step-section {
		max-width: 960px;
	}

	.step-title {
		font-size: var(--ii-text-h3, 1.25rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		margin-bottom: 4px;
	}

	.step-subtitle {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	.subsection-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		margin: var(--ii-space-stack-md, 16px) 0 var(--ii-space-stack-xs, 8px);
	}

	.step-warning {
		margin-top: var(--ii-space-stack-sm, 12px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-warning) 8%, transparent);
		color: var(--ii-warning);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.step-error {
		margin-top: var(--ii-space-stack-sm, 12px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.step-optional-banner {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-info) 8%, transparent);
		color: var(--ii-info);
		font-size: var(--ii-text-small, 0.8125rem);
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	/* ── Step 1 — Profile grid ──────────────────────────────────────────── */
	.profile-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--ii-space-stack-sm, 12px);
	}

	.profile-card {
		display: flex;
		flex-direction: column;
		padding: var(--ii-space-stack-md, 16px);
		border: 2px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		cursor: pointer;
		text-align: left;
		font-family: var(--ii-font-sans);
		transition: border-color 120ms ease, box-shadow 120ms ease;
	}

	.profile-card:hover {
		border-color: var(--ii-border-accent);
	}

	.profile-card--selected {
		border-color: var(--ii-brand-primary);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	.profile-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.profile-label {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.profile-check {
		color: var(--ii-brand-primary);
		font-size: 1.125rem;
		font-weight: 700;
	}

	.profile-kpis {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
		background: var(--ii-border-subtle);
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.profile-kpi {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 10px);
		background: var(--ii-surface-elevated);
	}

	.profile-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.profile-kpi-value {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.profile-desc {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		line-height: 1.5;
	}

	/* ── Step 2 — Fund selection ────────────────────────────────────────── */
	.fund-selection-layout {
		display: grid;
		grid-template-columns: 200px 1fr;
		gap: var(--ii-space-inline-md, 16px);
		min-height: 400px;
	}

	.block-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		border-right: 1px solid var(--ii-border-subtle);
		padding-right: var(--ii-space-inline-md, 16px);
		overflow-y: auto;
	}

	.block-item {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 10px);
		border: none;
		border-radius: var(--ii-radius-sm, 8px);
		background: transparent;
		text-align: left;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: background 80ms ease;
	}

	.block-item:hover { background: var(--ii-surface-alt); }

	.block-item--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
	}

	.block-item-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.block-item-count {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-success);
	}

	.block-item-count--zero {
		color: var(--ii-text-muted);
	}

	.block-item--empty .block-item-count {
		color: var(--ii-warning);
	}

	.fund-list {
		overflow-y: auto;
	}

	.fund-list-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.geo-toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-secondary);
		margin-bottom: var(--ii-space-stack-sm, 12px);
		cursor: pointer;
	}

	.geo-tag {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 3px;
		background: var(--ii-surface-alt, #f0f0f0);
		font-size: 0.6875rem;
		font-weight: 500;
	}

	.fund-list-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.fund-list-count {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.fund-items {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.fund-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface-elevated);
		cursor: pointer;
		text-align: left;
		font-family: var(--ii-font-sans);
		transition: border-color 80ms ease, background 80ms ease;
	}

	.fund-item:hover {
		border-color: var(--ii-border-accent);
	}

	.fund-item--selected {
		border-color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 4%, transparent);
	}

	.fund-item-info {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}

	.fund-item-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.fund-item-meta {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.fund-item-toggle {
		flex-shrink: 0;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-brand-primary);
		white-space: nowrap;
	}

	.fund-item--selected .fund-item-toggle {
		color: var(--ii-danger);
	}

	/* ── Step 3 — Macro ─────────────────────────────────────────────────── */
	.macro-reviews {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-xs, 8px);
	}

	.macro-card {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border: 2px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		cursor: pointer;
		text-align: left;
		font-family: var(--ii-font-sans);
		transition: border-color 120ms ease;
	}

	.macro-card:hover { border-color: var(--ii-border-accent); }

	.macro-card--selected {
		border-color: var(--ii-brand-primary);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	.macro-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.macro-date {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.macro-deltas {
		display: flex;
		flex-wrap: wrap;
		gap: var(--ii-space-inline-sm, 8px);
	}

	.macro-delta {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.macro-selected-indicator {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-brand-primary);
	}

	/* ── Step 4 — Construct ─────────────────────────────────────────────── */
	.construct-summary {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	.construct-summary-row {
		display: flex;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.construct-summary-row:last-child { border-bottom: none; }

	.construct-summary-label {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
	}

	.construct-summary-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.construct-action {
		text-align: center;
		padding: var(--ii-space-stack-lg, 24px) 0;
	}

	.construct-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--ii-space-inline-md, 16px);
		padding: var(--ii-space-stack-xl, 48px) 0;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-body, 0.9375rem);
	}

	.construct-spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--ii-border);
		border-top-color: var(--ii-brand-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.construct-results {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--ii-space-stack-sm, 12px);
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	.construct-card {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
		background: var(--ii-surface-elevated);
	}

	.construct-card--error {
		border-color: var(--ii-danger);
	}

	.construct-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.construct-profile {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.construct-solver {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
	}

	.construct-metrics {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		margin: var(--ii-space-stack-xs, 8px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
		background: var(--ii-border-subtle);
	}

	.construct-metric {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-sm, 8px);
		background: var(--ii-surface-elevated);
	}

	.construct-metric-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.construct-metric-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.construct-status {
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-align: center;
		padding-bottom: var(--ii-space-stack-xs, 8px);
	}

	.construct-card-error {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.construct-card-info {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.construct-retry-actions {
		display: flex;
		gap: var(--ii-space-inline-sm, 8px);
		margin-top: var(--ii-space-stack-sm, 12px);
	}

	/* ── Factor table ───────────────────────────────────────────────────── */
	.factor-section {
		margin-top: var(--ii-space-stack-md, 16px);
	}

	.factor-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.factor-table th,
	.factor-table td {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
		text-align: right;
	}

	.factor-table th {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		background: var(--ii-surface-alt);
		color: var(--ii-text-muted);
	}

	.factor-table th:first-child,
	.factor-table td:first-child {
		text-align: left;
	}

	.factor-name {
		font-weight: 500;
		color: var(--ii-text-primary);
		text-transform: capitalize;
	}

	.factor-value {
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-secondary);
	}

	/* ── Step 5 — Activate ──────────────────────────────────────────────── */
	.activate-form {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--ii-space-inline-md, 16px);
		margin-bottom: var(--ii-space-stack-md, 16px);
		max-width: 600px;
	}

	.activate-field {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
	}

	.activate-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.required { color: var(--ii-danger); }

	.activate-input {
		height: var(--ii-space-control-height-sm, 36px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.activate-input:focus {
		outline: none;
		border-color: var(--ii-border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-secondary) 20%, transparent);
	}

	.summary-table {
		width: 100%;
		max-width: 600px;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	.summary-table th {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
		text-align: left;
	}

	.summary-table td {
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.summary-profile {
		font-weight: 600;
		text-transform: capitalize;
	}

	.activate-checkbox {
		display: flex;
		align-items: flex-start;
		gap: var(--ii-space-inline-sm, 10px);
		padding: var(--ii-space-stack-md, 16px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-alt);
		cursor: pointer;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		max-width: 600px;
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	.activate-checkbox input[type="checkbox"] {
		margin-top: 2px;
		flex-shrink: 0;
	}

	.activate-actions {
		display: flex;
		gap: var(--ii-space-inline-sm, 8px);
	}

	/* ── Footer ─────────────────────────────────────────────────────────── */
	.wizard-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-lg, 24px);
		border-top: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface);
		position: sticky;
		bottom: 0;
	}

	.wizard-footer-right {
		display: flex;
		gap: var(--ii-space-inline-sm, 8px);
	}

	/* ── Responsive ─────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.profile-grid { grid-template-columns: 1fr; }
		.fund-selection-layout { grid-template-columns: 1fr; }
		.construct-results { grid-template-columns: 1fr; }
		.activate-form { grid-template-columns: 1fr; }
	}
</style>
