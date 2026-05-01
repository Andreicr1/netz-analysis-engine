<!--
  PortfolioGateNotice — STRESS-stage empty state.

  Rendered on the Builder workspace's STRESS tab when the active
  profile has no portfolios (model_portfolios) yet. Replaces the
  inline empty `<div>` previously hardcoded in StressTabContent
  (lines 43-47 pre-PR-UX-3).

  Pure presentation:
    - No CTA — operator switches stages via the BuilderTabStrip.
    - Profile copy via the canonical `profileDisplayLabel` helper.
    - Token discipline + svelte:boundary per PR-UX-1 / Stability §P3.
-->
<script lang="ts">
	import { profileDisplayLabel } from "../../i18n/quant-labels";

	interface Props {
		/** Profile slug (`conservative` / `moderate` / `growth`). */
		profile: string;
	}

	let { profile }: Props = $props();

	const label = $derived(profileDisplayLabel(profile, "full"));
</script>

<svelte:boundary>
	<div class="pf-gate" role="status" data-testid="portfolio-gate-notice">
		<div class="pf-gate__body">
			<p class="pf-gate__title">No portfolios yet for {label}.</p>
			<p class="pf-gate__copy">
				Create a portfolio in the Portfolio stage first.
			</p>
		</div>
	</div>
</svelte:boundary>

<style>
	/* Empty-state shell — terminal token styling, same primitive
	   layout as IPSGateNotice but without a CTA (the stage strip
	   carries the navigation affordance). */
	.pf-gate {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-3);
		min-height: 200px;
		padding: var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		border: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.pf-gate__body {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		text-align: center;
		max-width: 60ch;
	}

	.pf-gate__title {
		margin: 0;
		font-size: var(--terminal-text-12);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-primary);
	}

	.pf-gate__copy {
		margin: 0;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-tertiary);
	}
</style>
