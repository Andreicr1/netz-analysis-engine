<!--
  RegimeContextStrip.svelte
  =========================

  Read-only regime context for the allocation page. Renders the current
  global regime + stress score as two pills. The macro regime window is
  not exposed by ``GET /macro/regime`` (GlobalRegimeRead has no ``window``
  field) so it is intentionally omitted; keep this component honest.

  Data arrives via the page loader (``+page.server.ts``) fetching
  ``/macro/regime`` in parallel; null when the endpoint is unavailable
  (404 when the regime_detection worker has never run, transient 5xx)
  and the component renders nothing so it never blocks page load.

  Source: docs/plans/2026-04-19-netz-terminal-parity-builder-macro-screener.md §B.8.
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import { TerminalPill } from "../terminal/primitives";

	interface RegimeContextStripData {
		regime: string | null;
		stressScore: number | null;
	}

	interface Props {
		data: RegimeContextStripData | null;
		class?: string;
	}

	let { data, class: className }: Props = $props();

	function regimeTone(regime: string | null): "neutral" | "success" | "warn" | "error" {
		if (!regime) return "neutral";
		const upper = regime.toUpperCase();
		if (upper.includes("CRISIS") || upper.includes("RISK_OFF")) return "error";
		if (upper.includes("CAUTION") || upper.includes("TRANSITION")) return "warn";
		if (upper.includes("RISK_ON") || upper.includes("EXPANSION")) return "success";
		return "neutral";
	}

	function stressTone(
		score: number | null,
	): "neutral" | "success" | "warn" | "error" {
		if (score === null) return "neutral";
		if (score >= 0.75) return "error";
		if (score >= 0.5) return "warn";
		if (score >= 0.25) return "neutral";
		return "success";
	}
</script>

{#if data && data.regime}
	<div class="regime-context-strip {className ?? ''}" role="group" aria-label="Macro regime context">
		<span class="regime-context-strip__label">MACRO CONTEXT</span>
		<div class="regime-context-strip__pills">
			<TerminalPill
				label={`Regime: ${data.regime}`}
				tone={regimeTone(data.regime)}
				size="xs"
			/>
			{#if data.stressScore !== null}
				<TerminalPill
					label={`Stress: ${formatPercent(data.stressScore)}`}
					tone={stressTone(data.stressScore)}
					size="xs"
				/>
			{/if}
		</div>
	</div>
{/if}

<style>
	.regime-context-strip {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-2) 0;
		font-family: var(--terminal-font-mono);
	}
	.regime-context-strip__label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}
	.regime-context-strip__pills {
		display: flex;
		flex-wrap: wrap;
		gap: var(--terminal-space-2);
	}
</style>
