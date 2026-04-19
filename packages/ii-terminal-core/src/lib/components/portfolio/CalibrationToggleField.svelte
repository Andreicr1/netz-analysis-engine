<!--
  CalibrationToggleField — boolean toggle for the Advanced tier knobs
  (bl_enabled, garch_enabled, advisor_enabled).

  Explicit ``value`` + ``onChange`` props so the parent keeps the draft
  as the single source of truth.
-->
<script lang="ts">
	interface Props {
		id: string;
		label: string;
		description?: string;
		value: boolean;
		onChange: (value: boolean) => void;
		disabled?: boolean;
		originalValue?: boolean;
	}

	let {
		id,
		label,
		description,
		value,
		onChange,
		disabled = false,
		originalValue,
	}: Props = $props();

	const showOriginal = $derived(
		originalValue !== undefined && originalValue !== value,
	);
	const originalLabel = $derived(
		showOriginal ? (originalValue ? "Ativado" : "Desativado") : null,
	);

	function handleChange(e: Event) {
		onChange((e.target as HTMLInputElement).checked);
	}
</script>

<div class="ctf-root" class:ctf-root--disabled={disabled}>
	<div class="ctf-header">
		<label class="ctf-label" for={id}>{label}</label>
		{#if showOriginal && originalLabel !== null}
			<span class="ctf-original-chip" title="Valor da última construção">
				Anteriormente: {originalLabel}
			</span>
		{/if}
		<label class="ctf-switch">
			<input
				{id}
				type="checkbox"
				checked={value}
				{disabled}
				onchange={handleChange}
			/>
			<span class="ctf-slider" aria-hidden="true"></span>
		</label>
	</div>
	{#if description}
		<p class="ctf-description">{description}</p>
	{/if}
</div>

<style>
	.ctf-root {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-family: var(--terminal-font-mono);
	}
	.ctf-root--disabled {
		opacity: 0.55;
	}

	.ctf-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.ctf-label {
		font-size: 13px;
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}
	.ctf-description {
		margin: 0;
		font-size: 11px;
		color: var(--terminal-fg-muted);
		line-height: 1.4;
	}

	.ctf-switch {
		position: relative;
		display: inline-block;
		width: 36px;
		height: 20px;
		cursor: pointer;
	}
	.ctf-switch input {
		opacity: 0;
		width: 0;
		height: 0;
		position: absolute;
	}
	.ctf-slider {
		position: absolute;
		inset: 0;
		background: var(--terminal-fg-muted);
		border-radius: 999px;
		transition: background 140ms ease;
	}
	.ctf-slider::before {
		content: "";
		position: absolute;
		left: 2px;
		top: 2px;
		width: 16px;
		height: 16px;
		background: var(--terminal-fg-primary);
		border-radius: 999px;
		transition: transform 140ms ease;
	}
	.ctf-switch input:checked + .ctf-slider {
		background: var(--terminal-accent-amber);
	}
	.ctf-switch input:checked + .ctf-slider::before {
		transform: translateX(16px);
	}
	.ctf-switch input:focus-visible + .ctf-slider {
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--terminal-accent-amber) 25%, transparent);
	}
	.ctf-original-chip {
		margin-left: 8px;
		padding: 2px 6px;
		font-size: 10px;
		font-weight: 500;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--terminal-fg-muted);
		background: var(--terminal-bg-panel-raised);
		border: 1px solid var(--terminal-fg-muted);
		border-radius: 2px;
		font-family: var(--terminal-font-mono);
		white-space: nowrap;
	}
</style>
