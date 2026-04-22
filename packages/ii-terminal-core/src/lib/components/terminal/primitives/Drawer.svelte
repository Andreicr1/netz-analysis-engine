<!--
	Drawer.svelte
	=============

	Tokenized right/left-anchored drawer. Mounts between the topbar
	and statusbar (outside LayoutCage per the cage-padding pattern).
	Scrim click + ESC close. Programmatic focus on open. Manual
	Tab/Shift+Tab trap across focusable descendants.

	Consumers pass a Snippet for the body; Drawer itself owns only
	the header (title + close affordance) plus the dialog chrome.

	Source: docs/plans/2026-04-19-netz-terminal-parity-builder-macro-screener.md §B.5.
-->
<script lang="ts">
	import type { Snippet } from "svelte";

	export type DrawerSide = "left" | "right";

	interface Props {
		open: boolean;
		label: string;
		side?: DrawerSide;
		width?: number;
		onClose?: () => void;
		children: Snippet;
		title?: Snippet;
		footer?: Snippet;
	}

	let {
		open,
		label,
		side = "right",
		width = 320,
		onClose = () => {},
		children,
		title,
		footer,
	}: Props = $props();

	let dialogEl: HTMLDivElement | null = $state(null);

	const FOCUSABLE_SELECTOR =
		"a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

	$effect(() => {
		if (!open || !dialogEl) return;
		// Defer focus to after insertion paint.
		const handle = window.requestAnimationFrame(() => {
			dialogEl?.focus();
		});
		return () => window.cancelAnimationFrame(handle);
	});

	function handleKeydown(event: KeyboardEvent) {
		if (!open) return;
		if (event.key === "Escape") {
			event.preventDefault();
			onClose();
			return;
		}
		if (event.key !== "Tab" || !dialogEl) return;
		const focusables = Array.from(
			dialogEl.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
		).filter((el) => !el.hasAttribute("aria-hidden"));
		if (focusables.length === 0) {
			event.preventDefault();
			dialogEl.focus();
			return;
		}
		const first = focusables[0]!;
		const last = focusables[focusables.length - 1]!;
		const active = document.activeElement as HTMLElement | null;
		if (event.shiftKey) {
			if (active === first || active === dialogEl) {
				event.preventDefault();
				last.focus();
			}
		} else {
			if (active === last) {
				event.preventDefault();
				first.focus();
			}
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<div
		class="drawer-scrim"
		aria-hidden="true"
		role="presentation"
		onclick={() => onClose()}
		onkeydown={(e) => {
			if (e.key === "Enter" || e.key === " ") onClose();
		}}
	></div>
	<div
		bind:this={dialogEl}
		class="drawer drawer--{side}"
		role="dialog"
		aria-modal="true"
		aria-label={label}
		tabindex="-1"
		style:width="{width}px"
	>
		<header class="drawer__header">
			{#if title}
				{@render title()}
			{:else}
				<span class="drawer__title">{label}</span>
			{/if}
			<button
				type="button"
				class="drawer__close"
				aria-label="Close"
				onclick={() => onClose()}
			>
				×
			</button>
		</header>
		<div class="drawer__body">
			{@render children()}
		</div>
		{#if footer}
			<footer class="drawer__footer">
				{@render footer()}
			</footer>
		{/if}
	</div>
{/if}

<style>
	.drawer-scrim {
		position: fixed;
		inset: 0;
		background: var(--terminal-bg-scrim);
		z-index: calc(var(--terminal-z-toast) - 1);
	}

	.drawer {
		position: fixed;
		top: var(--terminal-shell-topbar-height);
		bottom: var(--terminal-shell-statusbar-height);
		background: var(--terminal-bg-panel);
		z-index: var(--terminal-z-toast);
		padding: var(--terminal-space-4);
		display: grid;
		grid-template-rows: auto 1fr auto;
		gap: var(--terminal-space-4);
		overflow-y: auto;
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}
	.drawer--right {
		right: 0;
		border-left: var(--terminal-border-strong);
	}
	.drawer--left {
		left: 0;
		border-right: var(--terminal-border-strong);
	}
	.drawer:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -1px;
	}

	.drawer__header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding-bottom: var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
	}
	.drawer__title {
		flex: 1;
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
		text-transform: uppercase;
	}
	.drawer__close {
		width: 20px;
		height: 20px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: transparent;
		color: var(--terminal-fg-tertiary);
		border: var(--terminal-border-hairline);
		font-size: var(--terminal-text-14);
		line-height: 1;
		cursor: pointer;
	}
	.drawer__close:hover {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
	}
	.drawer__close:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.drawer__body {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
		min-height: 0;
	}

	.drawer__footer {
		padding-top: var(--terminal-space-3);
		border-top: var(--terminal-border-hairline);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
	}
</style>
