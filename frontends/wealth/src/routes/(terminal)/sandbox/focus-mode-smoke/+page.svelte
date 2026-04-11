<!--
	/sandbox/focus-mode-smoke — dev-only smoke test for FocusMode primitive.

	Mounts FundFocusMode against a mock fund id. Validates at runtime:
	  - CSS custom property resolution from --terminal-* tokens
	  - Motion cascade timing (choreo slots)
	  - Focus trap restore on close
	  - Backdrop click + ESC close behavior
	  - Snippet composition rendering EntityAnalyticsVitrine

	NOT a test — a manual verification surface. Keep permanent for
	future FocusMode consumers (Part C TerminalShell, Phase 3 Screener,
	Phase 4 Builder, etc.) to validate their triggers.
-->
<script lang="ts">
	import FundFocusMode from "$lib/components/terminal/focus-mode/fund/FundFocusMode.svelte";

	let isOpen = $state(false);

	const MOCK_FUND_ID = "smoke-test-fund-00000000-0000-0000-0000-000000000000";
	const MOCK_FUND_LABEL = "SMOKE TEST FUND";

	function openFocus() {
		isOpen = true;
	}

	function closeFocus() {
		isOpen = false;
	}
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
			<li>backdrop fades in (t=0ms, chrome slot, tick duration)</li>
			<li>top bar fades in (chrome slot)</li>
			<li>reactor flies up from y=20 at t=120ms (primary slot)</li>
			<li>rail flies up from y=20 at t=220ms (secondary slot)</li>
			<li>seven analytics modules cascade inside the reactor</li>
			<li>press ESC — closes smoothly, no flicker</li>
			<li>click [ OPEN WAR ROOM ] again — focus returns to this button when closed</li>
			<li>keyboard: tab navigates inside the modal, wraps around the focus ring</li>
			<li>all text is monospace, all borders are 1px hairline, zero radius</li>
			<li>DOM inspector shows CSS custom properties --terminal-* resolving, no hex literals</li>
		</ol>

		<p class="smoke-warning">
			any failure → file issue, roll back the offending primitive change.
		</p>

		<button class="smoke-button" onclick={openFocus}>
			[ OPEN WAR ROOM ]
		</button>
	</section>
</div>

{#if isOpen}
	<FundFocusMode
		fundId={MOCK_FUND_ID}
		fundLabel={MOCK_FUND_LABEL}
		onClose={closeFocus}
	/>
{/if}

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
</style>
