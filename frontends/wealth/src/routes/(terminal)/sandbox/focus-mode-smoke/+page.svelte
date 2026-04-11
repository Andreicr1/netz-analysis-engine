<!--
	/sandbox/focus-mode-smoke — dev-only smoke test for FocusMode primitive.

	Mounts FocusMode directly with an inline reactor snippet that renders
	seven fake analytics modules with staggered cascade. Validates at runtime:
	  - CSS custom property resolution from --terminal-* tokens
	  - Shell cascade timing (chrome/primary/secondary slots via svelteTransitionFor)
	  - Inner module cascade timing (tail slot + 80ms per-item stagger)
	  - Focus trap restore on close
	  - Backdrop click + ESC close behavior
	  - Snippet composition API (reactor + rail + default actions)
	  - Body scroll lock

	Deliberately decoupled from EntityAnalyticsVitrine to avoid backend
	dependency — this route validates the FocusMode SHELL, not the vitrine
	content. Real-fund vitrine validation happens against live fund ids
	in the Phase 3 screener surface.

	NOT a test — a manual verification surface. Keep permanent for future
	FocusMode consumers (Part C TerminalShell, Phase 3 Screener row
	triggers, Phase 4 Builder construction focus, etc.) to validate their
	triggers against a known-good shell baseline.
-->
<script lang="ts">
	import { fly } from "svelte/transition";
	import { quintOut } from "svelte/easing";
	import { delayFor, durationFor } from "@investintell/ui";
	import FocusMode from "$lib/components/terminal/focus-mode/FocusMode.svelte";

	let isOpen = $state(false);

	function openFocus() {
		isOpen = true;
	}

	function closeFocus() {
		isOpen = false;
	}

	// Noop handler for the per-module INSPECT buttons — they exist
	// purely to give the focus trap something meaningful to cycle
	// through. Real FocusMode consumers (Phase 3 screener, Phase 4
	// builder) will wire these to drill-down actions.
	function inspectModule(moduleId: string) {
		console.debug(`[smoke] inspect module ${moduleId}`);
	}

	// Inner module cascade: 7 modules starting from the `tail` slot
	// (after the shell's chrome → primary → secondary chain completes)
	// with 80ms per-item stagger. Duration matches the opening slot.
	const MODULE_STAGGER_MS = 80;
	const MODULE_BASE_DELAY = delayFor("tail");
	const MODULE_DURATION = durationFor("opening");

	function moduleTransition(index: number) {
		return {
			y: 16,
			duration: MODULE_DURATION,
			delay: MODULE_BASE_DELAY + index * MODULE_STAGGER_MS,
			easing: quintOut,
		};
	}

	// Fake module content — every module is a labeled rectangle with a
	// scalar metric and an ASCII sparkline, enough to see the cascade
	// clearly without pulling real data.
	const MODULES = [
		{
			id: "risk-stats",
			label: "RISK STATS",
			metric: "σ 14.32%",
			ascii: "▁▂▃▄▅▆▇█▇▆▅▄▃▂▁",
		},
		{
			id: "underwater",
			label: "UNDERWATER DRAWDOWN",
			metric: "−08.7%",
			ascii: "▔▔▔▔▔▔▔▁▂▃▄▅▆▇▇",
		},
		{
			id: "capture",
			label: "CAPTURE RATIOS",
			metric: "U 1.14 / D 0.92",
			ascii: "██▇▆▅▄▃▂▁▁▁▂▃▄▅",
		},
		{
			id: "rolling",
			label: "ROLLING RETURNS 36M",
			metric: "+12.47%",
			ascii: "▁▂▃▅▇█▇▆▄▃▂▃▄▅▆",
		},
		{
			id: "distribution",
			label: "RETURN DISTRIBUTION",
			metric: "skew −0.24",
			ascii: "▁▁▂▃▅▇█▇▅▃▂▁▁▁▁",
		},
		{
			id: "evestment",
			label: "EVESTMENT GRID",
			metric: "rank 12/247",
			ascii: "█▇▆▅▅▄▄▄▃▃▂▂▁▁▁",
		},
		{
			id: "insider",
			label: "INSIDER SENTIMENT",
			metric: "+0.42",
			ascii: "▄▄▄▄▅▆▇▇▇▇▆▆▅▄▄",
		},
	];

	const RAIL_CHIPS = [
		{ key: "ENTITY", value: "SMOKE-TEST" },
		{ key: "MODE", value: "SHELL-ONLY" },
		{ key: "SNAPSHOT", value: "FAKE-DATA" },
		{ key: "NAV", value: "n/a — sandbox" },
	];
</script>

<svelte:head>
	<title>Sandbox — FocusMode Smoke Test</title>
</svelte:head>

