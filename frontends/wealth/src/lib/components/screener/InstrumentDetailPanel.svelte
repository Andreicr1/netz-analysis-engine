<!--
  Instrument detail context panel — screening info + send to review.
-->
<script lang="ts">
	import "./screener.css";
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { Button, StatusBadge, ConsequenceDialog, formatAUM, formatPercent } from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { InstrumentSearchItem } from "$lib/types/screening";
	import { SOURCE_LABELS } from "$lib/types/screening";

	interface Props {
		selectedInstrument: InstrumentSearchItem;
	}

	let { selectedInstrument }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let reviewDialogOpen = $state(false);
	let sendingToReview = $state(false);
	let reviewError = $state<string | null>(null);

	async function handleSendToReview(payload: ConsequenceDialogPayload) {
		if (!selectedInstrument) return;
		sendingToReview = true;
		reviewError = null;
		try {
			const api = createClientApiClient(getToken);
			let instrumentId = selectedInstrument.instrument_id;

			// For external instruments not yet imported, import first
			if (!instrumentId) {
				const identifier = selectedInstrument.isin || selectedInstrument.ticker;
				if (!identifier) {
					reviewError = "Cannot import: no ISIN or ticker available.";
					return;
				}
				const imported = await api.post<{ instrument_id: string }>(`/screener/import/${identifier}`, {});
				instrumentId = imported.instrument_id;
			}

			if (!instrumentId) {
				reviewError = "Cannot create DD report: instrument ID not available.";
				return;
			}

			// Create DD Report
			const ddReport = await api.post<{ id: string }>(`/dd-reports/funds/${instrumentId}`, {});
			reviewDialogOpen = false;
			goto(`/dd-reports/${instrumentId}/${ddReport.id}`);
		} catch (e) {
			reviewError = e instanceof Error ? e.message : "Failed to send to review";
		} finally {
			sendingToReview = false;
		}
	}

	function sourceBadgeClass(source: string): string {
		switch (source) {
			case "internal": return "source-badge--internal";
			case "esma": return "source-badge--european";
			case "sec": return "source-badge--us-registered";
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
		<span class="source-badge {sourceBadgeClass(selectedInstrument.source)}">{SOURCE_LABELS[selectedInstrument.source] ?? selectedInstrument.source}</span>
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
<div class="dt-section">
	{#if !selectedInstrument.instrument_id && (selectedInstrument.source === "esma" || selectedInstrument.source === "sec")}
		<p class="dt-empty-text">This {selectedInstrument.source === "esma" ? "European fund" : "US fund"} is not yet in your universe.</p>
	{/if}
	<Button size="sm" onclick={() => reviewDialogOpen = true} disabled={sendingToReview}>
		{sendingToReview ? "Sending…" : "Send to Review"}
	</Button>
	{#if reviewError}
		<span class="dt-add-error">{reviewError}</span>
	{/if}
</div>

<!-- Send to Review dialog -->
<ConsequenceDialog
	bind:open={reviewDialogOpen}
	title="Send to DD Review"
	impactSummary={!selectedInstrument.instrument_id && (selectedInstrument.source === "esma" || selectedInstrument.source === "sec")
		? "This instrument will be imported to your universe and a DD Report will be created for committee review."
		: "A DD Report will be created for this instrument for committee review."}
	requireRationale={true}
	rationaleLabel="Review justification"
	rationalePlaceholder="Why should this instrument undergo due diligence review? (min 10 chars)"
	rationaleMinLength={10}
	confirmLabel="Send to Review"
	metadata={[
		{ label: "Instrument", value: selectedInstrument?.name ?? "" },
		{ label: "Ticker", value: selectedInstrument?.ticker ?? "—" },
		{ label: "ISIN", value: selectedInstrument?.isin ?? "—" },
	]}
	onConfirm={handleSendToReview}
/>
