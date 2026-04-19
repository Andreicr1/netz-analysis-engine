<!--
  CalibrationSliderField — paired slider + numeric input used inside the
  Builder CalibrationPanel.

  Phase 4 Task 4.1 (OD-2 locked → paired slider + bound numeric input).
  The slider drives the number, the number drives the slider, and the
  keyboard arrows nudge by ``step``. ``displayFormat`` renders the
  inline value chip next to the label so the PM always sees the
  institutional representation (percent, bps, x, raw).

  API uses ``value`` + ``onChange`` (no bindable) so the parent can
  drive transforms — e.g. sentinel-for-null, percent-for-ratio — at
  the call site without touching the internal $state here.

  Formatting is routed through @investintell/ui formatters — never
  ``.toFixed`` or ``new Intl.NumberFormat`` (DL16).
-->
<script lang="ts">
	import { formatPercent, formatNumber, formatBps } from "@investintell/ui";

	type DisplayFormat = "percent" | "bps" | "raw" | "x";

	interface Props {
		id: string;
		label: string;
		description?: string;
		value: number;
		onChange: (value: number) => void;
		min: number;
		max: number;
		step: number;
		displayFormat?: DisplayFormat;
		digits?: number;
		edgeLabels?: [string, string];
		disabled?: boolean;
		accent?: "primary" | "danger" | "success";
		originalValue?: number;
	}

	let {
		id,
		label,
		description,
		value,
		onChange,
		min,
		max,
		step,
		displayFormat = "raw",
		digits,
		edgeLabels,
		disabled = false,
		accent = "primary",
		originalValue,
	}: Props = $props();

	const showOriginal = $derived(
		originalValue !== undefined && originalValue !== value,
	);
	const originalDisplay = $derived.by(() => {
		if (!showOriginal || originalValue === undefined) return null;
		switch (displayFormat) {
			case "percent":
				return formatPercent(originalValue, digits ?? 2);
			case "bps":
				return formatBps(originalValue);
			case "x":
				return `${formatNumber(originalValue, digits ?? 2)}x`;
			case "raw":
			default:
				return formatNumber(originalValue, digits ?? 2);
		}
	});

	const display = $derived.by(() => {
		switch (displayFormat) {
			case "percent":
				return formatPercent(value, digits ?? 2);
			case "bps":
				return formatBps(value);
			case "x":
				return `${formatNumber(value, digits ?? 2)}x`;
			case "raw":
			default:
				return formatNumber(value, digits ?? 2);
		}
	});

	function handleSliderInput(e: Event) {
		const next = Number.parseFloat((e.target as HTMLInputElement).value);
		if (!Number.isNaN(next)) onChange(clamp(next));
	}

	function handleNumberInput(e: Event) {
		const next = Number.parseFloat((e.target as HTMLInputElement).value);
		if (!Number.isNaN(next)) onChange(clamp(next));
	}

	function clamp(v: number): number {
		if (v < min) return min;
		if (v > max) return max;
		return v;
	}
</script>

<div class="csf-root" class:csf-root--disabled={disabled}>
	<div class="csf-header">
		<label class="csf-label" for={id}>{label}</label>
		<span class="csf-value" data-accent={accent}>{display}</span>
		{#if showOriginal && originalDisplay !== null}
			<span class="csf-original-chip" title="Valor da última construção">
				Anteriormente: {originalDisplay}
			</span>
		{/if}
	</div>
	{#if description}
		<p class="csf-description">{description}</p>
	{/if}

	<div class="csf-controls">
		<input
			{id}
			type="range"
			class="csf-slider"
			{min}
			{max}
			{step}
			{value}
			{disabled}
			oninput={handleSliderInput}
		/>
		<input
			type="number"
			class="csf-number"
			aria-label={`${label} (numeric input)`}
			{min}
			{max}
			{step}
			{value}
			{disabled}
			oninput={handleNumberInput}
		/>
	</div>

	{#if edgeLabels}
		<div class="csf-edges">
			<span>{edgeLabels[0]}</span>
			<span>{edgeLabels[1]}</span>
		</div>
	{/if}
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
	.csf-value {
		font-size: 13px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--terminal-accent-amber);
	}
	.csf-value[data-accent="danger"] {
		color: var(--terminal-status-error);
	}
	.csf-value[data-accent="success"] {
		color: var(--terminal-status-success);
	}

	.csf-description {
		margin: 0;
		font-size: 11px;
		color: var(--terminal-fg-muted);
		line-height: 1.4;
	}

	.csf-controls {
		display: grid;
		grid-template-columns: 1fr 84px;
		gap: 12px;
		align-items: center;
	}

	.csf-slider {
		width: 100%;
		-webkit-appearance: none;
		appearance: none;
		background: transparent;
	}
	.csf-slider::-webkit-slider-runnable-track {
		width: 100%;
		height: 4px;
		background: var(--terminal-fg-muted);
	}
	.csf-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		appearance: none;
		height: 16px;
		width: 16px;
		border-radius: 50%;
		background: var(--terminal-bg-panel);
		border: 2px solid var(--terminal-accent-amber);
		margin-top: -6px;
		cursor: pointer;
		transition: transform 120ms ease, box-shadow 120ms ease;
	}
	.csf-slider::-webkit-slider-thumb:hover {
		transform: scale(1.08);
	}
	.csf-slider:focus {
		outline: none;
	}
	.csf-slider:focus::-webkit-slider-thumb {
		box-shadow: 0 0 0 4px color-mix(in srgb, var(--terminal-accent-amber) 25%, transparent);
	}
	.csf-slider::-moz-range-track {
		width: 100%;
		height: 4px;
		background: var(--terminal-fg-muted);
	}
	.csf-slider::-moz-range-thumb {
		height: 16px;
		width: 16px;
		border-radius: 50%;
		background: var(--terminal-bg-panel);
		border: 2px solid var(--terminal-accent-amber);
		cursor: pointer;
	}

	.csf-number {
		height: 28px;
		padding: 0 8px;
		font-size: 12px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		border: var(--terminal-border-hairline);
		border-radius: 0;
		background: transparent;
		color: var(--terminal-fg-primary);
		text-align: right;
		font-family: inherit;
	}
	.csf-number:focus {
		outline: none;
		border-color: var(--terminal-accent-amber);
	}
	.csf-number::-webkit-outer-spin-button,
	.csf-number::-webkit-inner-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}
	.csf-number[type="number"] {
		-moz-appearance: textfield;
		appearance: textfield;
	}

	.csf-edges {
		display: flex;
		justify-content: space-between;
		font-size: 10px;
		font-weight: 500;
		color: var(--terminal-fg-muted);
	}

	.csf-original-chip {
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
