<!--
  LibraryWrapper — embeds the existing LibraryShell in the terminal
  Research surface with CSS variable remapping so library components
  render with terminal tokens without rewriting them.

  Data fetching is client-side (no +page.server.ts) — the tree
  payload is fetched on mount via the auth'd API client.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import LibraryShell from "$wealth/components/library/LibraryShell.svelte";
	import { createClientApiClient } from "$wealth/api/client";
	import type { LibraryTree } from "$wealth/types/library";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	let tree = $state<LibraryTree | null>(null);
	let loading = $state(true);
	let errorMsg = $state<string | null>(null);

	onMount(async () => {
		try {
			tree = await api.get<LibraryTree>("/library/tree");
		} catch (err: unknown) {
			errorMsg = err instanceof Error ? err.message : "Failed to load library tree";
		} finally {
			loading = false;
		}
	});
</script>

<div class="library-terminal-wrapper">
	{#if loading}
		<div class="lw-empty">
			<span class="lw-empty-text">Loading library...</span>
		</div>
	{:else if errorMsg}
		<div class="lw-empty">
			<span class="lw-empty-text lw-err">{errorMsg}</span>
		</div>
	{:else if tree}
		<LibraryShell {tree} initialPath={null} actorRole={null} />
	{:else}
		<div class="lw-empty">
			<span class="lw-empty-text">Library is empty</span>
		</div>
	{/if}
</div>

<style>
	.library-terminal-wrapper {
		width: 100%;
		height: 100%;
		overflow: hidden;

		/* ── CSS variable remapping: --ii-* → --terminal-* ── */

		/* Surfaces */
		--ii-surface: var(--terminal-bg-surface);
		--ii-surface-alt: var(--terminal-bg-panel);
		--ii-surface-elevated: var(--terminal-bg-panel-raised);

		/* Text */
		--ii-text-primary: var(--terminal-fg-primary);
		--ii-text-secondary: var(--terminal-fg-secondary);
		--ii-text-muted: var(--terminal-fg-muted);
		--ii-text-on-brand: var(--terminal-fg-primary);

		/* Borders */
		--ii-border-subtle: var(--terminal-border-hairline);
		--ii-border-accent: var(--terminal-accent-cyan);
		--ii-border: var(--terminal-border-hairline);

		/* Brand / status */
		--ii-brand-primary: var(--terminal-accent-cyan);
		--ii-success: var(--terminal-status-success);
		--ii-danger: var(--terminal-status-error);
		--ii-warning: var(--terminal-status-warn);
		--ii-info: var(--terminal-accent-cyan);

		/* Font */
		--ii-font-sans: var(--terminal-font-mono);
		--ii-font-mono: var(--terminal-font-mono);

		/* Radius — terminal uses 0 */
		--ii-radius-sm: 0px;
		--ii-radius-pill: 0px;

		font-family: var(--terminal-font-mono);
		border-radius: 0;
	}

	/* Override hex colors that library components use directly */
	.library-terminal-wrapper :global(.library-shell) {
		background: var(--terminal-bg-surface);
		color: var(--terminal-fg-secondary);
		border-radius: 0;
		height: 100%;
	}

	.library-terminal-wrapper :global(.library-header) {
		background: var(--terminal-bg-surface);
		border-bottom-color: var(--terminal-border-hairline-color, rgba(255, 255, 255, 0.06));
	}

	.library-terminal-wrapper :global(.pane--tree) {
		background: var(--terminal-bg-surface);
		border-right-color: var(--terminal-border-hairline-color, rgba(255, 255, 255, 0.06));
	}

	.library-terminal-wrapper :global(.pane--content) {
		background: var(--terminal-bg-surface);
	}

	.library-terminal-wrapper :global(.pane--preview) {
		background: var(--terminal-bg-surface);
		border-left-color: var(--terminal-border-hairline-color, rgba(255, 255, 255, 0.06));
	}

	.library-terminal-wrapper :global(.view-placeholder) {
		color: var(--terminal-fg-muted);
	}

	.library-terminal-wrapper :global(.view-placeholder__title) {
		color: var(--terminal-fg-primary);
	}

	.library-terminal-wrapper :global(.content-empty) {
		color: var(--terminal-fg-muted);
	}

	.library-terminal-wrapper :global(.content-empty__title) {
		color: var(--terminal-fg-primary);
	}

	.library-terminal-wrapper :global(.content-empty__sub) {
		color: var(--terminal-fg-muted);
	}

	/* ── Empty / loading states ── */
	.lw-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--terminal-fg-muted);
	}

	.lw-empty-text {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		letter-spacing: 0.04em;
	}

	.lw-err {
		color: var(--terminal-status-error);
	}
</style>
