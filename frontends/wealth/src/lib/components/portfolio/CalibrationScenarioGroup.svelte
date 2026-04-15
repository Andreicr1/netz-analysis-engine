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
		originalValue?: readonly StressScenarioId[];
	}

	let {
		label,
		description,
		value,
		onChange,
		options,
		disabled = false,
		originalValue,
	}: Props = $props();

	const originalSet = $derived(
		originalValue ? new Set(originalValue) : null,
	);
	const draftSet = $derived(new Set(value));

	const added = $derived.by(() =>
		originalSet ? value.filter((v) => !originalSet.has(v)) : [],
	);
	const removed = $derived.by(() =>
		originalSet ? [...originalSet].filter((v) => !draftSet.has(v)) : [],
	);
	const showOriginal = $derived(
		originalValue !== undefined && (added.length > 0 || removed.length > 0),
	);

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
		{#if showOriginal}
			{#if added.length > 0}
				<span
					class="csg-original-chip csg-original-chip--added"
					title="Cenários adicionados desde a última construção"
				>
					+{added.length} {added.length === 1 ? "cenário" : "cenários"}
				</span>
			{/if}
			{#if removed.length > 0}
				<span
					class="csg-original-chip csg-original-chip--removed"
					title="Cenários removidos desde a última construção"
				>
					−{removed.length} {removed.length === 1 ? "cenário" : "cenários"}
				</span>
			{/if}
		{/if}
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
		font-family: var(--terminal-font-mono);
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
		color: var(--terminal-fg-primary);
	}
	.csg-count {
		font-size: 11px;
		font-weight: 700;
		color: var(--terminal-fg-muted);
		font-variant-numeric: tabular-nums;
	}
	.csg-description {
		margin: 0;
		font-size: 11px;
		color: var(--terminal-fg-muted);
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
		border: var(--terminal-border-hairline);
		background: transparent;
		cursor: pointer;
		color: var(--terminal-fg-muted);
		font-family: inherit;
		font-size: 12px;
		font-weight: 500;
		text-align: left;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}
	.csg-chip:hover:not(:disabled) {
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-fg-primary);
	}
	.csg-chip--on {
		background: color-mix(in srgb, var(--terminal-accent-amber) 10%, transparent);
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-fg-primary);
	}
	.csg-chip-box {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border: 1px solid var(--terminal-fg-tertiary);
		flex-shrink: 0;
	}
	.csg-chip--on .csg-chip-box {
		background: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}
	.csg-chip-tick {
		font-size: 11px;
		font-weight: 700;
		color: var(--terminal-fg-inverted);
		line-height: 1;
	}
	.csg-chip-label {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.csg-original-chip {
		margin-left: 8px;
		padding: 2px 6px;
		font-size: 10px;
		font-weight: 500;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		border: 1px solid var(--terminal-fg-muted);
		border-radius: 2px;
		font-family: var(--terminal-font-mono);
		white-space: nowrap;
	}
	.csg-original-chip--added {
		color: var(--terminal-status-success);
		background: var(--terminal-bg-panel-raised);
	}
	.csg-original-chip--removed {
		color: var(--terminal-status-warn);
		background: var(--terminal-bg-panel-raised);
	}
</style>
