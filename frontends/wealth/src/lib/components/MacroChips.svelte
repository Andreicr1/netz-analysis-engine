<!--
  MacroChips — shared macro indicator chips row.
  Renders VIX, Yield Curve, CPI YoY, and Fed Funds chips in a flex-wrap container.
  VIX: danger when > 25, success otherwise.
  Yield Curve: danger when negative.
  CPI YoY / Fed Funds: primary text, no conditional colour.
-->
<script lang="ts">
	import { cn } from "@netz/ui";

	interface Props {
		macro: {
			vix: number | null;
			yield_curve_10y2y: number | null;
			cpi_yoy: number | null;
			fed_funds_rate: number | null;
		};
		class?: string;
	}

	let { macro, class: className }: Props = $props();
</script>

<div class={cn("flex flex-wrap gap-3", className)}>
	<!-- VIX -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
		<p class="text-xs text-[var(--netz-text-muted)]">VIX</p>
		<p
			class="text-lg font-semibold"
			style:color={macro.vix !== null && macro.vix > 25
				? "var(--netz-danger)"
				: "var(--netz-success)"}
		>{macro.vix?.toFixed(1) ?? "—"}</p>
	</div>

	<!-- Yield Curve -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
		<p class="text-xs text-[var(--netz-text-muted)]">Yield Curve</p>
		<p
			class="text-lg font-semibold"
			style:color={macro.yield_curve_10y2y !== null && macro.yield_curve_10y2y < 0
				? "var(--netz-danger)"
				: "var(--netz-text-primary)"}
		>{macro.yield_curve_10y2y !== null ? `${macro.yield_curve_10y2y.toFixed(2)}%` : "—"}</p>
	</div>

	<!-- CPI YoY -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
		<p class="text-xs text-[var(--netz-text-muted)]">CPI YoY</p>
		<p class="text-lg font-semibold text-[var(--netz-text-primary)]">
			{macro.cpi_yoy !== null ? `${macro.cpi_yoy.toFixed(1)}%` : "—"}
		</p>
	</div>

	<!-- Fed Funds -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
		<p class="text-xs text-[var(--netz-text-muted)]">Fed Funds</p>
		<p class="text-lg font-semibold text-[var(--netz-text-primary)]">
			{macro.fed_funds_rate !== null ? `${macro.fed_funds_rate.toFixed(2)}%` : "—"}
		</p>
	</div>
</div>
