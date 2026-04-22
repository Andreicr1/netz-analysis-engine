<script lang="ts">
	interface Props {
		symbol: string;
		name: string;
		lastValue: number | null;
		changePct: number | null;
		unit: string;
		sparkline: number[];
		onclick?: () => void;
	}

	let { symbol, name, lastValue, changePct, unit, sparkline, onclick }: Props = $props();

	const changePositive = $derived(changePct !== null && changePct > 0);
	const changeNegative = $derived(changePct !== null && changePct < 0);
	const sparklinePoints = $derived.by(() => {
		if (sparkline.length < 2) return "";
		const min = Math.min(...sparkline);
		const max = Math.max(...sparkline);
		const range = max - min || 1;
		return sparkline
			.map((v, i) => `${(i / (sparkline.length - 1)) * 80},${24 - ((v - min) / range) * 22}`)
			.join(" ");
	});

	function fmtValue(v: number | null, u: string): string {
		if (v === null) return "-";
		if (u === "%") return `${v.toFixed(2)}%`;
		if (u === "bps") return `${v.toFixed(2)}bp`;
		return v.toFixed(u === "idx" ? 0 : 2);
	}

	function fmtChange(c: number | null): string {
		if (c === null) return "";
		return `${c > 0 ? "+" : ""}${c.toFixed(2)}%`;
	}
</script>

<button type="button" class="mc-root" {onclick} aria-label="{name} {fmtValue(lastValue, unit)}">
	<div class="mc-head">
		<span class="mc-symbol">{symbol}</span>
		<span class="mc-name">{name}</span>
	</div>

	<div class="mc-spark">
		{#if sparkline.length >= 2}
			<svg viewBox="0 0 80 24" preserveAspectRatio="none" aria-hidden="true">
				<polyline
					points={sparklinePoints}
					fill="none"
					stroke={changePositive
						? "var(--terminal-accent-green, #4adf86)"
						: changeNegative
							? "var(--terminal-accent-red, #f87171)"
							: "var(--terminal-fg-tertiary)"}
					stroke-width="1"
					vector-effect="non-scaling-stroke"
				/>
			</svg>
		{/if}
	</div>

	<div class="mc-nums">
		<span class="mc-value">{fmtValue(lastValue, unit)}</span>
		<span class="mc-change" class:mc-change--up={changePositive} class:mc-change--dn={changeNegative}>
			{fmtChange(changePct)}
		</span>
	</div>
</button>

<style>
	.mc-root {
		display: grid;
		grid-template-columns: 1fr 80px 100px;
		align-items: center;
		gap: 0;
		width: 100%;
		padding: 3px var(--terminal-space-2);
		background: transparent;
		border: none;
		color: inherit;
		font-family: var(--terminal-font-mono);
		text-align: left;
		cursor: pointer;
		transition: background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.mc-root:hover {
		background: var(--terminal-bg-panel-raised);
	}
	.mc-root:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -1px;
	}
	.mc-head,
	.mc-nums {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}
	.mc-symbol {
		overflow: hidden;
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mc-name {
		overflow: hidden;
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mc-spark {
		width: 80px;
		height: 24px;
	}
	.mc-spark svg {
		width: 100%;
		height: 100%;
	}
	.mc-nums {
		align-items: flex-end;
	}
	.mc-value {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}
	.mc-change {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
	}
	.mc-change--up {
		color: var(--terminal-accent-green, #4adf86);
	}
	.mc-change--dn {
		color: var(--terminal-accent-red, #f87171);
	}
</style>
