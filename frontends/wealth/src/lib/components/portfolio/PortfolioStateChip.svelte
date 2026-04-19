<!--
  PortfolioStateChip — Phase 5 Task 5.2 always-visible state badge in
  the Builder action bar. Renders the current portfolio state with a
  client-safe label per OD-22 + memory ``feedback_smart_backend_dumb_frontend``.

  Hover surfaces ``state_metadata.latest_transition_reason`` so the PM
  can see why the portfolio landed in its current state without leaving
  the Builder.

  Per CLAUDE.md DL14 — never read ``state`` directly to decide
  rendering. This component is the ONLY place that maps state to a
  visible label.
-->
<script lang="ts">
	import type { PortfolioState } from "$wealth/types/model-portfolio";

	interface Props {
		state: PortfolioState;
		stateMetadata?: Record<string, unknown> | null;
	}

	let { state, stateMetadata }: Props = $props();

	// Per OD-22 — institutional client-safe labels for the canonical
	// 8-state machine. Phase 10 Task 10.1 will move this to the
	// jargon translation table; until then it lives here as the source
	// of truth for state presentation.
	const LABELS: Record<PortfolioState, string> = {
		draft: "Draft",
		constructed: "Built",
		validated: "Validated",
		approved: "Approved",
		live: "Live",
		paused: "Paused",
		archived: "Archived",
		rejected: "Rejected",
	};

	// Visual treatment per state — same accent palette as the
	// Discovery PASS/WARN/FAIL chips so the PM has consistent visual
	// language across the platform.
	const ACCENT: Record<PortfolioState, "neutral" | "info" | "success" | "warning" | "danger" | "muted"> = {
		draft: "neutral",
		constructed: "info",
		validated: "info",
		approved: "success",
		live: "success",
		paused: "warning",
		archived: "muted",
		rejected: "danger",
	};

	const label = $derived(LABELS[state] ?? state);
	const accent = $derived(ACCENT[state] ?? "neutral");

	const tooltip = $derived.by(() => {
		if (!stateMetadata) return label;
		const reason = stateMetadata.latest_transition_reason;
		if (typeof reason === "string" && reason.trim().length > 0) {
			return `${label} — ${reason}`;
		}
		return label;
	});
</script>

<span class="psc-chip" data-accent={accent} title={tooltip}>
	<span class="psc-dot" aria-hidden="true"></span>
	<span class="psc-label">{label}</span>
</span>

<style>
	.psc-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		border-radius: 999px;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.02em;
		text-transform: uppercase;
		white-space: nowrap;
		cursor: default;
	}

	.psc-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.psc-chip[data-accent="neutral"] {
		background: rgba(255, 255, 255, 0.06);
		color: #cbccd1;
	}
	.psc-chip[data-accent="neutral"] .psc-dot {
		background: #cbccd1;
	}

	.psc-chip[data-accent="info"] {
		background: rgba(1, 119, 251, 0.12);
		color: #4ca0ff;
	}
	.psc-chip[data-accent="info"] .psc-dot {
		background: #0177fb;
	}

	.psc-chip[data-accent="success"] {
		background: rgba(63, 185, 80, 0.14);
		color: #3fb950;
	}
	.psc-chip[data-accent="success"] .psc-dot {
		background: #3fb950;
	}

	.psc-chip[data-accent="warning"] {
		background: rgba(240, 160, 32, 0.16);
		color: #f0a020;
	}
	.psc-chip[data-accent="warning"] .psc-dot {
		background: #f0a020;
	}

	.psc-chip[data-accent="danger"] {
		background: rgba(252, 26, 26, 0.14);
		color: #fc1a1a;
	}
	.psc-chip[data-accent="danger"] .psc-dot {
		background: #fc1a1a;
	}

	.psc-chip[data-accent="muted"] {
		background: rgba(255, 255, 255, 0.04);
		color: #85a0bd;
	}
	.psc-chip[data-accent="muted"] .psc-dot {
		background: #85a0bd;
	}
</style>
