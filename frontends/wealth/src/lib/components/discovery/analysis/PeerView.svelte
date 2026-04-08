<!--
  PeerView — Peer Analysis group for the standalone Discovery Analysis page
  (Phase 7.4). Composes 3 ChartCards inside AnalysisGrid:

    1. Risk / Return vs Peers   (PeerScatterChart, span=2)
    2. Sharpe Ranking           (PeerRankingLadder)
    3. Institutional Portfolio Reveal (InstitutionalRevealMatrix, span=3)

  Fetches `/funds/{id}/analysis/peers` and `/funds/{id}/analysis/institutional-
  reveal` in parallel on mount / fundId change. Both effects use AbortController
  cleanup. The institutional reveal is permitted to be empty (CIK backfill of
  curated_institutions is non-blocking) — in that case the third card renders
  an explanatory empty state instead of the heatmap.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { ChartCard, AnalysisGrid } from "@investintell/ui";
	import PeerScatterChart from "$lib/components/charts/discovery/PeerScatterChart.svelte";
	import PeerRankingLadder from "$lib/components/charts/discovery/PeerRankingLadder.svelte";
	import InstitutionalRevealMatrix from "$lib/components/charts/discovery/InstitutionalRevealMatrix.svelte";
	import {
		fetchPeerComparison,
		fetchInstitutionalReveal,
	} from "$lib/discovery/analysis-api";

	interface Peer {
		external_id: string;
		name: string;
		ticker?: string | null;
		strategy_label?: string | null;
		aum_usd?: number | null;
		expense_ratio_pct?: number | null;
		volatility_1y: number | null;
		sharpe_1y: number | null;
		max_drawdown_1y?: number | null;
		cvar_95?: number | null;
		is_subject: boolean;
	}
	interface PeerPayload {
		peers: Peer[];
		subject: Peer | null;
	}
	interface Institution {
		institution_id: string;
		name: string;
		category: string;
		total_overlap?: number;
		total_value?: number;
	}
	interface RevealHolding {
		cusip: string;
		issuer_name: string;
		pct_of_nav?: number;
	}
	interface RevealPayload {
		institutions: Institution[];
		overlap_matrix: Record<string, Record<string, number>>;
		holdings: RevealHolding[];
	}

	interface Props {
		fundId: string;
	}

	let { fundId }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let peerData = $state<PeerPayload | null>(null);
	let revealData = $state<RevealPayload | null>(null);
	let peerError = $state<string | null>(null);

	$effect(() => {
		const id = fundId;
		if (!id || !getToken) return;
		const ctrl = new AbortController();
		peerData = null;
		revealData = null;
		peerError = null;

		Promise.all([
			fetchPeerComparison(getToken, id, ctrl.signal),
			fetchInstitutionalReveal(getToken, id, ctrl.signal).catch(() => null),
		])
			.then(([peers, reveal]) => {
				peerData = peers as PeerPayload;
				revealData = reveal as RevealPayload | null;
			})
			.catch((e: unknown) => {
				if (e instanceof Error && e.name !== "AbortError") {
					peerError = e.message;
				}
			});
		return () => ctrl.abort();
	});

	const hasPeers = $derived((peerData?.peers?.length ?? 0) > 0);
	const hasInstitutions = $derived(
		(revealData?.institutions?.length ?? 0) > 0 &&
			(revealData?.holdings?.length ?? 0) > 0,
	);
</script>

{#if peerError}
	<div class="pv-error">Failed to load peer analysis: {peerError}</div>
{:else if !peerData}
	<div class="pv-loading">Loading Peer Analysis…</div>
{:else if !hasPeers}
	<div class="pv-empty">
		<strong>No peer data available</strong>
		<p>
			This fund has no comparable peers in the catalog with sufficient risk
			metrics. Peer cohorts require at least 1y of return history and a
			matching strategy label.
		</p>
	</div>
{:else}
	<AnalysisGrid>
		<ChartCard
			title="Risk / Return vs Peers"
			subtitle="Volatility vs risk-adjusted return"
			span={2}
			minHeight="420px"
		>
			<PeerScatterChart peers={peerData.peers} />
		</ChartCard>

		<ChartCard
			title="How this fund ranks vs peers"
			subtitle="Top 20 by risk-adjusted return (1y)"
			minHeight="420px"
		>
			<PeerRankingLadder peers={peerData.peers} />
		</ChartCard>

		<ChartCard
			title="Institutional Portfolio Reveal"
			subtitle={hasInstitutions
				? "Curated institutions holding the subject fund's top positions"
				: "Curated institution overlap"}
			span={3}
			minHeight="580px"
		>
			{#if hasInstitutions && revealData}
				<InstitutionalRevealMatrix
					institutions={revealData.institutions}
					holdings={revealData.holdings}
					matrix={revealData.overlap_matrix}
				/>
			{:else}
				<div class="pv-sub-empty">
					<strong>Institutional reveal data unavailable</strong>
					<p>
						This view cross-references the subject fund's holdings against
						the latest 13F filings of a curated set of endowments, family
						offices, foundations, and sovereign funds. It requires CIK
						matching of curated institutions to SEC 13F filers — backfill
						is currently pending.
					</p>
				</div>
			{/if}
		</ChartCard>
	</AnalysisGrid>
{/if}

<style>
	.pv-error,
	.pv-loading,
	.pv-empty,
	.pv-sub-empty {
		padding: 40px;
		text-align: center;
		color: var(--ii-text-muted);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
	}
	.pv-sub-empty {
		padding: 32px;
	}
	.pv-empty strong,
	.pv-sub-empty strong {
		display: block;
		font-size: 14px;
		color: var(--ii-text-primary);
		margin-bottom: 8px;
	}
	.pv-empty p,
	.pv-sub-empty p {
		max-width: 520px;
		margin: 0 auto;
		font-size: 12px;
		line-height: 1.6;
	}
</style>
