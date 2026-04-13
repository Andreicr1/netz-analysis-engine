<!--
  ActivationBar — Zone F fixed footer in the Builder right column.

  Appears ONLY when: runPhase === "done" AND allTabsVisited === true.
  Two buttons: Save as Draft + Activate Portfolio (opens ConsequenceDialog).
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import ConsequenceDialog from "./ConsequenceDialog.svelte";

	interface Props {
		allTabsVisited: boolean;
	}

	let { allTabsVisited }: Props = $props();

	const visible = $derived(workspace.runPhase === "done" && allTabsVisited);

	let showDialog = $state(false);
	let successBanner = $state(false);

	async function handleSaveDraft() {
		// Draft is the current state — no explicit save needed beyond
		// the already-persisted construction run. This is a UX affordance
		// to reassure PMs their work is saved.
	}

	function handleActivateClick() {
		showDialog = true;
	}

	function handleDialogClose() {
		showDialog = false;
	}

	function handleActivateSuccess() {
		showDialog = false;
		successBanner = true;
	}
</script>

{#if visible}
	<div class="ab-bar">
		<button type="button" class="ab-btn ab-btn--secondary" onclick={handleSaveDraft}>
			Save as Draft
		</button>
		<button type="button" class="ab-btn ab-btn--primary" onclick={handleActivateClick}>
			Activate Portfolio
		</button>
	</div>
{/if}

{#if successBanner}
	<div class="ab-success">
		Portfolio activated &mdash;
		<a href="/portfolio/live" class="ab-success-link">view in Live Workbench</a>
	</div>
{/if}

{#if showDialog}
	<ConsequenceDialog
		onclose={handleDialogClose}
		onsuccess={handleActivateSuccess}
	/>
{/if}

<style>
	.ab-bar {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--terminal-space-2);
		height: 48px;
		padding: 0 var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		flex-shrink: 0;
	}

	.ab-btn {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: var(--terminal-space-1) var(--terminal-space-3);
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition:
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.ab-btn--secondary {
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-secondary);
	}

	.ab-btn--secondary:hover {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
	}

	.ab-btn--primary {
		background: var(--terminal-accent-amber);
		border: 1px solid var(--terminal-accent-amber);
		color: var(--terminal-bg-void);
	}

	.ab-btn--primary:hover {
		opacity: 0.9;
	}

	.ab-btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}

	.ab-success {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-1);
		height: 36px;
		background: var(--terminal-status-success);
		color: var(--terminal-bg-void);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.ab-success-link {
		color: var(--terminal-bg-void);
		text-decoration: underline;
	}
</style>
