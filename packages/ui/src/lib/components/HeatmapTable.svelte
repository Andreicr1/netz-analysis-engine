<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface ColorScale {
		min: string;
		max: string;
	}

	interface Props {
		rows: string[];
		columns: string[];
		data: number[][];
		formatCell?: (value: number) => string;
		colorScale?: ColorScale;
		class?: string;
	}

	let {
		rows,
		columns,
		data,
		formatCell,
		colorScale,
		class: className,
	}: Props = $props();

	const defaultFormat = (v: number) => v.toFixed(2);
	const fmt = $derived(formatCell ?? defaultFormat);

	/** Flatten all values to compute global min/max */
	const allValues = $derived(data.flat());
	const dataMin = $derived(allValues.length > 0 ? Math.min(...allValues) : 0);
	const dataMax = $derived(allValues.length > 0 ? Math.max(...allValues) : 1);
	const dataRange = $derived(dataMax - dataMin || 1);

	/**
	 * Interpolate between two hex colors by t ∈ [0, 1].
	 * Falls back to CSS variable-aware inline styles by using the CSS
	 * color-mix() where supported; for simplicity we compute a numeric
	 * intensity and use opacity on a single semantic color instead of
	 * true two-color interpolation (avoids parsing CSS variables).
	 */
	function cellStyle(value: number): string {
		const t = (value - dataMin) / dataRange; // 0 = min, 1 = max

		if (colorScale?.min && colorScale?.max) {
			// When explicit hex colors are provided we can interpolate directly
			return `background-color: color-mix(in srgb, ${colorScale.max} ${Math.round(t * 100)}%, ${colorScale.min});`;
		}

		// Default: green→red semantic interpolation via opacity layers
		if (t >= 0.5) {
			const intensity = (t - 0.5) * 2; // 0→1 for upper half
			return `background-color: color-mix(in srgb, var(--netz-danger) ${Math.round(intensity * 60)}%, var(--netz-surface-inset));`;
		} else {
			const intensity = (0.5 - t) * 2; // 0→1 for lower half
			return `background-color: color-mix(in srgb, var(--netz-success) ${Math.round(intensity * 60)}%, var(--netz-surface-inset));`;
		}
	}

	/** Text contrast: use primary for near-neutral, white for intense cells */
	function textStyle(value: number): string {
		const t = (value - dataMin) / dataRange;
		const intensity = Math.abs(t - 0.5) * 2; // 0 = neutral, 1 = extreme
		return intensity > 0.65
			? "color: var(--netz-surface);"
			: "color: var(--netz-text-primary);";
	}
</script>

<div class={cn("w-full overflow-x-auto", className)}>
	<table class="w-full border-collapse text-xs">
		<thead>
			<tr>
				<!-- Corner cell -->
				<th
					class="min-w-[120px] px-3 py-2 text-left text-[var(--netz-text-muted)]"
					scope="col"
				></th>
				{#each columns as col}
					<th
						class="min-w-[72px] px-2 py-2 text-center font-medium text-[var(--netz-text-secondary)]"
						scope="col"
					>
						{col}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as row, ri}
				<tr class="border-t border-[var(--netz-border)]">
					<th
						class="px-3 py-2 text-left font-medium text-[var(--netz-text-secondary)]"
						scope="row"
					>
						{row}
					</th>
					{#each columns as _col, ci}
						{@const val = data[ri]?.[ci] ?? 0}
						<td
							class="px-2 py-2 text-center font-mono font-medium tabular-nums"
							style="{cellStyle(val)} {textStyle(val)}"
						>
							{fmt(val)}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
