<script lang="ts">
	import "@investintell/ui/styles/surfaces/screener";
	import { getContext, onDestroy } from "svelte";
	import { page } from "$app/state";
	import { PageHeader } from "@investintell/ui";
	import { createClientApiClient } from "@investintell/ii-terminal-core/api/client";
	import MarketSensitivitiesBar from "@investintell/ii-terminal-core/components/research/MarketSensitivitiesBar.svelte";
	import StyleBiasRadar from "@investintell/ii-terminal-core/components/research/StyleBiasRadar.svelte";

	interface InstrumentRead {
		instrument_id: string;
		name: string;
		ticker: string | null;
	}

	interface ResearchPoint {
		label: string;
		value: number;
		significance: "high" | "medium" | "low" | "none";
	}

	interface ResearchResponse {
		instrument_id: string;
		instrument_name: string;
		ticker: string | null;
		market_sensitivities: {
			exposures: ResearchPoint[];
			r_squared: number | null;
			systematic_risk_pct: number | null;
		};
		style_bias: {
			exposures: ResearchPoint[];
		};
	}

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let instrument = $state<InstrumentRead | null>(null);
	let research = $state<ResearchResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let controller = $state<AbortController | null>(null);

	const instrumentId = $derived(page.url.pathname.split("/")[2] ?? "");

	function abortCurrent() {
		controller?.abort();
		controller = null;
	}

	async function loadSurface(id: string) {
		abortCurrent();
		const nextController = new AbortController();
		controller = nextController;
		loading = true;
		error = null;

		try {
			const [instrumentData, researchData] = await Promise.all([
				api.get<InstrumentRead>(`/instruments/${id}`, undefined, { signal: nextController.signal }),
				api.get<ResearchResponse>(`/research/funds/${id}`, undefined, { signal: nextController.signal }),
			]);
			instrument = instrumentData;
			research = researchData;
		} catch (cause: unknown) {
			if (cause instanceof DOMException && cause.name === "AbortError") return;
			error = cause instanceof Error ? cause.message : "Failed to load the research surface.";
			instrument = null;
			research = null;
		} finally {
			if (controller === nextController) controller = null;
			loading = false;
		}
	}

	$effect(() => {
		if (instrumentId) {
			loadSurface(instrumentId);
		}
		return () => abortCurrent();
	});

	onDestroy(() => abortCurrent());
</script>

<svelte:head>
	<title>Fund Research</title>
</svelte:head>

<div class="fund-research-page">
	<PageHeader title={instrument?.name ?? "Fund Research"} subtitle={instrument?.ticker ?? "Single-fund research view"}>
		{#snippet actions()}
			<a class="cta-button" href={`/allocation/moderate?candidate=${instrumentId}`}>Add to Model Portfolio</a>
			<a class="cta-button cta-button--ghost" href={`/live?watch=${instrumentId}`}>Watchlist</a>
		{/snippet}
	</PageHeader>

	{#if error}
		<div class="error-banner">{error}</div>
	{/if}

	<div class="fund-grid">
		<MarketSensitivitiesBar
			exposures={research?.market_sensitivities.exposures ?? []}
			loading={loading}
			error={error}
		/>
		<StyleBiasRadar exposures={research?.style_bias.exposures ?? []} loading={loading} error={error} />
	</div>
</div>

<style>
	.fund-research-page {
		display: flex;
		flex-direction: column;
		gap: 20px;
		padding: 24px;
		min-height: 100%;
		background:
			radial-gradient(circle at top left, color-mix(in srgb, var(--ii-brand-primary) 10%, transparent), transparent 34%),
			linear-gradient(180deg, var(--ii-surface), color-mix(in srgb, var(--ii-surface-elevated) 84%, transparent));
	}

	.fund-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
		gap: 20px;
	}

	.cta-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 10px 14px;
		border-radius: 999px;
		border: 1px solid color-mix(in srgb, var(--ii-brand-primary) 60%, transparent);
		background: color-mix(in srgb, var(--ii-brand-primary) 18%, transparent);
		color: var(--ii-text-secondary);
		text-decoration: none;
		font-size: 0.875rem;
	}

	.cta-button--ghost {
		background: transparent;
		border-color: var(--ii-border);
	}

	.error-banner {
		padding: 12px 14px;
		border-radius: 12px;
		border: 1px solid color-mix(in srgb, #ef4444 40%, transparent);
		background: color-mix(in srgb, #ef4444 10%, transparent);
		color: var(--ii-text-secondary);
	}

	@media (max-width: 1040px) {
		.fund-grid {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 640px) {
		.fund-research-page {
			padding: 16px;
		}
	}
</style>
