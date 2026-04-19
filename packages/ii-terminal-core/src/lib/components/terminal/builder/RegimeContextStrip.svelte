<!--
  RegimeContextStrip — Zone A of the Builder command panel.

  Shows current TAA regime badge, stress score bar, effective band
  ranges (equity/FI/alt/cash), and universe count. 120px fixed height.
  Pure presentational — no workspace dependency.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import {
		taaRegimeLabel,
		taaRegimeColor,
		taaRegimePosture,
	} from "../../../types/taa";
	import type { RegimeBands } from "../../../types/taa";

	interface Props {
		regimeBands: RegimeBands | null;
	}

	let { regimeBands }: Props = $props();

	// Derive band entries for the 4 main asset classes
	interface BandRow {
		label: string;
		min: number;
		center: number | null;
		max: number;
	}

	const BAND_ORDER: Record<string, string> = {
		equity: "Equity",
		fi: "Fixed Income",
		alt: "Alternatives",
		cash: "Cash",
	};

	const bandRows = $derived.by<BandRow[]>(() => {
		if (!regimeBands?.effective_bands) return [];
		const rows: BandRow[] = [];
		// Aggregate effective_bands by asset class prefix
		const agg: Record<string, { min: number; center: number; max: number }> = {};
		for (const [blockId, band] of Object.entries(regimeBands.effective_bands)) {
			let cls = "other";
			if (blockId.startsWith("na_equity") || blockId.startsWith("dm_") || blockId.startsWith("em_") || blockId.startsWith("intl_equity")) cls = "equity";
			else if (blockId.startsWith("fi_")) cls = "fi";
			else if (blockId.startsWith("alt_")) cls = "alt";
			else if (blockId === "cash") cls = "cash";

			const entry = agg[cls] ?? (agg[cls] = { min: 0, center: 0, max: 0 });
			entry.min += band.min;
			entry.center += band.center ?? (band.min + band.max) / 2;
			entry.max += band.max;
		}
		for (const [key, label] of Object.entries(BAND_ORDER)) {
			const a = agg[key];
			if (!a) continue;
			rows.push({ label, min: a.min, center: a.center, max: a.max });
		}
		return rows;
	});

	const universeCount = $derived.by(() => {
		if (!regimeBands?.effective_bands) return { instruments: 0, classes: 0 };
		const keys = Object.keys(regimeBands.effective_bands);
		return { instruments: keys.length, classes: Object.keys(BAND_ORDER).length };
	});

	const regimeColor = $derived(
		regimeBands ? taaRegimeColor(regimeBands.raw_regime) : "var(--terminal-fg-muted)",
	);
</script>

<div class="rcs-root">
	{#if regimeBands}
		<div class="rcs-header">
			<span class="rcs-badge" style="background: {regimeColor}; color: var(--terminal-fg-inverted);">
				{taaRegimeLabel(regimeBands.raw_regime)}
			</span>
			<span class="rcs-posture">{taaRegimePosture(regimeBands.raw_regime)}</span>
		</div>

		<div class="rcs-stress">
			<span class="rcs-stress-label">STRESS</span>
			<div class="rcs-stress-track">
				<div
					class="rcs-stress-fill"
					style="width: {regimeBands.stress_score ?? 0}%; background: {regimeColor};"
				></div>
			</div>
			<span class="rcs-stress-value">{regimeBands.stress_score ?? 0}</span>
		</div>

		<div class="rcs-bands">
			{#each bandRows as row (row.label)}
				<div class="rcs-band-row">
					<span class="rcs-band-label">{row.label}</span>
					<span class="rcs-band-range">
						{formatPercent(row.min, 1)} <span class="rcs-band-arrow">&rarr;</span>
						{formatPercent(row.center ?? row.min, 1)} <span class="rcs-band-arrow">&rarr;</span>
						{formatPercent(row.max, 1)}
					</span>
				</div>
			{/each}
		</div>

		<div class="rcs-universe">
			{universeCount.instruments} blocks across {universeCount.classes} classes
		</div>
	{:else}
		<div class="rcs-empty">Regime data unavailable</div>
	{/if}
</div>

<style>
	.rcs-root {
		height: 120px;
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		box-sizing: border-box;
		overflow: hidden;
	}

	.rcs-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.rcs-badge {
		display: inline-block;
		padding: 1px 6px;
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.rcs-posture {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}

	.rcs-stress {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.rcs-stress-label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		min-width: 40px;
	}

	.rcs-stress-track {
		flex: 1;
		height: 4px;
		background: var(--terminal-fg-muted);
	}

	.rcs-stress-fill {
		height: 100%;
		transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
	}

	.rcs-stress-value {
		font-size: var(--terminal-text-10);
		font-weight: 600;
		min-width: 24px;
		text-align: right;
	}

	.rcs-bands {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.rcs-band-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		font-size: var(--terminal-text-10);
	}

	.rcs-band-label {
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
	}

	.rcs-band-range {
		color: var(--terminal-fg-primary);
		font-weight: 600;
	}

	.rcs-band-arrow {
		color: var(--terminal-fg-muted);
	}

	.rcs-universe {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rcs-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
	}
</style>
