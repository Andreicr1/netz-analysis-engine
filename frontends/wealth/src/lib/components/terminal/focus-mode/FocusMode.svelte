<!--
	FocusMode.svelte — generic entity focus primitive.
	==================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.3 FocusMode primitive, Appendix B §4, Appendix G file structure.

	Generalization of the Phase 4.2 FundWarRoomModal. Accepts any
	entity kind (fund / portfolio / manager / sector / regime) and
	composes the brutalist 95vw × 95vh cage via snippets:

	  • reactor  — main centerpiece, staggered with the `primary` slot.
	  • rail     — optional 220px metadata strip, `secondary` slot.
	  • actions  — optional top-right action cluster, defaults to
	               a single [ ESC · CLOSE ] pill.

	FocusMode does NOT own the inner cascade of a reactor's modules —
	the consumer's snippet is responsible for its own stagger. This
	primitive animates only four elements: scrim, top bar, reactor
	wrapper, rail wrapper. All four motion sites route through
	svelteTransitionFor from @investintell/ui.

	URL state is NOT owned by this primitive. The caller owns URL
	deep-link contracts (see Part C / TerminalShell).
-->
<script lang="ts">
	import type { Snippet } from "svelte";
	import { fade, fly } from "svelte/transition";
	import { svelteTransitionFor } from "@investintell/ui";

	export type FocusModeEntityKind =
		| "fund"
		| "portfolio"
		| "manager"
		| "sector"
		| "regime";

	interface FocusModeProps {
		entityKind: FocusModeEntityKind;
		entityId: string;
		entityLabel: string;
		reactor: Snippet;
		rail?: Snippet;
		actions?: Snippet;
		onClose: () => void;
	}

	let {
		entityKind,
		entityId,
		entityLabel,
		reactor,
		rail,
		actions,
		onClose,
	}: FocusModeProps = $props();

	let frameEl: HTMLDivElement | undefined = $state();

	const timestamp = buildTimestamp();

	function buildTimestamp(): string {
		// Terminal timestamp — ISO 8601 minute precision, UTC. Not a
		// user-facing value, so it does not route through @investintell/ui
		// formatters (those handle locale/currency/date, not raw ISO).
		const now = new Date();
		const iso = now.toISOString();
		return iso.replace("T", " ").slice(0, 19) + "Z";
	}

	function kindLabel(kind: FocusModeEntityKind): string {
		switch (kind) {
			case "fund":
				return "FUND";
			case "portfolio":
				return "PORTFOLIO";
			case "manager":
				return "MANAGER";
			case "sector":
				return "SECTOR";
			case "regime":
				return "REGIME";
		}
	}

	// Body scroll lock — restore on unmount.
	$effect(() => {
		if (typeof document === "undefined") return;
		const previous = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		return () => {
			document.body.style.overflow = previous;
		};
	});

	// Keyboard handling — ESC closes, remove on unmount.
	$effect(() => {
		if (typeof window === "undefined") return;
		const handler = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.preventDefault();
				onClose();
			}
		};
		window.addEventListener("keydown", handler);
		return () => {
			window.removeEventListener("keydown", handler);
		};
	});

	// Focus lifecycle — move focus inside the frame on mount, restore
	// on unmount. Pairs with the Tab trap $effect below to implement
	// the full WAI-ARIA dialog focus contract (aria-modal="true").
	$effect(() => {
		if (typeof document === "undefined") return;
		const previouslyFocused = document.activeElement as HTMLElement | null;
		// Defer one microtask so the DOM is painted before querying.
		const task = queueMicrotask(() => {
			if (!frameEl) return;
			const target = queryFocusables(frameEl)[0] ?? frameEl;
			target.focus({ preventScroll: true });
		});
		return () => {
			// queueMicrotask returns undefined so `task` is unused; kept
			// for symmetry if the scheduling strategy changes.
			void task;
			if (previouslyFocused && typeof previouslyFocused.focus === "function") {
				previouslyFocused.focus({ preventScroll: true });
			}
		};
	});

	// Tab trap — cycle keyboard focus within the frame on Tab and
	// Shift+Tab, wrapping around at the edges. Satisfies the WAI-ARIA
	// dialog pattern for aria-modal="true": keyboard focus must not
	// escape to the inert background content. Defense-in-depth with
	// the initial-focus $effect above.
	$effect(() => {
		if (typeof window === "undefined") return;
		const handler = (event: KeyboardEvent) => {
			if (event.key !== "Tab" || !frameEl) return;
			const focusables = queryFocusables(frameEl);
			if (focusables.length === 0) {
				// No focusables inside the modal — park focus on the frame
				// itself (tabindex="-1") so focus cannot leak out.
				event.preventDefault();
				frameEl.focus({ preventScroll: true });
				return;
			}
			// Non-null assertions safe: length === 0 case already returned above.
			const first = focusables[0]!;
			const last = focusables[focusables.length - 1]!;
			const active = document.activeElement as HTMLElement | null;
			const outsideFrame = !active || !frameEl.contains(active);
			if (event.shiftKey) {
				if (outsideFrame || active === first) {
					event.preventDefault();
					last.focus({ preventScroll: true });
				}
			} else {
				if (outsideFrame || active === last) {
					event.preventDefault();
					first.focus({ preventScroll: true });
				}
			}
		};
		window.addEventListener("keydown", handler);
		return () => {
			window.removeEventListener("keydown", handler);
		};
	});

	// Shared focusable-descendants query used by both the initial
	// focus and the Tab trap. Filters out elements that are not
	// currently interactable (hidden via display:none, detached
	// subtrees, inert containers, disabled form controls).
	function queryFocusables(root: HTMLElement): HTMLElement[] {
		const selector =
			'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [contenteditable]:not([contenteditable="false"]), [tabindex]:not([tabindex="-1"])';
		const nodes = Array.from(root.querySelectorAll<HTMLElement>(selector));
		return nodes.filter((el) => {
			// offsetParent === null approximates display:none / detached.
			// closest("[inert]") catches the inert-subtree case even when
			// the element itself is rendered.
			if (el.offsetParent === null && el !== root) return false;
			if (el.closest("[inert]")) return false;
			return true;
		});
	}

	function handleBackdrop(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			onClose();
		}
	}

	function handleFrameClick(event: MouseEvent) {
		// Stop the click from bubbling to the backdrop handler.
		event.stopPropagation();
	}

	function handleCloseClick() {
		onClose();
	}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="fm-backdrop"
	role="dialog"
	aria-modal="true"
	aria-label={`${kindLabel(entityKind)} focus mode: ${entityLabel}`}
	tabindex="-1"
	onclick={handleBackdrop}
	transition:fade={svelteTransitionFor("chrome", { duration: "tick" })}
