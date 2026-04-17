<!--
  RiskBudgetSlider — PR-A13 wrapper around CalibrationSliderField that
  adds profile-default affordances: a "Default for {profile}: X.XX%" hint
  and a conditional "Reset to {profile} default" link when the current
  value drifts from the profile default.

  Vocabulary discipline (metric-translators.ts convention): the operator
  surface uses "Tail loss budget", never raw "CVaR 95%". "CVaR" remains
  reserved for the advanced / result chips.

  No $bindable: callback contract matches CalibrationSliderField so the
  parent owns the draft.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import CalibrationSliderField from "./CalibrationSliderField.svelte";
	import { profileLabel } from "$lib/util/profile-defaults";

	interface Props {
		value: number;
		profileDefault: number;
		profile: string | null | undefined;
		onChange: (v: number) => void;
		originalValue?: number;
	}

	let {
		value,
		profileDefault,
		profile,
		onChange,
		originalValue,
	}: Props = $props();

	const label = $derived(profileLabel(profile));
	const isDrifted = $derived(Math.abs(value - profileDefault) > 1e-6);
</script>

<div class="rbs-root">
	<CalibrationSliderField
		id="cp-cvar-limit"
		label="Tail loss budget"
		description="Maximum tail loss (95% confidence) the portfolio may carry."
		{value}
		{onChange}
		min={0.005}
		max={0.25}
		step={0.0025}
		displayFormat="percent"
		digits={2}
		edgeLabels={["Tighter", "Looser"]}
		accent="danger"
		{originalValue}
	/>

	<div class="rbs-footer">
		<span class="rbs-hint" title={`Institutional starting default for the ${label} profile`}>
			Default for {label}: {formatPercent(profileDefault, 2)}
		</span>
		{#if isDrifted}
			<button type="button" class="rbs-reset" onclick={() => onChange(profileDefault)}>
				Reset to {label} default
			</button>
		{/if}
	</div>
</div>

<style>
	.rbs-root {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.rbs-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding-top: 2px;
	}
	.rbs-hint {
		font-size: 10px;
		color: var(--terminal-fg-muted);
		font-family: var(--terminal-font-mono);
		letter-spacing: 0.02em;
	}
	.rbs-reset {
		font-size: 10px;
		font-weight: 600;
		font-family: var(--terminal-font-mono);
		color: var(--terminal-accent-amber);
		background: transparent;
		border: none;
		border-bottom: 1px solid var(--terminal-accent-amber);
		padding: 0 0 1px 0;
		cursor: pointer;
		letter-spacing: 0.02em;
	}
	.rbs-reset:hover {
		color: var(--terminal-fg-primary);
		border-bottom-color: var(--terminal-fg-primary);
	}
	.rbs-reset:focus-visible {
		outline: 2px solid var(--terminal-accent-amber);
		outline-offset: 2px;
	}
</style>
