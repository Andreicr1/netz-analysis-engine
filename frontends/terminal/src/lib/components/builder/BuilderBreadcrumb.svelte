<!--
  X3.1 — Builder workspace breadcrumb.

  Terminal-native replica of the bundle's `.bd-breadcrumb` row. Shows
  Screener > Macro > Builder > {PROFILE} and surfaces the optional
  portfolio-name badge on the right (only when a ?portfolio_id query
  is active, so users know which model portfolio they're editing).

  Pure terminal tokens — no shadcn bleed, no `$lib/*` imports.
-->
<script lang="ts">
	import { ChevronRight } from "lucide-svelte";
	import { resolve } from "$app/paths";
	import {
		PROFILE_LABELS,
		type AllocationProfile,
	} from "$wealth/types/allocation-page";

	interface Props {
		profile: AllocationProfile;
		/** Display name of the selected model portfolio, if any. */
		portfolioName?: string | null;
	}

	let { profile, portfolioName = null }: Props = $props();
</script>

<nav class="crumbs" aria-label="Breadcrumb">
	<a href={resolve("/screener")} class="crumbs__link">Screener</a>
	<ChevronRight class="crumbs__sep" aria-hidden="true" />
	<a href={resolve("/macro")} class="crumbs__link">Macro</a>
	<ChevronRight class="crumbs__sep" aria-hidden="true" />
	<span class="crumbs__current">Builder</span>
	<ChevronRight class="crumbs__sep" aria-hidden="true" />
	<span class="crumbs__current crumbs__current--accent"
		>{PROFILE_LABELS[profile]}</span
	>

	{#if portfolioName}
		<span class="crumbs__portfolio" title={portfolioName}>
			{portfolioName}
		</span>
	{/if}
</nav>

<style>
	.crumbs {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-1);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.crumbs__link {
		color: var(--terminal-fg-tertiary);
		text-decoration: none;
		transition: color var(--terminal-motion-tick)
			var(--terminal-motion-easing-out);
	}
	.crumbs__link:hover,
	.crumbs__link:focus-visible {
		color: var(--terminal-accent-amber);
		outline: none;
	}

	.crumbs__current {
		color: var(--terminal-fg-secondary);
	}
	.crumbs__current--accent {
		color: var(--terminal-fg-primary);
		font-weight: 600;
	}

	:global(.crumbs__sep) {
		width: 12px;
		height: 12px;
		color: var(--terminal-fg-muted);
	}

	.crumbs__portfolio {
		margin-left: auto;
		padding: 2px var(--terminal-space-2);
		border: 1px solid var(--terminal-accent-cyan);
		color: var(--terminal-accent-cyan);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		max-width: 40%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
