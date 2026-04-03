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
	let searchQuery = $state("");
	let loading = $state(false);
	let groups = $state<SearchCategoryGroup[]>([]);
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	let abortController: AbortController | null = null;

	// Reset state when dialog opens
	$effect(() => {
		if (open) {
			searchQuery = "";
			groups = [];
			loading = false;
		}
	});

	// Debounced search on query change
	$effect(() => {
		const q = searchQuery;
		clearTimeout(debounceTimer);
		if (q.length < 2) {
			groups = [];
			loading = false;
			return;
		}
		debounceTimer = setTimeout(() => doSearch(q), 300);
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
			const res = await api.get<GlobalSearchResponse>("/search", { q });
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
	class="max-w-[560px]"
>
	<Command.Input
		placeholder="Search funds, managers, documents…"
		bind:value={searchQuery}
	/>
	<Command.List class="max-h-[380px]">
		{#if loading}
			<Command.Loading>
				<div class="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
					Searching…
				</div>
			</Command.Loading>
		{/if}

		{#if searchQuery.length < 2}
			<div class="flex flex-col items-center gap-2 py-8 text-muted-foreground">
				<span class="text-sm">Type at least 2 characters to search</span>
				<div class="flex gap-3 text-xs">
					<span><kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">Esc</kbd> close</span>
					<span><kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">&uarr;&darr;</kbd> navigate</span>
					<span><kbd class="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">Enter</kbd> open</span>
				</div>
			</div>
		{:else if !loading && groups.length === 0 && searchQuery.length >= 2}
			<Command.Empty>No results for "{searchQuery}"</Command.Empty>
		{:else}
			{#each groups as group (group.category)}
				{@const Icon = getCategoryIcon(group.category)}
				<Command.Group heading={group.label} value={group.category}>
					{#each group.items as item (item.id)}
						<Command.Item
							value="{item.category}:{item.id}:{item.title}"
							onSelect={() => navigateTo(item)}
						>
							<Icon class="size-3.5 shrink-0 text-muted-foreground" />
							<span class="max-w-[55%] truncate font-medium">{item.title}</span>
							{#if item.subtitle}
								<span class="flex-1 truncate text-xs text-muted-foreground">{item.subtitle}</span>
							{/if}
						</Command.Item>
					{/each}
				</Command.Group>
			{/each}
		{/if}
	</Command.List>
</Command.Dialog>
