<!--
  StressCustomShockTab — user-defined shock form that feeds the legacy
  workspace.runStressTest method. Preserved for the Custom tab of
  StressScenarioPanel so PMs can run ad-hoc shocks on top of the
  4 preset catalog.

  Unlike the Matrix tab (which reads from the persisted construction
  run), this tab dispatches a live call and shows the immediate result
  from ``workspace.localStress``.
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { Button, formatPercent } from "@investintell/ui";

	let equityShock = $state(-20);
	let ratesShock = $state(200);
	let creditShock = $state(150);

	async function runCustomStress() {
		await workspace.runStressTest({
			equity: equityShock,
			rates: ratesShock,
			credit: creditShock,
		});
	}

	const result = $derived(workspace.localStress);
	const isRunning = $derived(workspace.isStressing);
</script>

<div class="scs-root">
	<div class="scs-form">
		<div class="scs-field">
			<label for="scs-equity">Equity shock (%)</label>
			<input
				id="scs-equity"
				type="number"
				step="1"
				bind:value={equityShock}
			/>
		</div>
		<div class="scs-field">
			<label for="scs-rates">Rates shock (bps)</label>
			<input
				id="scs-rates"
				type="number"
				step="25"
				bind:value={ratesShock}
			/>
		</div>
		<div class="scs-field">
			<label for="scs-credit">Credit shock (bps)</label>
			<input
				id="scs-credit"
				type="number"
				step="25"
				bind:value={creditShock}
			/>
		</div>
		<div class="scs-actions">
			<Button
				variant="default"
				size="sm"
				disabled={!workspace.portfolioId || isRunning}
				onclick={runCustomStress}
			>
				{isRunning ? "Running…" : "Run custom shock"}
			</Button>
		</div>
	</div>

	{#if result}
		<div class="scs-result">
			<div class="scs-result-row">
				<span class="scs-label">Portfolio drop</span>
				<span class="scs-value">{formatPercent(result.portfolioDrop / 100, 2)}</span>
			</div>
			<div class="scs-result-row">
				<span class="scs-label">Stressed Tail Loss</span>
				<span class="scs-value">
					{result.cvarStressed === null ? "—" : formatPercent(result.cvarStressed, 2)}
				</span>
			</div>
			{#if result.worstBlock}
				<div class="scs-result-row">
					<span class="scs-label">Worst block</span>
					<span class="scs-value">{result.worstBlock}</span>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.scs-root {
		display: flex;
		flex-direction: column;
		gap: 16px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.scs-form {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr auto;
		align-items: end;
		gap: 12px;
	}
	.scs-field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.scs-field label {
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-muted, #85a0bd);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.scs-field input {
		height: 30px;
		padding: 0 8px;
		font-size: 12px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-primary, #ffffff);
		font-family: inherit;
	}
	.scs-field input:focus {
		outline: none;
		border-color: var(--ii-primary, #0177fb);
	}
	.scs-actions {
		display: flex;
		align-items: center;
	}

	.scs-result {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px 14px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
	}
	.scs-result-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 16px;
		font-size: 12px;
	}
	.scs-label {
		color: var(--ii-text-muted, #85a0bd);
	}
	.scs-value {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
</style>
