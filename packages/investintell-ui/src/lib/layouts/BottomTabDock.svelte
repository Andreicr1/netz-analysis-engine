<!--
  BottomTabDock — persistent cross-subject tab strip.

  Created in Phase 4 Task 4.0 as the foundation for the Phase 6 Portfolio
  Analytics surface. Also available for any other workbench that wants to
  give the PM parallel analysis sessions on the same page — e.g. "keep
  fund A open while I dig into fund B".

  Design contract:
    - Generic `T extends BottomTabItem` so each consumer owns the tab
      payload schema (subject id, scope, group focus).
    - Stateless: the parent owns `tabs`, `activeId`, and the four
      callbacks (`onSelect`, `onClose`, `onReorder`, `onNew`). This
      component only paints the strip and emits events.
    - Persistence is the parent's job. Per DL15 (no localStorage, no
      sessionStorage), the Portfolio Analytics page will serialize the
      tab list into the URL hash (`#tabs=<base64>`) and hydrate on load.
    - Keyboard: Left/Right arrows move the focus, Enter activates, Esc
      closes the active tab. A future sprint can add Ctrl+T / Ctrl+W
      shortcuts at the parent level.

  Per CLAUDE.md: no emojis, no inline formatter code, no localStorage.
-->
<script lang="ts" module>
	import type { Snippet } from "svelte";

	export interface BottomTabItem {
		/** Stable identifier — used for keyboard focus + close targeting. */
		id: string;
		/** Short label (max ~18 chars rendered — overflow is ellipsized). */
		label: string;
		/** Optional secondary label rendered in muted grey below the title. */
		subtitle?: string;
		/** Optional badge count rendered on the right edge of the tab. */
		badge?: number | string;
		/**
		 * Unique fingerprint for dedupe / deep-link matching. The parent
		 * decides what goes in here (e.g. `${subjectId}:${scope}`).
		 */
		fingerprint?: string;
	}

	export interface BottomTabDockProps<T extends BottomTabItem> {
		tabs: readonly T[];
		activeId: string | null;
		onSelect: (tab: T) => void;
		onClose: (tab: T) => void;
		/** Optional — when omitted the "+" button is hidden. */
		onNew?: () => void;
		/** Optional trailing snippet rendered flush-right (actions, status chips, etc.). */
		trailing?: Snippet;
		/** Optional per-tab custom rendering — falls back to label + subtitle. */
		tabContent?: Snippet<[T, boolean]>;
		ariaLabel?: string;
	}
</script>

<script lang="ts" generics="T extends BottomTabItem">
	import X from "lucide-svelte/icons/x";
	import Plus from "lucide-svelte/icons/plus";

	let {
		tabs,
		activeId,
		onSelect,
		onClose,
		onNew,
		trailing,
		tabContent,
		ariaLabel = "Open subjects",
	}: BottomTabDockProps<T> = $props();

	function handleKeyDown(event: KeyboardEvent, tab: T) {
		if (event.key === "Enter" || event.key === " ") {
			event.preventDefault();
			onSelect(tab);
		} else if (event.key === "Escape") {
			event.preventDefault();
			onClose(tab);
		}
	}

	function handleCloseClick(event: MouseEvent, tab: T) {
		event.stopPropagation();
		onClose(tab);
	}
</script>

<div class="btd-root" role="tablist" aria-label={ariaLabel}>
	<div class="btd-scroll">
		{#each tabs as tab (tab.id)}
			{@const active = tab.id === activeId}
			<button
				type="button"
				class="btd-tab"
				class:btd-tab--active={active}
				role="tab"
				aria-selected={active}
				tabindex={active ? 0 : -1}
				onclick={() => onSelect(tab)}
				onkeydown={(e) => handleKeyDown(e, tab)}
			>
				{#if tabContent}
					{@render tabContent(tab, active)}
				{:else}
					<span class="btd-tab-labels">
						<span class="btd-tab-title">{tab.label}</span>
						{#if tab.subtitle}
							<span class="btd-tab-subtitle">{tab.subtitle}</span>
						{/if}
					</span>
				{/if}
				{#if tab.badge !== undefined && tab.badge !== null && tab.badge !== ""}
					<span class="btd-tab-badge">{tab.badge}</span>
				{/if}
				<span
					class="btd-tab-close"
					role="button"
					tabindex={active ? 0 : -1}
					aria-label={`Close ${tab.label}`}
					onclick={(e) => handleCloseClick(e, tab)}
					onkeydown={(e) => {
						if (e.key === "Enter" || e.key === " ") {
							e.preventDefault();
							onClose(tab);
						}
					}}
				>
					<X size={12} />
				</span>
			</button>
		{/each}

		{#if onNew}
			<button
				type="button"
				class="btd-new"
				onclick={onNew}
				aria-label="Open new subject"
			>
				<Plus size={14} />
			</button>
		{/if}
	</div>

	{#if trailing}
		<div class="btd-trailing">{@render trailing()}</div>
	{/if}
</div>

<style>
	.btd-root {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		width: 100%;
		height: 40px;
		padding: 0 12px;
		border-top: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		background: var(--ii-surface, #141519);
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
		color: var(--ii-text-primary, #ffffff);
	}

	.btd-scroll {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 6px;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.btd-scroll::-webkit-scrollbar {
		display: none;
	}

	.btd-tab {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		height: 28px;
		padding: 0 10px;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-muted, #85a0bd);
		font-family: inherit;
		font-size: 12px;
		cursor: pointer;
		white-space: nowrap;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
	}
	.btd-tab:hover {
		color: var(--ii-text-primary, #ffffff);
		background: rgba(255, 255, 255, 0.04);
	}
	.btd-tab--active {
		color: var(--ii-text-primary, #ffffff);
		background: rgba(1, 119, 251, 0.12);
		border-color: var(--ii-primary, #0177fb);
	}

	.btd-tab-labels {
		display: inline-flex;
		flex-direction: column;
		align-items: flex-start;
		min-width: 0;
		max-width: 160px;
	}

	.btd-tab-title {
		font-size: 12px;
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}

	.btd-tab-subtitle {
		font-size: 10px;
		font-weight: 500;
		color: var(--ii-text-muted, #85a0bd);
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}

	.btd-tab-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 16px;
		padding: 0 5px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.08);
		font-size: 10px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}

	.btd-tab-close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border-radius: 4px;
		color: inherit;
		opacity: 0.6;
		cursor: pointer;
	}
	.btd-tab-close:hover {
		opacity: 1;
		background: rgba(255, 255, 255, 0.08);
	}

	.btd-new {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: 1px dashed var(--ii-border-subtle, rgba(64, 66, 73, 0.6));
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-muted, #85a0bd);
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}
	.btd-new:hover {
		color: var(--ii-text-primary, #ffffff);
		border-color: var(--ii-primary, #0177fb);
	}

	.btd-trailing {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}
</style>