<div class="smoke-page">
	<header class="smoke-header">
		<h1 class="smoke-title">[ SANDBOX // FOCUS-MODE SMOKE TEST ]</h1>
	</header>

	<section class="smoke-body">
		<p class="smoke-intro">
			click [ OPEN WAR ROOM ] below, then verify:
		</p>

		<ol class="smoke-checklist">
			<li>backdrop fades in (chrome slot, tick duration)</li>
			<li>top bar fades in (chrome slot, 0ms delay)</li>
			<li>reactor flies up from y=20 at 120ms (primary slot)</li>
			<li>rail flies up from y=20 at 220ms (secondary slot)</li>
			<li>seven analytics modules cascade from 320ms with 80ms stagger</li>
			<li>press ESC — closes smoothly, no flicker</li>
			<li>click [ OPEN WAR ROOM ] again — focus returns to this button when closed</li>
			<li>keyboard: tab cycles through 7 INSPECT buttons + the ESC · CLOSE button, wrapping at the edges (shift+tab reverses)</li>
			<li>all text is monospace, all borders are 1px hairline, zero radius</li>
			<li>DOM inspector shows CSS custom properties --terminal-* resolving, no hex literals</li>
		</ol>

		<p class="smoke-warning">
			any failure → file issue against FocusMode primitive, not against this sandbox.
		</p>

		<button class="smoke-button" onclick={openFocus}>
			[ OPEN WAR ROOM ]
		</button>
	</section>
</div>

{#if isOpen}
	<FocusMode
		entityKind="fund"
		entityId="smoke-test"
		entityLabel="Terminal Shell Smoke Test"
		onClose={closeFocus}
		reactor={reactorSnippet}
		rail={railSnippet}
	/>
{/if}

{#snippet reactorSnippet()}
	<div class="smoke-reactor">
		<div class="smoke-reactor-heading">
			<span class="smoke-reactor-title">ANALYTICS CASCADE / SHELL SMOKE</span>
			<span class="smoke-reactor-sub">7 modules × 80ms stagger, quintOut</span>
		</div>
		<div class="smoke-module-grid">
			{#each MODULES as module, i (module.id)}
				<article class="smoke-module" in:fly={moduleTransition(i)}>
					<header class="smoke-module-header">
						<span class="smoke-module-index">M{String(i + 1).padStart(2, "0")}</span>
						<span class="smoke-module-label">{module.label}</span>
					</header>
					<div class="smoke-module-metric">{module.metric}</div>
					<div class="smoke-module-ascii">{module.ascii}</div>
					<footer class="smoke-module-footer">
						<button
							type="button"
							class="smoke-module-inspect"
							onclick={() => inspectModule(module.id)}
						>
							[ INSPECT ]
						</button>
					</footer>
				</article>
			{/each}
		</div>
	</div>
{/snippet}

{#snippet railSnippet()}
	<div class="smoke-rail-inner">
		{#each RAIL_CHIPS as chip (chip.key)}
			<div class="smoke-rail-chip">
				<div class="smoke-rail-chip-key">{chip.key}</div>
				<div class="smoke-rail-chip-value">{chip.value}</div>
			</div>
		{/each}
	</div>
{/snippet}

<style>
	.smoke-page {
		height: 100%;
		background: var(--terminal-bg-void);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		padding: var(--terminal-space-6);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-6);
		overflow-y: auto;
	}

	.smoke-header {
		border-bottom: var(--terminal-border-hairline);
		padding-bottom: var(--terminal-space-4);
		flex-shrink: 0;
	}

	.smoke-title {
		font-size: var(--terminal-text-16);
		font-weight: normal;
		letter-spacing: var(--terminal-tracking-caps);
		margin: 0;
		color: var(--terminal-accent-amber);
	}

	.smoke-body {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
		max-width: 720px;
	}

	.smoke-intro {
		font-size: var(--terminal-text-11);
		margin: 0;
	}

	.smoke-checklist {
		font-size: var(--terminal-text-11);
		line-height: var(--terminal-leading-normal);
		padding-left: var(--terminal-space-6);
		color: var(--terminal-fg-secondary);
		margin: 0;
	}

	.smoke-checklist li {
		margin-bottom: var(--terminal-space-1);
	}

	.smoke-warning {
		font-size: var(--terminal-text-11);
		color: var(--terminal-status-warn);
		margin: var(--terminal-space-2) 0;
	}

	.smoke-button {
		align-self: flex-start;
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		padding: var(--terminal-space-2) var(--terminal-space-4);
		cursor: pointer;
		transition: border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.smoke-button:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.smoke-button:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	/* Reactor content — fake analytics modules with cascade. */
	.smoke-reactor {
		padding: var(--terminal-space-6);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-6);
		height: 100%;
		box-sizing: border-box;
	}

	.smoke-reactor-heading {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
		border-bottom: var(--terminal-border-hairline);
		padding-bottom: var(--terminal-space-3);
	}

	.smoke-reactor-title {
		font-size: var(--terminal-text-14);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
		font-weight: 700;
	}

	.smoke-reactor-sub {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-tertiary);
	}

	.smoke-module-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: var(--terminal-space-4);
	}

	.smoke-module {
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		padding: var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
	}

	.smoke-module-header {
		display: flex;
		align-items: baseline;
		gap: var(--terminal-space-3);
		border-bottom: 1px dashed var(--terminal-fg-muted);
		padding-bottom: var(--terminal-space-2);
	}

	.smoke-module-index {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.smoke-module-label {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.smoke-module-metric {
		font-size: var(--terminal-text-20);
		color: var(--terminal-accent-amber);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.02em;
	}

	.smoke-module-ascii {
		font-size: var(--terminal-text-14);
		line-height: 1;
		color: var(--terminal-accent-cyan);
		letter-spacing: 0.05em;
	}

	.smoke-module-footer {
		display: flex;
		justify-content: flex-end;
		border-top: 1px dashed var(--terminal-fg-muted);
		padding-top: var(--terminal-space-2);
	}

	.smoke-module-inspect {
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-secondary);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		padding: 4px 10px;
		cursor: pointer;
		text-transform: uppercase;
		transition:
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.smoke-module-inspect:hover {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.smoke-module-inspect:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	/* Rail content — metadata chips. */
	.smoke-rail-inner {
		display: grid;
		grid-auto-rows: min-content;
		gap: 1px;
		background: transparent;
	}

	.smoke-rail-chip {
		padding: var(--terminal-space-3) var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-1);
	}

	.smoke-rail-chip-key {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.smoke-rail-chip-value {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-primary);
		font-variant-numeric: tabular-nums;
	}
</style>
