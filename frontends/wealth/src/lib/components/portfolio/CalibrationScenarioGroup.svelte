<!--
  CalibrationScenarioGroup — 4 stress-scenario checkboxes for the
  Basic tier ``stress_scenarios_active`` field (DL7 canonical set).

  Explicit ``value`` + ``onChange`` props so the parent keeps the
  draft as the single source of truth.
-->
<script lang="ts">
	import type { StressScenarioId } from "$lib/types/portfolio-calibration";

	interface Option {
		value: StressScenarioId;
		label: string;
	}

	interface Props {
		label: string;
		description?: string;
		value: readonly StressScenarioId[];
		onChange: (value: StressScenarioId[]) => void;
		options: readonly Option[];
		disabled?: boolean;
	}

	let {
		label,
		description,
		value,
		onChange,
		options,
		disabled = false,
	}: Props = $props();

	function toggle(id: StressScenarioId) {
		if (value.includes(id)) {
			onChange(value.filter((v) => v !== id));
		} else {
			onChange([...value, id]);
		}
	}
</script>

<div class="csg-root" class:csg-root--disabled={disabled}>
	<div class="csg-header">
		<span class="csg-label">{label}</span>
		<span class="csg-count">{value.length}/{options.length}</span>
	</div>
	{#if description}
		<p class="csg-description">{description}</p>
	{/if}
	<div class="csg-grid">
		{#each options as opt (opt.value)}
			{@const checked = value.includes(opt.value)}
			<button
				type="button"
				class="csg-chip"
				class:csg-chip--on={checked}
				{disabled}
				onclick={() => toggle(opt.value)}
				aria-pressed={checked}
			>
				<span class="csg-chip-box">
					{#if checked}
						<span class="csg-chip-tick">✓</span>
					{/if}
				</span>
				<span class="csg-chip-label">{opt.label}</span>
			</button>
		{/each}
	</div>
</div>

<style>
	.csg-root {
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.csg-root--disabled {
		opacity: 0.55;
	}

	.csg-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
	}
	.csg-label {
		font-size: 13px;
		font-weight: 600;
		color: var(--ii-text-primary, #ffffff);
	}
	.csg-count {
		font-size: 11px;
		font-weight: 700;
		color: var(--ii-text-muted, #85a0bd);
		font-variant-numeric: tabular-nums;
	}
	.csg-description {
		margin: 0;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		line-height: 1.4;
	}

	.csg-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.csg-chip {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 8px 10px;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 8px;
		background: transparent;
		cursor: pointer;
		color: var(--ii-text-muted, #85a0bd);
		font-family: inherit;
		font-size: 12px;
		font-weight: 500;
		text-align: left;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.csg-chip:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.03);
		color: var(--ii-text-primary, #ffffff);
	}
	.csg-chip--on {
		background: rgba(1, 119, 251, 0.08);
		border-color: var(--ii-primary, #0177fb);
		color: var(--ii-text-primary, #ffffff);
	}
	.csg-chip-box {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border-radius: 4px;
		border: 1px solid rgba(255, 255, 255, 0.28);
		flex-shrink: 0;
	}
	.csg-chip--on .csg-chip-box {
		background: var(--ii-primary, #0177fb);
		border-color: var(--ii-primary, #0177fb);
	}
	.csg-chip-tick {
		font-size: 11px;
		font-weight: 700;
		color: #ffffff;
		line-height: 1;
	}
	.csg-chip-label {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
