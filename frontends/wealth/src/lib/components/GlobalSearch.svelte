<!--
  GlobalSearch — Cmd+K command palette with grouped results.
  Built on shadcn Command + Dialog primitives (bits-ui).
  Debounced search against GET /search?q=&categories=
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { Search, FileText, Building2, Landmark } from "lucide-svelte";
	import * as Command from "@investintell/ui/components/ui/command";
	import { createClientApiClient } from "$wealth/api/client";
	import { createDebouncedState } from "$wealth/utils/reactivity";

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
	const search = createDebouncedState("", 300);
	let loading = $state(false);
	let groups = $state<SearchCategoryGroup[]>([]);
	let abortController: AbortController | null = null;

	// Reset state when dialog opens
	$effect(() => {
		if (open) {
			search.current = "";
			search.flush();
			groups = [];
			loading = false;
		}
	});

	// React to debounced search value
	$effect(() => {
		const q = search.debounced;
		if (q.length < 2) {
			groups = [];
			loading = false;
			return;
		}
		doSearch(q);
	});

	function handleGlobalKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === "k") {
			e.preventDefault();
			open = !open;
			return;
		}
		if (
			e.key === "/" &&
			!open &&
			!(e.target instanceof HTMLInputElement) &&
			!(e.target instanceof HTMLTextAreaElement)
		) {
			e.preventDefault();
			open = true;
		}
	}

	function handleOpenChange(isOpen: boolean) {
		open = isOpen;
		if (!isOpen) {
			abortController?.abort();
		}
	}

	function navigateTo(item: SearchResultItem) {
		open = false;
		goto(item.href);
	}

	async function doSearch(q: string) {
		abortController?.abort();
		abortController = new AbortController();
		loading = true;
		try {
			const res = await api.get<GlobalSearchResponse>("/search/global", { q });
			groups = res.groups;
		} catch (err) {
			if (err instanceof DOMException && err.name === "AbortError") return;
			groups = [];
		} finally {
			loading = false;
		}
	}

	const CATEGORY_ICONS: Record<string, typeof Search> = {
		funds: Landmark,
		managers: Building2,
		documents: FileText,
	};

	function getCategoryIcon(cat: string) {
		return CATEGORY_ICONS[cat] || Search;
	}
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

<Command.Dialog
	bind:open
	onOpenChange={handleOpenChange}
	title="Global Search"
	description="Search funds, managers, documents"
	shouldFilter={false}
	class="ii-global-search !max-w-[640px] !bg-[var(--ii-surface-panel)] !border !border-white/10 !rounded-2xl !p-0 !shadow-[0_30px_80px_-20px_rgba(0,0,0,0.7)] !ring-1 !ring-white/5"
