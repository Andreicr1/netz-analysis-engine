<!--
  Instrument detail context panel — screening info + ESMA import.
-->
<script lang="ts">
	import "./screener.css";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { Button, StatusBadge, ConsequenceDialog, formatAUM, formatPercent } from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { InstrumentSearchItem } from "$lib/types/screening";

	interface Props {
		selectedInstrument: InstrumentSearchItem;
	}

	let { selectedInstrument }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let esmaImportDialogOpen = $state(false);
	let importing = $state(false);
	let importError = $state<string | null>(null);

	async function handleEsmaImport(payload: ConsequenceDialogPayload) {
		if (!selectedInstrument?.isin) return;
		importing = true;
		importError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/screener/import-esma/${selectedInstrument.isin}`, {});
			esmaImportDialogOpen = false;
			await invalidateAll();
		} catch (e) {
			importError = e instanceof Error ? e.message : "Import failed";
		} finally {
			importing = false;
		}
	}

	function sourceBadgeClass(source: string): string {
		switch (source) {
			case "internal": return "source-badge--internal";
			case "esma": return "source-badge--esma";
			case "sec": return "source-badge--sec";
			default: return "";
		}
	}

	function typeBadgeClass(type: string): string {
		switch (type) {
			case "fund": return "type-badge--fund";
			case "etf": return "type-badge--etf";
			case "bond": return "type-badge--bond";
			case "equity": return "type-badge--equity";
			case "hedge_fund": return "type-badge--hedge";
			default: return "";
		}
	}
</script>

<div class="dt-section">
	<div class="dt-header-row">
		{#if selectedInstrument.screening_status}
			<StatusBadge status={selectedInstrument.screening_status} />
		{/if}
		<span class="source-badge {sourceBadgeClass(selectedInstrument.source)}">{selectedInstrument.source}</span>
		<span class="type-badge {typeBadgeClass(selectedInstrument.instrument_type)}">{selectedInstrument.instrument_type}</span>
	</div>
	<div class="dt-fund-meta">
		{#if selectedInstrument.isin}<span>ISIN: {selectedInstrument.isin}</span>{/if}
		{#if selectedInstrument.ticker}<span>Ticker: {selectedInstrument.ticker}</span>{/if}
		{#if selectedInstrument.manager_name}<span>Manager: {selectedInstrument.manager_name}</span>{/if}
		{#if selectedInstrument.aum}<span>AUM: {formatAUM(selectedInstrument.aum)}</span>{/if}
		<span>Geography: {selectedInstrument.geography}</span>
		{#if selectedInstrument.domicile}<span>Domicile: {selectedInstrument.domicile}</span>{/if}
		<span>Currency: {selectedInstrument.currency}</span>
		{#if selectedInstrument.structure}<span>Structure: {selectedInstrument.structure}</span>{/if}
		{#if selectedInstrument.strategy}<span>Strategy: {selectedInstrument.strategy}</span>{/if}
		{#if selectedInstrument.asset_class}<span>Asset Class: {selectedInstrument.asset_class}</span>{/if}
	</div>
</div>
{#if selectedInstrument.screening_score !== null}
	<div class="dt-section">
		<h4 class="dt-section-title">Screening</h4>
		<div class="dt-kv"><span class="dt-k">Score</span><span class="dt-v">{formatPercent(selectedInstrument.screening_score)}</span></div>
		<div class="dt-kv"><span class="dt-k">Status</span><StatusBadge status={selectedInstrument.screening_status ?? "—"} /></div>
	</div>
{/if}
{#if selectedInstrument.source === "esma" && !selectedInstrument.instrument_id}
	<div class="dt-section">
		<p class="dt-empty-text">This ESMA fund is not yet in your universe.</p>
		<Button size="sm" onclick={() => esmaImportDialogOpen = true}>Add to Universe</Button>
		{#if importError}
			<span class="dt-add-error">{importError}</span>
		{/if}
	</div>
{/if}

<!-- ESMA Import dialog -->
<ConsequenceDialog
	bind:open={esmaImportDialogOpen}
	title="Import ESMA Fund to Universe"
	impactSummary="This will add the fund to your instrument universe as a pending instrument for screening."
	requireRationale={true}
	rationaleLabel="Import justification"
	rationalePlaceholder="Why add this UCITS fund? (min 10 chars)"
	rationaleMinLength={10}
	confirmLabel="Import to Universe"
	metadata={[
		{ label: "Fund", value: selectedInstrument?.name ?? "" },
		{ label: "ISIN", value: selectedInstrument?.isin ?? "" },
		{ label: "Source", value: "ESMA" },
	]}
	onConfirm={handleEsmaImport}
/>
