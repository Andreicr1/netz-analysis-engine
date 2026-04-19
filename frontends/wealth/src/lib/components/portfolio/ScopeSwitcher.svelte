<!--
  ScopeSwitcher — Phase 6 Block A of the portfolio-enterprise-workbench
  plan. Three-pill segmented control mounted at the top of the
  /portfolio/analytics FilterRail.

  OD-25 (locked): Compare Both is rendered with a disabled state and a
  ``v1.1`` badge. The pill is visible so the IA decision is communicated
  to the PM, but clicking it does nothing in Phase 6 Block A — the
  multi-subject diff is the highest-risk scope item and lands in v1.1.

  Per DL15 — zero localStorage. The active scope is owned by the parent
  via ``value`` + ``onValueChange``. The parent persists it into the URL
  query (``?scope=``) and re-derives on navigation. This component is
  pure presentation.
-->
<script lang="ts">
	import type { AnalyticsScope } from "$wealth/portfolio/analytics-types";
	import { ANALYTICS_SCOPE_LABEL } from "$wealth/portfolio/analytics-types";

	interface Props {
		value: AnalyticsScope;
		onValueChange: (next: AnalyticsScope) => void;
	}

	let { value, onValueChange }: Props = $props();

	interface PillSpec {
		scope: AnalyticsScope;
		disabled: boolean;
		badge?: string;
		hint?: string;
	}

	// OD-25 — compare_both is rendered but disabled in v1.0; the v1.1
	// badge communicates the decision to the PM without hiding the IA.
	const PILLS: readonly PillSpec[] = [
		{ scope: "model_portfolios", disabled: false },
		{ scope: "approved_universe", disabled: false },
		{
			scope: "compare_both",
			disabled: true,
			badge: "v1.1",
			hint: "Multi-subject diff lands in v1.1",
		},
	];

	function handleClick(spec: PillSpec) {
		if (spec.disabled) return;
		if (spec.scope === value) return;
		onValueChange(spec.scope);
	}
</script>

<div class="ss-root" role="tablist" aria-label="Analytics scope">
	{#each PILLS as pill (pill.scope)}
		{@const isActive = value === pill.scope}
		<button
			type="button"
			class="ss-pill"
			class:ss-pill--active={isActive}
			class:ss-pill--disabled={pill.disabled}
			role="tab"
			aria-selected={isActive}
			aria-disabled={pill.disabled}
			disabled={pill.disabled}
			title={pill.hint ?? ANALYTICS_SCOPE_LABEL[pill.scope]}
			onclick={() => handleClick(pill)}
		>
			<span class="ss-pill-label">{ANALYTICS_SCOPE_LABEL[pill.scope]}</span>
			{#if pill.badge}
				<span class="ss-pill-badge">{pill.badge}</span>
			{/if}
		</button>
	{/each}
</div>

<style>
	.ss-root {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.ss-pill {
		display: inline-flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 10px 14px;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 8px;
		background: transparent;
		color: var(--ii-text-secondary, #cbccd1);
		font-family: inherit;
		font-size: 13px;
		font-weight: 600;
		text-align: left;
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.ss-pill:hover:not(.ss-pill--disabled):not(.ss-pill--active) {
		background: rgba(255, 255, 255, 0.04);
		color: var(--ii-text-primary, #ffffff);
	}

	.ss-pill--active {
		background: rgba(1, 119, 251, 0.12);
		border-color: var(--ii-primary, #0177fb);
		color: var(--ii-text-primary, #ffffff);
	}

	.ss-pill--disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.ss-pill-label {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ss-pill-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 1px 6px;
		font-size: 10px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-muted, #85a0bd);
		background: rgba(255, 255, 255, 0.06);
		border-radius: 999px;
		flex-shrink: 0;
	}
</style>
