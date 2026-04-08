<!--
  AnalysisFilters — filter rail content for the Analysis page. The time
  window radio group is shared across all three analysis groups; the rest
  of the rail swaps based on `group` (returns-risk / holdings / peer).

  Holdings and peer sections render scaffolding only — Phases 6 and 7 will
  wire them to real state.
-->
<script lang="ts">
	type Window = "1y" | "3y" | "5y" | "max";
	type Group = "returns-risk" | "holdings" | "peer";

	interface Props {
		group: Group;
		window: Window;
		onWindowChange: (w: Window) => void;
	}

	let { group, window, onWindowChange }: Props = $props();

	const WINDOWS: Window[] = ["1y", "3y", "5y", "max"];
</script>

<div class="af-section">
	<h4>Time Window</h4>
	<div class="af-radio-group">
		{#each WINDOWS as w (w)}
			<label class:active={window === w}>
				<input
					type="radio"
					name="window"
					value={w}
					checked={window === w}
					onchange={() => onWindowChange(w)}
				/>
				{w.toUpperCase()}
			</label>
		{/each}
	</div>
</div>

{#if group === "returns-risk"}
	<div class="af-section">
		<h4>Benchmarks</h4>
		<label><input type="checkbox" checked /> S&amp;P 500</label>
		<label><input type="checkbox" /> MSCI World</label>
		<label><input type="checkbox" /> Peer median</label>
	</div>
	<div class="af-section">
		<h4>Display</h4>
		<label><input type="checkbox" checked /> Market phase shading</label>
		<label><input type="checkbox" checked /> Drawdown overlay</label>
	</div>
{:else if group === "holdings"}
	<div class="af-section">
		<h4>Holdings lens</h4>
		<label><input type="radio" name="lens" checked /> Top 25 by weight</label>
		<label><input type="radio" name="lens" /> Top sectors</label>
		<label><input type="radio" name="lens" /> Geography</label>
	</div>
	<div class="af-section">
		<h4>Style Drift</h4>
		<label>Quarters back: <input type="number" value="8" min="1" max="20" /></label>
	</div>
{:else}
	<div class="af-section">
		<h4>Peer Universe</h4>
		<label><input type="checkbox" checked /> Same strategy</label>
		<label><input type="checkbox" checked /> Same domicile</label>
		<label><input type="checkbox" /> Same size bucket</label>
	</div>
	<div class="af-section">
		<h4>Institutional Reveal</h4>
		<label><input type="checkbox" checked /> Endowments</label>
		<label><input type="checkbox" checked /> Family Offices</label>
		<label><input type="checkbox" /> Sovereign Funds</label>
	</div>
{/if}

<style>
	.af-section {
		margin-bottom: 24px;
	}
	.af-section h4 {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
		margin: 0 0 10px;
		font-weight: 600;
	}
	.af-section label {
		display: block;
		padding: 6px 0;
		font-size: 12px;
		color: var(--ii-text-primary);
		cursor: pointer;
	}
	.af-section input[type="checkbox"],
	.af-section input[type="radio"] {
		margin-right: 8px;
		accent-color: var(--ii-brand-accent);
	}
	.af-radio-group {
		display: flex;
		gap: 4px;
	}
	.af-radio-group label {
		flex: 1;
		text-align: center;
		padding: 6px 8px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
	}
	.af-radio-group label.active {
		background: var(--ii-brand-accent);
		color: white;
		border-color: var(--ii-brand-accent);
	}
	.af-radio-group input {
		display: none;
	}
</style>
