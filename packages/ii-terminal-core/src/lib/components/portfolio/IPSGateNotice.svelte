<!--
  IPSGateNotice — PORTFOLIO-stage empty state.

  Rendered on the Builder workspace's PORTFOLIO tab when the active
  profile's Strategic IPS has not been approved yet. Blocks portfolio
  construction with a single-action CTA back to the Strategic IPS
  surface.

  Pure presentation:
    - No fetch, no store reads, no localStorage. The parent owns the
      gate condition (today: `!has_active_approval`; post PR-BE-6:
      `ips_state !== "approved"`) and the navigation callback.
    - Profile display copy routes through `profileDisplayLabel` (the
      canonical, Q165 / PR-BE-7 helper) so "Dynamic" vs "Dynamic
      Growth" never gets hardcoded here.
    - Token discipline: every visual property is a `var(--terminal-*)`
      custom property (mirrors PR-UX-1 ProposeButton).
    - Stability Guardrails P3 Isolated: wrapped in `<svelte:boundary>`
      so a render error in the empty-state copy cannot blank the
      entire workspace tab.

  Consumed by:
    - frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte
    - PR-UX-4 (dialog wiring) will add a richer onOpenStrategic handler
    - PR-UX-6 (StageProgressStrip lock state) will mirror this gate
-->
<script lang="ts">
	import { profileDisplayLabel } from "../../i18n/quant-labels";

	interface Props {
		/** Profile slug (`conservative` / `moderate` / `growth`). */
		profile: string;
		/** Invoked when the operator clicks "Open Strategic IPS". */
		onOpenStrategic: () => void;
	}

	let { profile, onOpenStrategic }: Props = $props();

	const label = $derived(profileDisplayLabel(profile, "full"));
</script>

<svelte:boundary>
	<div class="ips-gate" role="status" data-testid="ips-gate-notice">
		<div class="ips-gate__body">
			<p class="ips-gate__title">
				Strategic IPS not approved for {label} profile.
			</p>
			<p class="ips-gate__copy">
				Approve a Strategic IPS proposal before constructing portfolios.
			</p>
		</div>
		<button
			type="button"
			class="ips-gate__cta"
			onclick={() => onOpenStrategic()}
		>
			Open Strategic IPS
		</button>
	</div>
</svelte:boundary>

<style>
	/* Empty-state shell — terminal token styling.
	   Mirrors the layout discipline of `.builder-empty-zone` in
	   PortfolioTabContent.svelte and the CTA token spec from PR-UX-1
	   (`.propose-cta`). All colour, spacing, border, font tokens come
	   from the terminal design system — never Tailwind utility classes.
	*/
	.ips-gate {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-3);
		min-height: 240px;
		padding: var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.ips-gate__body {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		text-align: center;
		max-width: 60ch;
	}

	.ips-gate__title {
		margin: 0;
		font-size: var(--terminal-text-12);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-primary);
	}

	.ips-gate__copy {
		margin: 0;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-tertiary);
	}

	/* CTA — mirrors `.propose-cta` (PR-UX-1) for cross-surface
	   consistency: transparent ground, status-success border + text,
	   color-mix hover tint. */
	.ips-gate__cta {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-4);
		background: transparent;
		border: 1px solid var(--terminal-status-success);
		color: var(--terminal-status-success);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
	}
	.ips-gate__cta:hover {
		background: color-mix(
			in srgb,
			var(--terminal-status-success) 10%,
			transparent
		);
	}
	.ips-gate__cta:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
