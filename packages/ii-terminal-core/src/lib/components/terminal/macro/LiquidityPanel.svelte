<script lang="ts">
	interface Props {
		nfci: number | null;
		history: number[];
		loading?: boolean;
	}

	let { nfci, history, loading = false }: Props = $props();

	const gaugeWidth = $derived(nfci === null ? 50 : Math.max(0, Math.min(100, ((nfci + 2) / 4) * 100)));
	const label = $derived(nfci === null ? "-" : nfci < -0.5 ? "LOOSE" : nfci > 0.5 ? "TIGHT" : "NEUTRAL");
	const labelColor = $derived(
		nfci === null
			? "var(--terminal-fg-tertiary)"
			: nfci < -0.5
				? "var(--terminal-accent-green, #4adf86)"
				: nfci > 0.5
					? "var(--terminal-accent-red, #f87171)"
					: "var(--terminal-accent-amber)",
	);
	const sparkMin = $derived(history.length ? Math.min(...history) : 0);
	const sparkMax = $derived(history.length ? Math.max(...history) : 1);
	const sparkRange = $derived(sparkMax - sparkMin || 1);
	const zeroY = $derived(24 - ((0 - sparkMin) / sparkRange) * 22);
	const sparkPoints = $derived(
		history
			.map((value, index) => {
				const x = history.length > 1 ? (index / (history.length - 1)) * 240 : 0;
				const y = 24 - ((value - sparkMin) / sparkRange) * 22;
				return `${x},${y}`;
			})
			.join(" "),
	);
</script>

<div class="lp-root">
	<div class="lp-header">
		<span class="lp-title">LIQUIDITY</span>
		<span class="lp-sub">NFCI</span>
	</div>

	{#if loading}
		<div class="lp-loading">LOADING...</div>
	{:else}
		<div class="lp-gauge-wrap">
			<div class="lp-gauge-track">
				<div class="lp-gauge-needle" style:left={`${gaugeWidth}%`}></div>
			</div>
			<div class="lp-gauge-labels">
				<span>LOOSE</span>
				<span>TIGHT</span>
			</div>
		</div>

		<div class="lp-value-row">
			<span class="lp-nfci" style:color={labelColor}>{nfci !== null ? `${nfci >= 0 ? "+" : ""}${nfci.toFixed(3)}` : "-"}</span>
			<span class="lp-label" style:color={labelColor}>{label}</span>
		</div>

		{#if history.length >= 2}
			<svg viewBox="0 0 240 28" class="lp-spark" aria-hidden="true" preserveAspectRatio="none">
				<polyline points={sparkPoints} fill="none" stroke="var(--terminal-fg-tertiary)" stroke-width="1" vector-effect="non-scaling-stroke" />
				<line x1="0" y1={zeroY} x2="240" y2={zeroY} stroke="var(--terminal-accent-amber)" stroke-width="0.5" stroke-dasharray="2 3" opacity="0.5" />
			</svg>
			<span class="lp-spark-label">24-MONTH NFCI</span>
		{/if}
	{/if}
</div>

<style>
	.lp-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
	}
	.lp-header {
		display: flex;
		align-items: baseline;
		gap: var(--terminal-space-2);
	}
	.lp-title {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.lp-sub,
	.lp-loading,
	.lp-spark-label {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
	}
	.lp-gauge-wrap {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.lp-gauge-track {
		position: relative;
		height: 6px;
		border-radius: 2px;
		background: linear-gradient(to right, #4adf86, #f6c90e, #f87171);
	}
	.lp-gauge-needle {
		position: absolute;
		top: -2px;
		width: 2px;
		height: 10px;
		background: var(--terminal-fg-primary);
		box-shadow: 0 0 4px var(--terminal-accent-amber);
		transform: translateX(-1px);
	}
	.lp-gauge-labels,
	.lp-value-row {
		display: flex;
		justify-content: space-between;
	}
	.lp-gauge-labels {
		color: var(--terminal-fg-tertiary);
		font-size: 9px;
		letter-spacing: 0.04em;
	}
	.lp-value-row {
		align-items: baseline;
	}
	.lp-nfci {
		font-size: var(--terminal-text-14);
		font-variant-numeric: tabular-nums;
		font-weight: 600;
	}
	.lp-label {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
	}
	.lp-spark {
		width: 100%;
		height: 28px;
	}
	.lp-spark-label {
		letter-spacing: 0.04em;
	}
</style>
