<!--
  NewsFeed -- right-column panel showing Tiingo editorial headlines.

  Fetches from GET /market-data/news?tickers={csv}&limit=20.
  Shows tag-colored pills (MACRO, FUND, MARKET, ALERT),
  publication time, and 2-line headline.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatTime } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";

	interface Props {
		tickers: string[];
	}

	let { tickers }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface NewsItem {
		id: number | string | null;
		title: string;
		description: string;
		url: string;
		source: string;
		published_at: string;
		tickers: string[];
		tags: string[];
	}

	let items = $state<NewsItem[]>([]);
	let loading = $state(true);
	let error = $state(false);

	function classifyTag(item: NewsItem): string {
		const tags = item.tags.map((t) => t.toLowerCase());
		const title = item.title.toLowerCase();
		if (tags.includes("alert") || title.includes("alert") || title.includes("warning")) return "ALERT";
		if (tags.includes("macro") || title.includes("fed") || title.includes("inflation") || title.includes("gdp") || title.includes("cpi")) return "MACRO";
		if (tags.includes("fund") || title.includes("etf") || title.includes("fund")) return "FUND";
		return "MARKET";
	}

	function displayTime(iso: string): string {
		return formatTime(iso);
	}

	$effect(() => {
		const t = tickers;
		let cancelled = false;
		loading = true;
		error = false;

		const params = new URLSearchParams({ limit: "20" });
		if (t.length > 0) {
			params.set("tickers", t.join(","));
		}

		api.get<{ items: NewsItem[]; count: number }>(`/market-data/news?${params.toString()}`)
			.then((res) => {
				if (!cancelled) {
					items = res.items;
					loading = false;
				}
			})
			.catch(() => {
				if (!cancelled) {
					items = [];
					loading = false;
					error = true;
				}
			});

		return () => { cancelled = true; };
	});
</script>

<div class="nf-root">
	<div class="nf-header">
		<span class="nf-label">NEWS FEED</span>
		<span class="nf-count">{items.length}</span>
	</div>

	<div class="nf-body">
		{#if loading}
			<div class="nf-empty">Loading...</div>
		{:else if error}
			<div class="nf-empty">News feed -- coming soon</div>
		{:else if items.length === 0}
			<div class="nf-empty">No recent headlines</div>
		{:else}
			{#each items as item (item.id ?? item.title)}
				{@const tag = classifyTag(item)}
				<a
					class="nf-item"
					href={item.url}
					target="_blank"
					rel="noopener noreferrer"
				>
					<div class="nf-meta">
						<span class="nf-time">{displayTime(item.published_at)}</span>
						<span class="nf-tag nf-tag--{tag.toLowerCase()}">{tag}</span>
					</div>
					<span class="nf-headline">{item.title}</span>
				</a>
			{/each}
		{/if}
	</div>
</div>

<style>
	.nf-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.nf-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
		height: 28px;
		padding: 0 var(--terminal-space-2);
		border-bottom: var(--terminal-border-hairline);
	}

	.nf-label {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
	}

	.nf-count {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		color: var(--terminal-fg-tertiary);
	}

	.nf-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}

	.nf-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 80px;
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
	}

	.nf-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--terminal-space-1) var(--terminal-space-2);
		border-bottom: 1px solid var(--terminal-fg-muted);
		cursor: pointer;
		text-decoration: none;
		transition: background var(--terminal-motion-tick);
	}

	.nf-item:hover {
		background: var(--terminal-bg-panel-raised);
	}

	.nf-meta {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.nf-time {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.nf-tag {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		padding: 1px 4px;
	}

	.nf-tag--macro {
		color: var(--terminal-accent-cyan);
	}

	.nf-tag--fund {
		color: var(--terminal-status-success);
	}

	.nf-tag--market {
		color: var(--terminal-accent-amber);
	}

	.nf-tag--alert {
		color: var(--terminal-status-error);
	}

	.nf-headline {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-secondary);
		line-height: var(--terminal-leading-snug);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
</style>
