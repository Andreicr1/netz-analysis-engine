<!--
	TerminalTweaksPanel.svelte
	==========================

	Floating gear button (bottom-right) + right-side drawer with density,
	accent, and theme toggles. Reads/writes the terminal-tweaks store
	wired via context at (terminal)/+layout.svelte.

	Source: docs/plans/2026-04-18-netz-terminal-parity.md §C.2.

	Keyboard: Shift+T toggles open/close. Ignored inside editable fields.
	Mount location: TerminalShell root (OUTSIDE LayoutCage) so the drawer
	is unaffected by the cage padding override pattern — see plan §H risk #4.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import {
		TerminalAccentPicker,
		TerminalDensityToggle,
		TerminalPill,
		TerminalThemeToggle,
		TerminalKbd,
	} from "@investintell/ui";
	import {
		TERMINAL_TWEAKS_KEY,
		type TerminalTweaks,
	} from "../../../stores/terminal-tweaks.svelte";

	const tweaks = getContext<TerminalTweaks>(TERMINAL_TWEAKS_KEY);

	let open = $state(false);

	function isEditableTarget(target: EventTarget | null): boolean {
		if (!(target instanceof HTMLElement)) return false;
		const tag = target.tagName;
		if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
		if (target.isContentEditable) return true;
		const role = target.getAttribute("role");
		if (role === "textbox" || role === "searchbox" || role === "combobox") {
			return true;
		}
		return false;
	}

	$effect(() => {
		if (typeof window === "undefined") return;
		const handler = (event: KeyboardEvent) => {
			if (
				event.shiftKey &&
				!event.metaKey &&
				!event.ctrlKey &&
				!event.altKey &&
				(event.key === "T" || event.key === "t")
			) {
				if (isEditableTarget(event.target)) return;
				event.preventDefault();
				open = !open;
			} else if (event.key === "Escape" && open) {
				open = false;
			}
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	});
</script>

<button
	type="button"
	class="tweaks-fab"
	aria-label="Open terminal tweaks (Shift+T)"
	aria-expanded={open}
	aria-controls="terminal-tweaks-drawer"
	onclick={() => (open = !open)}
>
	<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
		<path
			fill="none"
			stroke="currentColor"
			stroke-width="1.25"
			d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Zm5.6 2.5a5.7 5.7 0 0 0-.1-1l1.3-1-1.3-2.3-1.6.5a5.6 5.6 0 0 0-1.7-1L9.8 1H7.2l-.4 1.7a5.6 5.6 0 0 0-1.7 1l-1.6-.5-1.3 2.3 1.3 1a5.7 5.7 0 0 0 0 2l-1.3 1 1.3 2.3 1.6-.5a5.6 5.6 0 0 0 1.7 1l.4 1.7h2.6l.4-1.7a5.6 5.6 0 0 0 1.7-1l1.6.5 1.3-2.3-1.3-1c.1-.3.1-.7.1-1Z"
		/>
	</svg>
</button>

{#if open}
	<div
		class="tweaks-scrim"
		aria-hidden="true"
		role="presentation"
		onclick={() => (open = false)}
		onkeydown={(e) => {
			if (e.key === "Enter" || e.key === " ") open = false;
		}}
	></div>
	<div
		id="terminal-tweaks-drawer"
		class="tweaks-drawer"
		role="dialog"
		aria-modal="true"
		aria-label="Terminal tweaks"
		tabindex="-1"
	>
		<header class="tweaks-header">
			<span class="tweaks-title">TWEAKS</span>
			<span class="tweaks-shortcut">
				<TerminalKbd keys={["Shift", "T"]} />
			</span>
			<button
				type="button"
				class="tweaks-close"
				aria-label="Close"
				onclick={() => (open = false)}
			>
				×
			</button>
		</header>

		<section class="tweaks-section">
			<div class="tweaks-section__label">DENSITY</div>
			<TerminalDensityToggle
				value={tweaks.density}
				onChange={(v) => tweaks.setDensity(v)}
			/>
		</section>

		<section class="tweaks-section">
			<div class="tweaks-section__label">ACCENT</div>
			<TerminalAccentPicker
				value={tweaks.accent}
				onChange={(v) => tweaks.setAccent(v)}
			/>
		</section>

		<section class="tweaks-section">
			<div class="tweaks-section__label">THEME</div>
			<TerminalThemeToggle
				value={tweaks.theme}
				onChange={(v) => tweaks.setTheme(v)}
			/>
		</section>

		<section class="tweaks-section">
			<div class="tweaks-section__label">LIVE SIM</div>
			<TerminalPill label="OFF" tone="neutral" size="sm" />
		</section>
	</div>
{/if}

<style>
	.tweaks-fab {
		position: fixed;
		bottom: calc(var(--terminal-shell-statusbar-height) + var(--terminal-space-3));
		right: var(--terminal-space-3);
		z-index: var(--terminal-z-toast);
		width: 32px;
		height: 32px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-fg-secondary);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		cursor: pointer;
		transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.tweaks-fab:hover {
		color: var(--terminal-accent-amber);
		border-color: var(--terminal-accent-amber);
	}
	.tweaks-fab:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.tweaks-scrim {
		position: fixed;
		inset: 0;
		background: var(--terminal-bg-scrim);
		z-index: calc(var(--terminal-z-toast) - 1);
	}

	.tweaks-drawer {
		position: fixed;
		top: var(--terminal-shell-topbar-height);
		right: 0;
		bottom: var(--terminal-shell-statusbar-height);
		width: 320px;
		background: var(--terminal-bg-panel);
		border-left: var(--terminal-border-strong);
		z-index: var(--terminal-z-toast);
		padding: var(--terminal-space-4);
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-6);
		overflow-y: auto;
		font-family: var(--terminal-font-mono);
	}

	.tweaks-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding-bottom: var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
	}

	.tweaks-title {
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-primary);
		text-transform: uppercase;
		flex: 1;
	}
	.tweaks-shortcut {
		display: inline-flex;
	}
	.tweaks-close {
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
	.tweaks-close:hover {
		color: var(--terminal-fg-primary);
		border-color: var(--terminal-fg-secondary);
	}
	.tweaks-close:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 1px;
	}

	.tweaks-section {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
	}
	.tweaks-section__label {
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}
</style>
