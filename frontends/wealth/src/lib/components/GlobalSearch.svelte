<!--
  GlobalSearch — Cmd+K command palette with grouped results.
  Debounced search against GET /search?q=&categories=
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { Search, X, FileText, Building2, Landmark, Loader2 } from "lucide-svelte";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface SearchResultItem {
		id: string;
		title: string;
		subtitle: string | null;
		category: string;
		href: string;
	}

	interface SearchCategoryGroup {
		category: string;
		label: string;
		items: SearchResultItem[];
		total: number;
	}

	interface GlobalSearchResponse {
		query: string;
		groups: SearchCategoryGroup[];
	}

	let { open = $bindable(false) }: { open?: boolean } = $props();
	let query = $state("");
	let loading = $state(false);
	let groups = $state<SearchCategoryGroup[]>([]);
	let selectedIndex = $state(0);
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	let inputEl: HTMLInputElement | undefined;
	let abortController: AbortController | null = null;

	// Flatten all items for keyboard navigation
	const allItems = $derived(groups.flatMap((g) => g.items));

	// React to open being set externally (e.g. topbar click)
	$effect(() => {
		if (open) {
			query = "";
			groups = [];
			selectedIndex = 0;
			loading = false;
			requestAnimationFrame(() => inputEl?.focus());
		}
	});

	function openPalette() {
		open = true;
	}

	function closePalette() {
		open = false;
		query = "";
		groups = [];
		abortController?.abort();
	}

	function handleGlobalKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === "k") {
			e.preventDefault();
			if (open) closePalette();
			else openPalette();
			return;
		}
		// "/" shortcut when not focused in an input
		if (
			e.key === "/" &&
			!open &&
			!(e.target instanceof HTMLInputElement) &&
			!(e.target instanceof HTMLTextAreaElement)
		) {
			e.preventDefault();
			openPalette();
		}
	}

	function handleInputKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			closePalette();
			return;
		}
		if (e.key === "ArrowDown") {
			e.preventDefault();
			selectedIndex = Math.min(selectedIndex + 1, allItems.length - 1);
			return;
		}
		if (e.key === "ArrowUp") {
			e.preventDefault();
			selectedIndex = Math.max(selectedIndex - 1, 0);
			return;
		}
		if (e.key === "Enter" && allItems.length > 0) {
			e.preventDefault();
			const selected = allItems[selectedIndex];
			if (selected) navigateTo(selected);
		}
	}

	function navigateTo(item: SearchResultItem) {
		closePalette();
		goto(item.href);
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) closePalette();
	}

	async function doSearch(q: string) {
		if (q.length < 2) {
			groups = [];
			loading = false;
			return;
		}

		abortController?.abort();
		abortController = new AbortController();

		loading = true;
		try {
			const res = await api.get<GlobalSearchResponse>("/search", { q });
			groups = res.groups;
			selectedIndex = 0;
		} catch (err) {
			if (err instanceof DOMException && err.name === "AbortError") return;
			groups = [];
		} finally {
			loading = false;
		}
	}

	function onInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => doSearch(query), 300);
	}

	const CATEGORY_ICONS: Record<string, typeof Search> = {
		funds: Landmark,
		managers: Building2,
		documents: FileText,
	};

	function getCategoryIcon(cat: string) {
		return CATEGORY_ICONS[cat] || Search;
	}

	// Compute flat index for a given group item
	function flatIndex(grps: SearchCategoryGroup[], groupIdx: number, itemIdx: number): number {
		let idx = 0;
		for (let g = 0; g < groupIdx; g++) idx += grps[g]?.items.length ?? 0;
		return idx + itemIdx;
	}
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="gs-backdrop" onclick={handleBackdropClick}>
		<div class="gs-dialog" role="dialog" aria-label="Global search">
			<!-- Search input -->
			<div class="gs-input-row">
				<Search size={16} strokeWidth={1.5} class="gs-input-icon" />
				<input
					bind:this={inputEl}
					bind:value={query}
					oninput={onInput}
					onkeydown={handleInputKeydown}
					class="gs-input"
					type="text"
					placeholder="Search funds, managers, documents…"
					spellcheck="false"
					autocomplete="off"
				/>
				{#if loading}
					<Loader2 size={16} strokeWidth={2} class="gs-spinner" />
				{/if}
				<button class="gs-close-btn" onclick={closePalette} type="button" aria-label="Close">
					<X size={14} strokeWidth={2} />
				</button>
			</div>

			<!-- Results -->
			<div class="gs-results">
				{#if query.length < 2}
					<div class="gs-empty">
						<span class="gs-empty-text">Type at least 2 characters to search</span>
						<div class="gs-shortcuts">
							<kbd>Esc</kbd> to close
							<kbd>&uarr;&darr;</kbd> navigate
							<kbd>Enter</kbd> open
						</div>
					</div>
				{:else if loading && groups.length === 0}
					<div class="gs-empty">
						<Loader2 size={20} strokeWidth={2} class="gs-spinner" />
						<span class="gs-empty-text">Searching…</span>
					</div>
				{:else if !loading && groups.length === 0 && query.length >= 2}
					<div class="gs-empty">
						<span class="gs-empty-text">No results for "{query}"</span>
					</div>
				{:else}
					{#each groups as group, gi (group.category)}
						{@const Icon = getCategoryIcon(group.category)}
						<div class="gs-group">
							<div class="gs-group-header">
								<Icon size={13} strokeWidth={1.5} />
								<span>{group.label}</span>
								{#if group.total > group.items.length}
									<span class="gs-group-count">{group.total} total</span>
								{/if}
							</div>
							{#each group.items as item, ii (item.id)}
								{@const fi = flatIndex(groups, gi, ii)}
								<!-- svelte-ignore a11y_click_events_have_key_events -->
								<button
									class="gs-item"
									class:selected={fi === selectedIndex}
									onclick={() => navigateTo(item)}
									onmouseenter={() => (selectedIndex = fi)}
									type="button"
								>
									<span class="gs-item-title">{item.title}</span>
									{#if item.subtitle}
										<span class="gs-item-subtitle">{item.subtitle}</span>
									{/if}
								</button>
							{/each}
						</div>
					{/each}
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.gs-backdrop {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: rgba(0, 0, 0, 0.4);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 12vh;
		backdrop-filter: blur(2px);
	}

	.gs-dialog {
		width: 100%;
		max-width: 560px;
		background: var(--netz-surface-elevated, #fff);
		border: 1px solid var(--netz-border, #e2e8f0);
		border-radius: var(--netz-radius-lg, 12px);
		box-shadow:
			0 20px 60px rgba(0, 0, 0, 0.15),
			0 4px 16px rgba(0, 0, 0, 0.1);
		overflow: hidden;
	}

	/* ── Input row ── */
	.gs-input-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 12px 16px;
		border-bottom: 1px solid var(--netz-border-subtle, #edf2f7);
	}

	.gs-input-row :global(.gs-input-icon) {
		color: var(--netz-text-muted);
		flex-shrink: 0;
	}

	.gs-input {
		flex: 1;
		border: none;
		background: transparent;
		font-size: 0.9375rem;
		font-family: var(--netz-font-sans);
		color: var(--netz-text-primary);
		outline: none;
	}

	.gs-input::placeholder {
		color: var(--netz-text-muted);
	}

	.gs-input-row :global(.gs-spinner) {
		color: var(--netz-brand-primary, #3b82f6);
		animation: spin 0.8s linear infinite;
		flex-shrink: 0;
	}

	.gs-close-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: 1px solid var(--netz-border, #e2e8f0);
		border-radius: var(--netz-radius-xs, 4px);
		background: var(--netz-surface-alt, #f7fafc);
		color: var(--netz-text-muted);
		cursor: pointer;
		flex-shrink: 0;
	}

	.gs-close-btn:hover {
		color: var(--netz-text-primary);
	}

	/* ── Results area ─��� */
	.gs-results {
		max-height: 380px;
		overflow-y: auto;
		scrollbar-width: thin;
	}

	/* ── Empty / loading states ── */
	.gs-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 32px 16px;
		color: var(--netz-text-muted);
	}

	.gs-empty :global(.gs-spinner) {
		color: var(--netz-text-muted);
		animation: spin 0.8s linear infinite;
	}

	.gs-empty-text {
		font-size: 0.8125rem;
	}

	.gs-shortcuts {
		display: flex;
		gap: 12px;
		font-size: 0.6875rem;
		color: var(--netz-text-muted);
	}

	.gs-shortcuts kbd {
		display: inline-flex;
		align-items: center;
		padding: 1px 4px;
		border: 1px solid var(--netz-border);
		border-radius: 3px;
		background: var(--netz-surface-alt);
		font-family: var(--netz-font-mono);
		font-size: 0.625rem;
	}

	/* ── Groups ── */
	.gs-group {
		padding: 4px 0;
	}

	.gs-group-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 16px;
		font-size: 0.6875rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--netz-text-muted);
	}

	.gs-group-count {
		margin-left: auto;
		font-weight: 500;
		font-size: 0.625rem;
		color: var(--netz-text-muted);
		opacity: 0.7;
	}

	/* ── Items ── */
	.gs-item {
		display: flex;
		align-items: baseline;
		gap: 8px;
		width: 100%;
		padding: 8px 16px 8px 36px;
		border: none;
		background: transparent;
		cursor: pointer;
		text-align: left;
		font-family: var(--netz-font-sans);
		transition: background 60ms ease;
	}

	.gs-item:hover,
	.gs-item.selected {
		background: var(--netz-surface-alt, #f7fafc);
	}

	.gs-item-title {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--netz-text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 55%;
	}

	.gs-item-subtitle {
		font-size: 0.75rem;
		color: var(--netz-text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
