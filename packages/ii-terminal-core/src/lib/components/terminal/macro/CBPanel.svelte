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
		gap: 1px;
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}
	.cb-header,
	.cb-loading,
	.cb-empty {
		padding: var(--terminal-space-2) var(--terminal-space-3);
	}
	.cb-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.cb-loading,
	.cb-empty {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}
	.cb-row {
		display: grid;
		grid-template-columns: 44px 58px 58px 58px 30px;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: 3px var(--terminal-space-2);
	}
	.cb-row:hover {
		background: var(--terminal-bg-panel-raised);
	}
	.cb-bank {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
	}
	.cb-date,
	.cb-rate {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-10);
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
		font-size: var(--terminal-text-10);
		font-weight: 600;
	}
	.cb-days {
		color: var(--terminal-fg-tertiary);
		font-size: 9px;
	}
</style>
