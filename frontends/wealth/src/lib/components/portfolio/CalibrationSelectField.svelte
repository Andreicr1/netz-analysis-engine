<!--
  CalibrationSelectField — dropdown version of CalibrationSliderField,
  used for enum-valued knobs (mandate, regime_override, cvar_level
  segmented, etc.).

  Uses explicit ``value`` + ``onChange`` props (no bindable) so the
  parent can transform — e.g. ``"auto"`` sentinel → ``null`` — without
  touching internal state.
-->
<script lang="ts">
	import { Select } from "@investintell/ui";

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
		<Select
			{value}
			onValueChange={onChange}
			options={[...options]}
			{placeholder}
			{disabled}
		/>
	</div>
</div>

<style>
	.csf-root {
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-family: "Urbanist", system-ui, sans-serif;
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
		color: var(--ii-text-primary, #ffffff);
	}
	.csf-description {
		margin: 0;
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		line-height: 1.4;
	}
	.csf-control {
		width: 100%;
	}
</style>
