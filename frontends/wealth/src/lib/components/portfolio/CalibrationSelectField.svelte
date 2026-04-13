<!--
  CalibrationSelectField — dropdown version of CalibrationSliderField,
  used for enum-valued knobs (mandate, regime_override, cvar_level
  segmented, etc.).

  Uses explicit ``value`` + ``onChange`` props (no bindable) so the
  parent can transform — e.g. ``"auto"`` sentinel → ``null`` — without
  touching internal state.
-->
<script lang="ts">
	interface Option {
		value: string;
		label: string;
	}

	interface Props {
		id: string;
		label: string;
		description?: string;
		value: string;
		onChange: (value: string) => void;
		options: readonly Option[];
		placeholder?: string;
		disabled?: boolean;
	}

	let {
		id,
		label,
		description,
		value,
		onChange,
		options,
		placeholder = "Select...",
		disabled = false,
	}: Props = $props();
</script>

<div class="csf-root" class:csf-root--disabled={disabled}>
	<div class="csf-header">
		<label class="csf-label" for={id}>{label}</label>
	</div>
	{#if description}
		<p class="csf-description">{description}</p>
	{/if}
	<div class="csf-control">
		<select
			{id}
			class="csf-select"
			{disabled}
			value={value}
			onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value)}
		>
			{#each options as opt (opt.value)}
				<option value={opt.value}>{opt.label}</option>
			{/each}
		</select>
	</div>
</div>

<style>
	.csf-root {
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-family: var(--terminal-font-mono);
	}
	.csf-root--disabled {
		opacity: 0.55;
	}
	.csf-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.csf-label {
		font-size: 13px;
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}
	.csf-description {
		margin: 0;
		font-size: 11px;
		color: var(--terminal-fg-muted);
		line-height: 1.4;
	}
	.csf-control {
		width: 100%;
	}
	.csf-select {
		width: 100%;
		height: 28px;
		background: var(--terminal-bg-panel-sunken);
		color: var(--terminal-fg-primary);
		border: var(--terminal-border-hairline);
		border-radius: 0;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		padding: 0 var(--terminal-space-2);
		cursor: pointer;
	}
	.csf-select:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
	.csf-select:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
</style>