>
	<div class="ii-search-header">
		<Search size={16} class="text-[var(--ii-text-muted)] shrink-0" />
		<Command.Input
			placeholder="Search funds, managers, documents…"
			value={search.current}
			oninput={(e: Event) => { search.current = (e.target as HTMLInputElement).value; }}
			class="ii-search-input"
		/>
		<kbd class="ii-search-kbd">Esc</kbd>
	</div>
	<Command.List class="ii-search-list max-h-[420px]">
		{#if loading}
			<Command.Loading>
				<div class="ii-search-loading">
					<span class="ii-search-spinner"></span>
					Searching…
				</div>
			</Command.Loading>
		{/if}

		{#if search.current.length < 2}
			<div class="ii-search-hint">
				<div class="ii-search-hint-title">Start typing to search InvestIntell</div>
				<div class="ii-search-hint-sub">Funds · Managers · Documents</div>
				<div class="ii-search-hint-keys">
					<span><kbd class="ii-search-kbd">Esc</kbd> close</span>
					<span><kbd class="ii-search-kbd">&uarr;&darr;</kbd> navigate</span>
					<span><kbd class="ii-search-kbd">Enter</kbd> open</span>
				</div>
			</div>
		{:else if !loading && groups.length === 0 && search.current.length >= 2}
			<Command.Empty>
				<div class="ii-search-empty">No results for "{search.current}"</div>
			</Command.Empty>
		{:else}
			{#each groups as group (group.category)}
				{@const Icon = getCategoryIcon(group.category)}
				<Command.Group heading={group.label} value={group.category}>
					{#each group.items as item (item.id)}
						<Command.Item
							value="{item.category}:{item.id}:{item.title}"
							onSelect={() => navigateTo(item)}
						>
							<Icon class="size-4 shrink-0 text-[var(--ii-text-muted)]" />
							<span class="max-w-[55%] truncate font-medium text-white">{item.title}</span>
							{#if item.subtitle}
								<span class="flex-1 truncate text-xs text-[var(--ii-text-muted)]">{item.subtitle}</span>
							{/if}
						</Command.Item>
					{/each}
				</Command.Group>
			{/each}
		{/if}
	</Command.List>
</Command.Dialog>

<style>
	/* Force the dialog overlay behind the palette to match the AI
	 * drawer scrim — the shadcn default bg-black/10 was leaving the
	 * dashboard fully legible, which read as "no backdrop, card is
	 * transparent". */
	:global([data-dialog-overlay]),
	:global([data-sheet-overlay]) {
		background: rgba(5, 8, 15, 0.68) !important;
		backdrop-filter: blur(6px);
	}

	/* Scoped to this dialog instance via .ii-global-search so we don't
	 * bleed into shadcn command/dialog usage elsewhere. */
	:global(.ii-global-search) {
		overflow: hidden;
	}

	:global(.ii-global-search [cmdk-root]) {
		background: transparent !important;
		color: var(--ii-text-primary);
	}

	.ii-search-header {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 16px 18px;
		border-bottom: 1px solid var(--ii-border-subtle);
		background:
			linear-gradient(180deg, rgba(1, 119, 251, 0.06) 0%, transparent 100%),
			var(--ii-surface-panel);
	}

	:global(.ii-search-input) {
		flex: 1 !important;
		height: 28px !important;
		background: transparent !important;
		border: none !important;
		outline: none !important;
		color: var(--ii-text-primary) !important;
		font-size: 15px !important;
		font-family: var(--ii-font-sans) !important;
	}

	:global(.ii-search-input::placeholder) {
		color: var(--ii-text-muted) !important;
	}

	:global(.ii-search-list) {
		padding: 8px !important;
		overflow-y: auto;
		background: var(--ii-surface-panel);
	}

	:global(.ii-search-list::-webkit-scrollbar) {
		width: 8px;
	}
	:global(.ii-search-list::-webkit-scrollbar-thumb) {
		background: var(--ii-border-subtle);
		border-radius: 4px;
	}

	:global(.ii-search-list [cmdk-group-heading]) {
		padding: 10px 12px 6px !important;
		font-size: 10px !important;
		font-weight: 600 !important;
		text-transform: uppercase !important;
		letter-spacing: 0.09em !important;
		color: var(--ii-text-muted) !important;
	}

	:global(.ii-search-list [cmdk-item]) {
		display: flex !important;
		align-items: center !important;
		gap: 10px !important;
		padding: 10px 12px !important;
		border-radius: 10px !important;
		color: var(--ii-text-primary) !important;
		font-size: 13px !important;
		cursor: pointer !important;
		transition: background 120ms ease !important;
		margin-bottom: 2px;
	}

	:global(.ii-search-list [cmdk-item][data-selected="true"]),
	:global(.ii-search-list [cmdk-item]:hover) {
		background: rgba(1, 119, 251, 0.14) !important;
		box-shadow: inset 0 0 0 1px rgba(1, 119, 251, 0.35);
	}

	.ii-search-hint {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		padding: 42px 24px;
		text-align: center;
	}

	.ii-search-hint-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.ii-search-hint-sub {
		font-size: 12px;
		color: var(--ii-text-muted);
		margin-bottom: 18px;
	}

	.ii-search-hint-keys {
		display: flex;
		gap: 14px;
		font-size: 11px;
		color: var(--ii-text-muted);
		align-items: center;
	}

	.ii-search-hint-keys span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}

	.ii-search-kbd {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 22px;
		padding: 2px 6px;
		border-radius: 5px;
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		color: var(--ii-text-muted);
		font-size: 10px;
		font-family: var(--ii-font-mono);
		line-height: 1;
	}

	.ii-search-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 30px;
		font-size: 13px;
		color: var(--ii-text-muted);
	}

	.ii-search-spinner {
		width: 14px;
		height: 14px;
		border: 2px solid rgba(1, 119, 251, 0.2);
		border-top-color: #0177fb;
		border-radius: 50%;
		animation: ii-search-spin 0.8s linear infinite;
	}

	@keyframes ii-search-spin {
		to { transform: rotate(360deg); }
	}

	.ii-search-empty {
		padding: 32px 16px;
		text-align: center;
		font-size: 13px;
		color: var(--ii-text-muted);
	}
</style>
