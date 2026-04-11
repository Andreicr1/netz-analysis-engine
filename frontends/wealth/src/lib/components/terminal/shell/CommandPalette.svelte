<!--
	CommandPalette.svelte — Cmd+K launcher overlay.
	===============================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell, Appendix B navigation flow.

	WAI-ARIA combobox overlay with listbox results. Seeded with 8 go-to
	navigation commands (3 active, 5 pending) matching the TerminalTopNav
	tab catalog. Pending commands stay visible so users see the full
	terminal vision.

	Full-viewport backdrop (var(--terminal-bg-scrim)), centered 640px
	frame, brutalist chrome, auto-focus on open, focus restore on close,
	body scroll lock, ESC/Enter/↑/↓ keyboard handling, simple substring
	filter on label + hint.

	Navigation uses `const target = resolve("/..."); await goto(target);`
	per the svelte/no-navigation-without-resolve rule — the AST matcher
	only accepts a plain Identifier passed to goto.

	Z-index var(--terminal-z-palette) = 70, above FocusMode (60) so the
	palette can open inside an active focus mode.
-->
<script lang="ts">
	import { fade, fly } from "svelte/transition";
	import { svelteTransitionFor } from "@investintell/ui";
	import { goto } from "$app/navigation";
	import { resolve } from "$app/paths";

	interface CommandPaletteProps {
		/** Bindable. TerminalShell toggles this from Cmd+K. */
		open: boolean;
	}

	let { open = $bindable() }: CommandPaletteProps = $props();

	type CommandStatus = "active" | "pending";

	interface Command {
		id: string;
		label: string;
		hint: string;
		status: CommandStatus;
		action: () => void | Promise<void>;
	}

	// ─────────────────────────────────────────────────────────────
	// Active command actions — extracted-const resolve() pattern.
	// ─────────────────────────────────────────────────────────────

	async function gotoScreener() {
		const target = resolve("/terminal-screener");
		await goto(target);
	}

	async function gotoLive() {
		const target = resolve("/portfolio/live");
		await goto(target);
	}

	async function gotoResearch() {
		const target = resolve("/research");
		await goto(target);
	}

	// Pending actions are intentional no-ops. Triggering a pending
	// command plays a shake animation on its row and keeps the palette
	// open so the user sees the "not yet wired" signal.
	function pendingAction() {
		/* no-op — see handleEnter for UX feedback */
	}

	const COMMANDS: ReadonlyArray<Command> = [
		{ id: "nav.screener", label: "Go to Screener",        hint: "g s", status: "active",  action: gotoScreener },
		{ id: "nav.live",     label: "Go to Live Workbench",  hint: "g l", status: "active",  action: gotoLive },
		{ id: "nav.research", label: "Go to Research",        hint: "g r", status: "active",  action: gotoResearch },
		{ id: "nav.macro",    label: "Go to Macro Desk",      hint: "g m", status: "pending", action: pendingAction },
		{ id: "nav.alloc",    label: "Go to Allocation",      hint: "g a", status: "pending", action: pendingAction },
		{ id: "nav.builder",  label: "Go to Portfolio Builder", hint: "g p", status: "pending", action: pendingAction },
		{ id: "nav.alerts",   label: "Go to Alerts",          hint: "g n", status: "pending", action: pendingAction },
		{ id: "nav.dd",       label: "Go to DD Queue",        hint: "g d", status: "pending", action: pendingAction },
	];

	let query = $state("");
	let highlightedIndex = $state(0);
	let inputEl: HTMLInputElement | undefined = $state();
	let frameEl: HTMLDivElement | undefined = $state();
	let shakeKey = $state(0);

	const filtered = $derived.by<Command[]>(() => {
		const q = query.trim().toLowerCase();
		if (q.length === 0) return [...COMMANDS];
		return COMMANDS.filter(
			(c) =>
				c.label.toLowerCase().includes(q) ||
				c.hint.toLowerCase().includes(q),
		);
	});

	$effect(() => {
		// Clamp the highlighted index whenever the filtered list shrinks.
		if (filtered.length === 0) {
			highlightedIndex = 0;
			return;
		}
		if (highlightedIndex >= filtered.length) {
			highlightedIndex = filtered.length - 1;
		}
	});

	// Focus lifecycle — mirror FocusMode's pattern: restore focus on
	// close, body scroll lock while open.
	$effect(() => {
		if (!open) return;
		if (typeof document === "undefined") return;
		const previousOverflow = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		const previouslyFocused = document.activeElement as HTMLElement | null;
		query = "";
		highlightedIndex = 0;
		queueMicrotask(() => {
			inputEl?.focus({ preventScroll: true });
		});
		return () => {
			document.body.style.overflow = previousOverflow;
			if (
				previouslyFocused &&
				typeof previouslyFocused.focus === "function"
			) {
				previouslyFocused.focus({ preventScroll: true });
			}
		};
	});

	function handleBackdropClick(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			open = false;
		}
	}

	function handleFrameClick(event: MouseEvent) {
		event.stopPropagation();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === "Escape") {
			event.preventDefault();
			open = false;
			return;
		}
		if (event.key === "ArrowDown") {
			event.preventDefault();
			if (filtered.length === 0) return;
			highlightedIndex = (highlightedIndex + 1) % filtered.length;
			return;
		}
		if (event.key === "ArrowUp") {
			event.preventDefault();
			if (filtered.length === 0) return;
			highlightedIndex =
				(highlightedIndex - 1 + filtered.length) % filtered.length;
			return;
		}
		if (event.key === "Enter") {
			event.preventDefault();
			handleEnter();
			return;
		}
	}

	function handleEnter() {
		const command = filtered[highlightedIndex];
		if (!command) return;
		if (command.status === "pending") {
			// Visual shake feedback — increment key so the row remounts
			// its animation.
			shakeKey += 1;
			return;
		}
		const result = command.action();
		if (result && typeof (result as Promise<void>).then === "function") {
			(result as Promise<void>).then(
				() => {
					open = false;
				},
				() => {
					/* swallow navigation errors — palette stays open so
					   the user can retry */
				},
			);
		} else {
			open = false;
		}
	}

	function handleOptionClick(index: number) {
		highlightedIndex = index;
		handleEnter();
	}

	const optionIdFor = (id: string) => `cp-option-${id}`;

	const listboxId = "terminal-command-palette-listbox";
	const inputId = "terminal-command-palette-input";
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div
		class="cp-backdrop"
		role="presentation"
		onclick={handleBackdropClick}
		transition:fade={svelteTransitionFor("chrome", { duration: "tick" })}
	>
		<div
			bind:this={frameEl}
			class="cp-frame"
			role="dialog"
			aria-modal="true"
			aria-label="Command palette"
			tabindex="-1"
			onclick={handleFrameClick}
			in:fly={{ y: -12, ...svelteTransitionFor("chrome", { duration: "tick" }) }}
		>
			<header class="cp-header">
				<span class="cp-prompt">⌘</span>
				<input
					bind:this={inputEl}
					bind:value={query}
					id={inputId}
					class="cp-input"
					type="text"
					placeholder="Type a command or search..."
					autocomplete="off"
					autocorrect="off"
					autocapitalize="off"
					spellcheck="false"
					role="combobox"
					aria-expanded="true"
					aria-controls={listboxId}
					aria-activedescendant={(() => {
						const current = filtered[highlightedIndex];
						return current ? optionIdFor(current.id) : undefined;
					})()}
					onkeydown={handleKeydown}
				/>
			</header>

			<ul id={listboxId} class="cp-list" role="listbox">
				{#each filtered as cmd, i (cmd.id)}
					{@const isHighlighted = i === highlightedIndex}
					{@const shouldShake =
						isHighlighted && cmd.status === "pending" && shakeKey > 0}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<li
						id={optionIdFor(cmd.id)}
						class="cp-option"
						class:cp-option--highlighted={isHighlighted}
						class:cp-option--pending={cmd.status === "pending"}
						class:cp-option--shake={shouldShake}
						role="option"
						aria-selected={isHighlighted}
						onclick={() => handleOptionClick(i)}
						onmouseenter={() => (highlightedIndex = i)}
					>
						<span class="cp-option-label">{cmd.label}</span>
						<span class="cp-option-right">
							{#if cmd.status === "pending"}
								<span class="cp-option-badge">PENDING</span>
							{/if}
							<span class="cp-option-hint">{cmd.hint}</span>
						</span>
					</li>
				{:else}
					<li class="cp-empty">NO MATCHES</li>
				{/each}
			</ul>

			<footer class="cp-footer">
				<span class="cp-footer-count">{filtered.length} results</span>
				<span class="cp-footer-keys">↑↓ navigate · ⏎ select · ESC close</span>
			</footer>
		</div>
	</div>
{/if}

<style>
	.cp-backdrop {
		position: fixed;
		inset: 0;
		z-index: var(--terminal-z-palette);
		background: var(--terminal-bg-scrim);
		backdrop-filter: blur(3px);
		-webkit-backdrop-filter: blur(3px);
		display: grid;
		place-items: start center;
		padding-top: 14vh;
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
	}

	.cp-frame {
		width: 640px;
		max-width: calc(100vw - var(--terminal-space-8));
		max-height: 60vh;
		background: var(--terminal-bg-void);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		display: grid;
		grid-template-rows: auto 1fr auto;
		overflow: hidden;
		box-shadow: 0 0 0 1px var(--terminal-fg-muted);
	}

	.cp-header {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-3) var(--terminal-space-4);
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
	}

	.cp-prompt {
		color: var(--terminal-accent-amber);
		font-size: var(--terminal-text-14);
		font-weight: 700;
	}

	.cp-input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		color: var(--terminal-fg-primary);
		font-family: inherit;
		font-size: var(--terminal-text-14);
		letter-spacing: 0;
	}

	.cp-input::placeholder {
		color: var(--terminal-fg-tertiary);
	}

	.cp-list {
		list-style: none;
		margin: 0;
		padding: var(--terminal-space-1) 0;
		overflow-y: auto;
		min-height: 0;
	}

	.cp-option {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--terminal-space-4);
		padding: var(--terminal-space-2) var(--terminal-space-4);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-secondary);
		cursor: pointer;
		border-left: 2px solid transparent;
	}

	.cp-option--highlighted {
		background: var(--terminal-bg-panel-raised);
		color: var(--terminal-fg-primary);
		border-left-color: var(--terminal-accent-amber);
	}

	.cp-option--pending {
		color: var(--terminal-fg-muted);
	}

	.cp-option--pending.cp-option--highlighted {
		color: var(--terminal-fg-tertiary);
		border-left-color: var(--terminal-status-warn);
	}

	.cp-option--shake {
		animation: cp-shake 240ms ease-in-out;
	}

	.cp-option-label {
		font-weight: 600;
	}

	.cp-option-right {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-2);
	}

	.cp-option-badge {
		padding: 1px 4px;
		font-size: var(--terminal-text-10);
		letter-spacing: 0.08em;
		color: var(--terminal-fg-tertiary);
		border: 1px solid var(--terminal-fg-muted);
	}

	.cp-option-hint {
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: 0.06em;
	}

	.cp-empty {
		padding: var(--terminal-space-6) var(--terminal-space-4);
		text-align: center;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
		letter-spacing: var(--terminal-tracking-caps);
	}

	.cp-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--terminal-space-2) var(--terminal-space-4);
		border-top: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		letter-spacing: var(--terminal-tracking-caps);
	}

	@keyframes cp-shake {
		0%, 100% { transform: translateX(0); }
		20% { transform: translateX(-4px); }
		40% { transform: translateX(4px); }
		60% { transform: translateX(-3px); }
		80% { transform: translateX(3px); }
	}

	@media (prefers-reduced-motion: reduce) {
		.cp-option--shake {
			animation: none;
		}
	}
</style>
