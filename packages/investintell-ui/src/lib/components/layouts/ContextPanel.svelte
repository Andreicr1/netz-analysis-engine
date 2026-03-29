<!--
  @component ContextPanel
  Slide-in panel from right side with overlay backdrop on mobile, focus trap, and Escape key handler.

  Actively used in:
  - wealth screener (instrument detail, run detail, history panels)
  - wealth instruments page (instrument detail)
  - wealth risk page (risk detail)
  - wealth portfolios page (portfolio detail)
  - wealth FundDetailPanel component (fund detail slide-in)
  - credit pipeline page (deal detail panel)
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";

	let {
		open = false,
		onClose,
		title,
		width = "400px",
		class: className,
		children,
	}: {
		open?: boolean;
		onClose: () => void;
		title?: string;
		width?: string;
		class?: string;
		children?: Snippet;
	} = $props();

	let panelEl: HTMLElement | undefined = $state(undefined);

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			onClose();
		}

		// Focus trap: cycle focus within the panel
		if (e.key === "Tab" && panelEl) {
			const focusable = panelEl.querySelectorAll<HTMLElement>(
				'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
			);
			if (focusable.length === 0) return;

			const first = focusable[0] as HTMLElement | undefined;
			const last = focusable[focusable.length - 1] as HTMLElement | undefined;

			if (e.shiftKey && document.activeElement === first && last) {
				e.preventDefault();
				last.focus();
			} else if (!e.shiftKey && document.activeElement === last && first) {
				e.preventDefault();
				first.focus();
			}
		}
	}

	$effect(() => {
		if (open && panelEl) {
			// Focus the panel when it opens
			const firstFocusable = panelEl.querySelector<HTMLElement>(
				'button, a[href], input, textarea, select, [tabindex]:not([tabindex="-1"])'
			);
			firstFocusable?.focus();
		}
	});
</script>

{#if open}
	<button class="ii-context-panel__backdrop" onclick={onClose} aria-label="Close panel" tabindex="-1"></button>
{/if}

<div
	bind:this={panelEl}
	class={cn("ii-context-panel", open && "ii-context-panel--open", className)}
	style:--panel-width={width}
	role="dialog"
	tabindex="-1"
	aria-modal={open ? "true" : undefined}
	aria-label={title || "Context panel"}
	onkeydown={open ? handleKeydown : undefined}
>
	<div class="ii-context-panel__header">
		{#if title}
			<h2 class="ii-context-panel__title">{title}</h2>
		{/if}
		<button
			class="ii-context-panel__close"
			onclick={onClose}
			aria-label="Close panel"
			type="button"
		>
			<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
				<path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
			</svg>
		</button>
	</div>

	<div class="ii-context-panel__body">
		{@render children?.()}
	</div>
</div>

<style>
	.ii-context-panel__backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.3);
		z-index: 39;
		display: none;
	}

	.ii-context-panel {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: var(--panel-width, 400px);
		background: var(--ii-surface, #ffffff);
		border-left: 1px solid var(--ii-border, #e5e7eb);
		z-index: 40;
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform 200ms ease;
		box-shadow: -4px 0 24px rgba(0, 0, 0, 0);
	}

	.ii-context-panel--open {
		transform: translateX(0);
		box-shadow: -4px 0 24px rgba(0, 0, 0, 0.08);
	}

	.ii-context-panel__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		border-bottom: 1px solid var(--ii-border, #e5e7eb);
		flex-shrink: 0;
	}

	.ii-context-panel__title {
		margin: 0;
		font-size: 16px;
		font-weight: 600;
		color: var(--ii-text-primary, #111827);
		line-height: 1.4;
	}

	.ii-context-panel__close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-muted, #9ca3af);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
		flex-shrink: 0;
	}

	.ii-context-panel__close:hover {
		background: var(--ii-surface-alt, #f3f4f6);
		color: var(--ii-text-primary, #111827);
	}

	.ii-context-panel__body {
		flex: 1;
		overflow-y: auto;
		padding: 20px;
	}

	/* Mobile: show backdrop overlay */
	@media (max-width: 1023px) {
		.ii-context-panel__backdrop {
			display: block;
		}
		.ii-context-panel {
			width: min(var(--panel-width, 400px), 100vw);
		}
	}

	@media (max-width: 599px) {
		.ii-context-panel {
			width: 100vw;
		}
	}
</style>
