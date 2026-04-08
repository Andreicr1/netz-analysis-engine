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
	}

	let {
		id,
		label,
		description,
		value,
		onChange,
		disabled = false,
	}: Props = $props();

	function handleChange(e: Event) {
		onChange((e.target as HTMLInputElement).checked);
	}
</script>

<div class="ctf-root" class:ctf-root--disabled={disabled}>
	<div class="ctf-header">
		<label class="ctf-label" for={id}>{label}</label>
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
		font-family: "Urbanist", system-ui, sans-serif;
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
		color: var(--ii-text-primary, #ffffff);
	}
	.ctf-description {
		margin: 0;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
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
		background: rgba(64, 66, 73, 0.7);
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
		background: #ffffff;
		border-radius: 999px;
		transition: transform 140ms ease;
	}
	.ctf-switch input:checked + .ctf-slider {
		background: var(--ii-primary, #0177fb);
	}
	.ctf-switch input:checked + .ctf-slider::before {
		transform: translateX(16px);
	}
	.ctf-switch input:focus-visible + .ctf-slider {
		box-shadow: 0 0 0 3px rgba(1, 119, 251, 0.25);
	}
</style>
