<script lang="ts">
	export interface CbEvent {
		centralBank: string;
		meetingDate: string;
		currentRatePct: number;
		expectedChangeBps: number;
	}

	interface Props {
		events: CbEvent[];
		loading?: boolean;
	}

	let { events, loading = false }: Props = $props();

	function changeBadge(bps: number): { text: string; color: string } {
		if (bps === 0) return { text: "HOLD", color: "var(--terminal-fg-tertiary)" };
		if (bps > 0) return { text: `+${bps}bp`, color: "var(--terminal-accent-red, #f87171)" };
		return { text: `${bps}bp`, color: "var(--terminal-accent-green, #4adf86)" };
	}

	function fmtDate(iso: string): string {
		const d = new Date(`${iso}T00:00:00`);
		return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
	}

	function daysUntil(iso: string): number {
		const d = new Date(`${iso}T00:00:00`);
		return Math.ceil((d.getTime() - Date.now()) / 86_400_000);
	}
</script>

<div class="cb-root">
	<div class="cb-header"><span class="cb-title">CENTRAL BANKS</span></div>

	{#if loading}
		<div class="cb-loading">LOADING...</div>
	{:else if events.length === 0}
		<div class="cb-empty">No upcoming meetings</div>
	{:else}
		{#each events as ev (ev.centralBank + ev.meetingDate)}
			{@const badge = changeBadge(ev.expectedChangeBps)}
			<div class="cb-row">
				<span class="cb-bank">{ev.centralBank}</span>
				<span class="cb-date">{fmtDate(ev.meetingDate)}</span>
				<span class="cb-rate">{ev.currentRatePct.toFixed(2)}%</span>
				<span class="cb-badge" style:color={badge.color}>{badge.text}</span>
				<span class="cb-days">{daysUntil(ev.meetingDate)}d</span>
			</div>
		{/each}
	{/if}
</div>

<style>
	.cb-root {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		background: var(--ii-surface);
		font-family: var(--ii-font-mono);
	}
	.cb-header,
	.cb-loading,
	.cb-empty {
		padding: 10px 14px 8px;
	}
	.cb-title {
		color: var(--ii-text-primary);
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.14em;
	}
	.cb-loading,
	.cb-empty {
		color: var(--ii-text-muted);
		font-size: 10px;
	}
	.cb-row {
		display: grid;
		grid-template-columns: 54px 58px 1fr 62px 34px;
		align-items: center;
		gap: 10px;
		padding: 6px 14px;
		border-top: 1px solid var(--ii-terminal-hair);
		background: var(--ii-surface-alt);
	}
	.cb-row:hover {
		background: var(--ii-surface);
	}
	.cb-bank {
		color: var(--ii-text-primary);
		font-size: 11px;
		font-weight: 700;
	}
	.cb-date,
	.cb-rate {
		color: var(--ii-text-secondary);
		font-size: 10px;
	}
	.cb-rate,
	.cb-badge,
	.cb-days {
		text-align: right;
	}
	.cb-rate {
		font-variant-numeric: tabular-nums;
	}
	.cb-badge {
		font-size: 10px;
		font-weight: 700;
	}
	.cb-days {
		color: var(--ii-text-muted);
		font-size: 9px;
	}
</style>
