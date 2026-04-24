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
		<span class="lp-title">GLOBAL LIQUIDITY · NFCI</span>
		<span class="lp-sub">24M</span>
	</div>

	{#if loading}
		<div class="lp-loading">LOADING...</div>
	{:else}
		<div class="lp-gauge-wrap">
			<div class="lp-gauge-track">
				<div class="lp-gauge-fill"></div>
				<div class="lp-gauge-labels">
					<span>LOOSE</span>
					<span>NEUTRAL</span>
					<span>TIGHT</span>
				</div>
				<div class="lp-gauge-needle" style:left={`${gaugeWidth}%`}></div>
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
		gap: 7px;
		min-height: 0;
		padding: 10px 14px;
		overflow: hidden;
		background: var(--ii-surface);
		font-family: var(--ii-font-mono);
	}
	.lp-header {
		display: flex;
		align-items: baseline;
		gap: var(--terminal-space-2);
	}
	.lp-title {
		color: var(--ii-text-muted);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.lp-sub,
	.lp-loading,
	.lp-spark-label {
		color: var(--ii-text-muted);
		font-size: 10px;
	}
	.lp-gauge-wrap {
		display: block;
	}
	.lp-gauge-track {
		position: relative;
		height: 46px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 2px;
		background: var(--ii-surface-alt);
	}
	.lp-gauge-fill {
		position: absolute;
		inset: 0;
		background: linear-gradient(
			90deg,
			rgba(61, 211, 154, 0.42) 0%,
			rgba(61, 211, 154, 0.14) 32%,
			rgba(255, 255, 255, 0.05) 50%,
			rgba(255, 92, 122, 0.14) 68%,
			rgba(255, 92, 122, 0.42) 100%
		);
	}
	.lp-gauge-needle {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 3px;
		background: var(--ii-brand-primary);
		box-shadow: 0 0 8px rgba(255, 150, 90, 0.6);
		transform: translateX(-1px);
	}
	.lp-gauge-labels,
	.lp-value-row {
		display: flex;
		justify-content: space-between;
	}
	.lp-gauge-labels {
		position: absolute;
		inset: 0;
		align-items: center;
		margin: 0;
		padding: 0 10px;
		color: var(--ii-text-muted);
		font-size: 9px;
		letter-spacing: var(--ii-terminal-tr-caps);
		pointer-events: none;
	}
	.lp-value-row {
		align-items: baseline;
	}
	.lp-nfci {
		font-size: 14px;
		font-variant-numeric: tabular-nums;
		font-weight: 700;
	}
	.lp-label {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.lp-spark {
		width: 100%;
		height: 28px;
	}
	.lp-spark-label {
		letter-spacing: 0.04em;
	}
</style>