>
	<div
		bind:this={frameEl}
		class="fm-frame"
		class:fm-frame--has-rail={rail !== undefined}
		onclick={handleFrameClick}
	>
		<header
			class="fm-topbar"
			in:fade={svelteTransitionFor("chrome")}
		>
			<div class="fm-topbar-left">
				<span class="fm-brand">[ FOCUS · {kindLabel(entityKind)} ]</span>
				<span class="fm-sep">//</span>
				<span class="fm-entity-label">{entityLabel}</span>
				<span class="fm-sep">//</span>
				<span class="fm-entity-id">{entityId}</span>
				<span class="fm-sep">//</span>
				<span class="fm-status">
					<span class="fm-dot"></span>LIVE
				</span>
			</div>
			<div class="fm-topbar-right">
				<span class="fm-ts">{timestamp}</span>
				{#if actions}
					{@render actions()}
				{:else}
					<button
						type="button"
						class="fm-close"
						onclick={handleCloseClick}
						aria-label="Close focus mode"
					>
						[ ESC · CLOSE ]
					</button>
				{/if}
			</div>
		</header>

		<div class="fm-grid">
			<section
				class="fm-reactor"
				in:fly={{ y: 20, ...svelteTransitionFor("primary") }}
			>
				{@render reactor()}
			</section>

			{#if rail}
				<aside
					class="fm-rail"
					in:fly={{ y: 20, ...svelteTransitionFor("secondary") }}
				>
					{@render rail()}
				</aside>
			{/if}
		</div>
	</div>
</div>

<style>
	.fm-backdrop {
		position: fixed;
		inset: 0;
		z-index: var(--terminal-z-focusmode);
		background: var(--terminal-bg-scrim);
		backdrop-filter: blur(4px);
		-webkit-backdrop-filter: blur(4px);
		display: grid;
		place-items: center;
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
	}

	.fm-frame {
		width: 95vw;
		height: 95vh;
		background: var(--terminal-bg-void);
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		display: grid;
		grid-template-rows: 36px 1fr;
		overflow: hidden;
		outline: none;
	}

	.fm-topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 var(--terminal-space-4);
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		font-size: var(--terminal-text-11);
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
	}

	.fm-topbar-left,
	.fm-topbar-right {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
	}

	.fm-brand {
		color: var(--terminal-fg-primary);
		font-weight: 700;
		letter-spacing: 0.12em;
	}

	.fm-sep {
		color: var(--terminal-fg-muted);
	}

	.fm-entity-label {
		color: var(--terminal-fg-secondary);
		font-weight: 500;
		max-width: 420px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.fm-entity-id {
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.fm-status {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		color: var(--terminal-status-success);
	}

	.fm-dot {
		width: 6px;
		height: 6px;
		background: var(--terminal-status-success);
		display: inline-block;
		box-shadow: 0 0 8px var(--terminal-status-success);
		animation: fm-pulse 1.8s ease-in-out infinite;
	}

	@keyframes fm-pulse {
		0%,
		100% {
			opacity: 0.45;
		}
		50% {
			opacity: 1;
		}
	}

	.fm-ts {
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.fm-close {
		background: transparent;
		border: var(--terminal-border-hairline);
		border-radius: var(--terminal-radius-none);
		color: var(--terminal-fg-primary);
		font-family: inherit;
		font-size: var(--terminal-text-11);
		letter-spacing: 0.06em;
		padding: 4px 10px;
		cursor: pointer;
		text-transform: uppercase;
		transition:
			border-color 80ms ease,
			color 80ms ease,
			background 80ms ease;
	}

	.fm-close:hover {
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}

	.fm-grid {
		display: grid;
		grid-template-columns: 1fr;
		grid-template-rows: 1fr;
		min-height: 0;
		overflow: hidden;
	}

	.fm-frame--has-rail .fm-grid {
		grid-template-columns: 1fr 220px;
	}

	.fm-reactor {
		min-width: 0;
		min-height: 0;
		overflow: auto;
	}

	.fm-frame--has-rail .fm-reactor {
		border-right: var(--terminal-border-hairline);
	}

	.fm-rail {
		display: grid;
		grid-auto-rows: min-content;
		gap: 1px;
		background: var(--terminal-fg-muted);
		overflow: auto;
	}

	@media (max-width: 1100px) {
		.fm-frame--has-rail {
			grid-template-rows: 36px auto 1fr;
		}
		.fm-frame--has-rail .fm-grid {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
		}
		.fm-frame--has-rail .fm-reactor {
			order: 2;
			border-right: none;
			border-top: var(--terminal-border-hairline);
		}
		.fm-frame--has-rail .fm-rail {
			order: 1;
			grid-auto-flow: column;
			grid-auto-columns: minmax(160px, 1fr);
			max-height: 120px;
		}
	}
</style>
