<!--
  TradeLog -- recent trade tickets for the active portfolio.

  Fetches from GET /model-portfolios/{id}/trade-tickets?page_size=20.
  Shows ticker, BUY/SELL badge, delta weight, and execution time.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatPercent, formatTime } from "@investintell/ui";
	import { createClientApiClient } from "../../../api/client";

	interface Props {
		portfolioId: string | null;
	}

	let { portfolioId }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	/** Instrument ID -> ticker map for resolution */
	let instrumentMap = $state<Map<string, string>>(new Map());

	interface TradeTicket {
		id: string;
		instrument_id: string;
		action: string;
		delta_weight: number;
		executed_at: string;
		execution_venue: string | null;
		fill_status: string;
	}

	let tickets = $state<TradeTicket[]>([]);
	let loading = $state(true);

	// Fetch instrument map for ticker resolution
	$effect(() => {
		const _pid = portfolioId;
		if (!_pid) return;
		let cancelled = false;
		api.get<Array<{ instrument_id: string; ticker: string | null; name: string }>>(
			"/instruments",
		)
			.then((instruments) => {
				if (cancelled) return;
				const m = new Map<string, string>();
				for (const inst of instruments) {
					if (inst.ticker) {
						m.set(inst.instrument_id, inst.ticker);
					}
				}
				instrumentMap = m;
			})
			.catch(() => {});
		return () => { cancelled = true; };
	});

	$effect(() => {
		const pid = portfolioId;
		let cancelled = false;
		loading = true;

		if (!pid) {
			tickets = [];
			loading = false;
			return;
		}

		api.get<{
			items: TradeTicket[];
			total: number;
			page: number;
			page_size: number;
			has_next: boolean;
		}>(`/model-portfolios/${pid}/trade-tickets?page_size=20`)
			.then((res) => {
				if (!cancelled) {
					tickets = res.items;
					loading = false;
				}
			})
			.catch(() => {
				if (!cancelled) {
					tickets = [];
					loading = false;
				}
			});

		return () => { cancelled = true; };
	});

	function displayTime(iso: string): string {
		return formatTime(iso);
	}

	function resolveTicker(instrumentId: string): string {
		return instrumentMap.get(instrumentId) ?? instrumentId.slice(0, 8);
	}
</script>

<div class="tl-root">
	<div class="tl-header">
		<span class="tl-label">TRADE LOG</span>
		<span class="tl-count">{tickets.length}</span>
	</div>

	<div class="tl-body">
		{#if loading}
			<div class="tl-empty">Loading...</div>
		{:else if tickets.length === 0}
			<div class="tl-empty">No trades executed</div>
		{:else}
			{#each tickets as t (t.id)}
				{@const isBuy = t.action.toLowerCase() === "buy"}
				<div class="tl-row">
					<span class="tl-ticker">{resolveTicker(t.instrument_id)}</span>
					<span class="tl-badge" class:tl-badge--buy={isBuy} class:tl-badge--sell={!isBuy}>
						{t.action.toUpperCase()}
					</span>
					<span class="tl-delta" class:tl-delta--buy={isBuy} class:tl-delta--sell={!isBuy}>
						{isBuy ? "+" : ""}{formatPercent(t.delta_weight, 1)}
					</span>
					<span class="tl-time">{displayTime(t.executed_at)}</span>
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.tl-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.tl-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.tl-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.tl-count {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		color: var(--terminal-fg-tertiary);
	}

	.tl-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.tl-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 80px;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
	}

	.tl-row {
		display: grid;
		grid-template-columns: 1fr auto auto auto;
		align-items: center;
		gap: 6px;
		padding: var(--terminal-space-1) var(--terminal-space-2);
		height: 28px;
		border-bottom: 1px solid var(--terminal-fg-muted);
	}

	.tl-ticker {
		font-size: var(--terminal-text-11);
		font-weight: 700;
		color: var(--terminal-fg-primary);
		letter-spacing: var(--terminal-tracking-caps);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.tl-badge {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: 1px 6px;
		white-space: nowrap;
	}

	.tl-badge--buy {
		color: var(--terminal-bg-void);
		background: var(--terminal-status-success);
	}

	.tl-badge--sell {
		color: var(--terminal-bg-void);
		background: var(--terminal-status-error);
	}

	.tl-delta {
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
		text-align: right;
		white-space: nowrap;
	}

	.tl-delta--buy {
		color: var(--terminal-status-success);
	}

	.tl-delta--sell {
		color: var(--terminal-status-error);
	}

	.tl-time {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
</style>
