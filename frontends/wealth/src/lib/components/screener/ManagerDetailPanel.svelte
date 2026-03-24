<!--
  Manager detail panel — 7 tabs: profile, holdings, institutional, universe, drift, nport, docs.
-->
<script lang="ts">
	import "./screener.css";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import {
		Button, StatusBadge, ConsequenceDialog,
		formatAUM, formatPercent, formatDate,
	} from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type {
		ManagerProfile, HoldingsData, InstitutionalData, UniverseStatus, DetailTab,
	} from "$lib/types/manager-screener";
	import DriftTab from "./DriftTab.svelte";
	import HoldingsTab from "./HoldingsTab.svelte";
	import DocsTab from "./DocsTab.svelte";

	interface Props {
		panelCrd: string;
		panelFirm: string;
	}

	let { panelCrd, panelFirm }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let activeTab = $state<DetailTab>("profile");
	let detailLoading = $state(false);
	let profileData = $state<ManagerProfile | null>(null);
	let holdingsData = $state<HoldingsData | null>(null);
	let institutionalData = $state<InstitutionalData | null>(null);
	let universeData = $state<UniverseStatus | null>(null);

	// Add to Universe
	let addDialogOpen = $state(false);
	let addAssetClass = $state("hedge_fund");
	let addGeography = $state("Global");
	let addCurrency = $state("USD");
	let adding = $state(false);
	let addError = $state<string | null>(null);

	// Load first tab on mount
	$effect(() => {
		if (panelCrd) {
			profileData = null;
			holdingsData = null;
			institutionalData = null;
			universeData = null;
			activeTab = "profile";
			void fetchTab("profile");
		}
	});

	async function fetchTab(tab: DetailTab) {
		if (!panelCrd) return;
		activeTab = tab;
		detailLoading = true;
		try {
			const api = createClientApiClient(getToken);
			switch (tab) {
				case "profile":
					if (!profileData) profileData = await api.get<ManagerProfile>(`/manager-screener/managers/${panelCrd}/profile`);
					break;
				case "holdings":
					if (!holdingsData) holdingsData = await api.get<HoldingsData>(`/manager-screener/managers/${panelCrd}/holdings`);
					break;
				case "institutional":
					if (!institutionalData) institutionalData = await api.get<InstitutionalData>(`/manager-screener/managers/${panelCrd}/institutional`);
					break;
				case "universe":
					if (!universeData) universeData = await api.get<UniverseStatus>(`/manager-screener/managers/${panelCrd}/universe-status`);
					break;
			}
		} catch {
			// silent — panel shows "no data"
		} finally {
			detailLoading = false;
		}
	}

	async function handleAddToUniverse(payload: ConsequenceDialogPayload) {
		if (!panelCrd) return;
		adding = true;
		addError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/manager-screener/managers/${panelCrd}/add-to-universe`, {
				asset_class: addAssetClass,
				geography: addGeography,
				currency: addCurrency,
			});
			addDialogOpen = false;
			universeData = await api.get<UniverseStatus>(`/manager-screener/managers/${panelCrd}/universe-status`);
			await invalidateAll();
		} catch (e) {
			addError = e instanceof Error ? e.message : "Failed to add";
		} finally {
			adding = false;
		}
	}
</script>

<!-- Tab bar -->
<div class="dt-tabs">
	{#each (["profile", "holdings", "institutional", "universe", "drift", "nport", "docs"] as DetailTab[]) as tab (tab)}
		<button
			class="dt-tab"
			class:dt-tab--active={activeTab === tab}
			onclick={() => tab === "drift" || tab === "nport" || tab === "docs" ? (activeTab = tab) : fetchTab(tab)}
		>
			{tab === "nport" ? "Holdings" : tab === "docs" ? "Docs" : tab.charAt(0).toUpperCase() + tab.slice(1)}
		</button>
	{/each}
</div>

<div class="dt-content">
	{#if detailLoading}
		<div class="dt-loading">Loading…</div>
	{:else if activeTab === "profile"}
		{#if profileData}
			<div class="dt-section">
				<div class="dt-kv"><span class="dt-k">CRD</span><span class="dt-v">{profileData.crd_number}</span></div>
				{#if profileData.cik}<div class="dt-kv"><span class="dt-k">CIK</span><span class="dt-v">{profileData.cik}</span></div>{/if}
				<div class="dt-kv"><span class="dt-k">Status</span><StatusBadge status={profileData.registration_status ?? "—"} /></div>
				<div class="dt-kv"><span class="dt-k">AUM Total</span><span class="dt-v">{profileData.aum_total ? formatAUM(profileData.aum_total) : "—"}</span></div>
				<div class="dt-kv"><span class="dt-k">Discretionary</span><span class="dt-v">{profileData.aum_discretionary ? formatAUM(profileData.aum_discretionary) : "—"}</span></div>
				<div class="dt-kv"><span class="dt-k">Accounts</span><span class="dt-v">{profileData.total_accounts ?? "—"}</span></div>
				<div class="dt-kv"><span class="dt-k">Location</span><span class="dt-v">{profileData.state ?? ""}{profileData.state && profileData.country ? ", " : ""}{profileData.country ?? ""}</span></div>
				{#if profileData.website}<div class="dt-kv"><span class="dt-k">Website</span><span class="dt-v">{profileData.website}</span></div>{/if}
				<div class="dt-kv"><span class="dt-k">Disclosures</span><span class="dt-v">{profileData.compliance_disclosures ?? 0}</span></div>
				{#if profileData.last_adv_filed_at}<div class="dt-kv"><span class="dt-k">Last ADV</span><span class="dt-v">{formatDate(profileData.last_adv_filed_at)}</span></div>{/if}
			</div>
			{#if profileData.funds.length > 0}
				<div class="dt-section">
					<h4 class="dt-section-title">Funds ({profileData.funds.length})</h4>
					{#each profileData.funds as fund (fund.fund_name)}
						<div class="dt-list-row">
							<span class="dt-list-name">{fund.fund_name}</span>
							<span class="dt-list-meta">{fund.fund_type ?? ""} · {fund.gross_asset_value ? formatAUM(fund.gross_asset_value) : "—"}</span>
						</div>
					{/each}
				</div>
			{/if}
			{#if profileData.team.length > 0}
				<div class="dt-section">
					<h4 class="dt-section-title">Team ({profileData.team.length})</h4>
					{#each profileData.team as member (member.person_name)}
						<div class="dt-list-row">
							<span class="dt-list-name">{member.person_name}</span>
							<span class="dt-list-meta">{member.title ?? member.role ?? ""}</span>
						</div>
					{/each}
				</div>
			{/if}
		{:else}
			<div class="dt-empty">No profile data.</div>
		{/if}
	{:else if activeTab === "holdings"}
		{#if holdingsData}
			<div class="dt-section">
				<div class="dt-kv"><span class="dt-k">HHI</span><span class="dt-v">{holdingsData.hhi?.toFixed(3) ?? "—"}</span></div>
			</div>
			{#if Object.keys(holdingsData.sector_allocation).length > 0}
				<div class="dt-section">
					<h4 class="dt-section-title">Sector Allocation</h4>
					{#each Object.entries(holdingsData.sector_allocation).sort((a, b) => b[1] - a[1]) as [sector, weight] (sector)}
						<div class="dt-alloc-row">
							<span class="dt-alloc-name">{sector}</span>
							<div class="dt-alloc-bar-track">
								<div class="dt-alloc-bar-fill" style:width="{weight * 100}%"></div>
							</div>
							<span class="dt-alloc-pct">{(weight * 100).toFixed(1)}%</span>
						</div>
					{/each}
				</div>
			{/if}
			{#if holdingsData.top_holdings.length > 0}
				<div class="dt-section">
					<h4 class="dt-section-title">Top Holdings</h4>
					{#each holdingsData.top_holdings as h (h.cusip)}
						<div class="dt-list-row">
							<span class="dt-list-name">{h.issuer_name}</span>
							<span class="dt-list-meta">{h.sector ?? ""} · {h.weight ? formatPercent(h.weight) : "—"}</span>
						</div>
					{/each}
				</div>
			{/if}
		{:else}
			<div class="dt-empty">No holdings data.</div>
		{/if}
	{:else if activeTab === "institutional"}
		{#if institutionalData}
			<div class="dt-section">
				<div class="dt-kv"><span class="dt-k">Coverage</span><StatusBadge status={institutionalData.coverage_type} /></div>
			</div>
			{#if institutionalData.holders.length > 0}
				<div class="dt-section">
					<h4 class="dt-section-title">Institutional Holders ({institutionalData.holders.length})</h4>
					{#each institutionalData.holders as holder (holder.filer_cik)}
						<div class="dt-list-row">
							<span class="dt-list-name">{holder.filer_name}</span>
							<span class="dt-list-meta">{holder.filer_type ?? ""} · {holder.market_value ? formatAUM(holder.market_value) : "—"}</span>
						</div>
					{/each}
				</div>
			{:else}
				<div class="dt-empty">No institutional holders found.</div>
			{/if}
		{:else}
			<div class="dt-empty">No institutional data.</div>
		{/if}
	{:else if activeTab === "universe"}
		{#if universeData?.instrument_id}
			<div class="dt-section">
				<div class="dt-kv"><span class="dt-k">Status</span><StatusBadge status={universeData.approval_status ?? "—"} /></div>
				<div class="dt-kv"><span class="dt-k">Asset Class</span><span class="dt-v">{universeData.asset_class ?? "—"}</span></div>
				<div class="dt-kv"><span class="dt-k">Geography</span><span class="dt-v">{universeData.geography ?? "—"}</span></div>
				<div class="dt-kv"><span class="dt-k">Currency</span><span class="dt-v">{universeData.currency ?? "—"}</span></div>
				{#if universeData.added_at}<div class="dt-kv"><span class="dt-k">Added</span><span class="dt-v">{formatDate(universeData.added_at)}</span></div>{/if}
			</div>
		{:else}
			<div class="dt-section">
				<p class="dt-empty-text">Not yet added to universe.</p>
				<div class="dt-add-form">
					<div class="dt-add-field">
						<label class="dt-add-label" for="add-asset-class">Asset Class</label>
						<select id="add-asset-class" class="dt-add-select" bind:value={addAssetClass}>
							<option value="hedge_fund">Hedge Fund</option>
							<option value="equity">Equity</option>
							<option value="fixed_income">Fixed Income</option>
						</select>
					</div>
					<div class="dt-add-field">
						<label class="dt-add-label" for="add-geography">Geography</label>
						<select id="add-geography" class="dt-add-select" bind:value={addGeography}>
							<option value="Global">Global</option>
							<option value="US">US</option>
							<option value="EU">EU</option>
							<option value="APAC">APAC</option>
							<option value="LATAM">LATAM</option>
						</select>
					</div>
					<div class="dt-add-field">
						<label class="dt-add-label" for="add-currency">Currency</label>
						<select id="add-currency" class="dt-add-select" bind:value={addCurrency}>
							<option value="USD">USD</option>
							<option value="EUR">EUR</option>
							<option value="GBP">GBP</option>
							<option value="BRL">BRL</option>
						</select>
					</div>
					<Button size="sm" onclick={() => addDialogOpen = true}>Add to Universe</Button>
					{#if addError}
						<span class="dt-add-error">{addError}</span>
					{/if}
				</div>
			</div>
		{/if}
	{:else if activeTab === "drift"}
		<DriftTab crd={panelCrd} />
	{:else if activeTab === "nport"}
		<HoldingsTab crd={panelCrd} />
	{:else if activeTab === "docs"}
		<DocsTab crd={panelCrd} />
	{/if}
</div>

<!-- Add to Universe dialog -->
<ConsequenceDialog
	bind:open={addDialogOpen}
	title="Add Manager to Universe"
	impactSummary="This manager will enter the approval pipeline as a pending instrument."
	requireRationale={true}
	rationaleLabel="Justification"
	rationalePlaceholder="Why should this manager enter the universe? (min 10 chars)"
	rationaleMinLength={10}
	confirmLabel="Add to Universe"
	metadata={[
		{ label: "Firm", value: panelFirm },
		{ label: "Asset Class", value: addAssetClass },
		{ label: "Geography", value: addGeography },
	]}
	onConfirm={handleAddToUniverse}
/>
