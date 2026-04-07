<!--
  LiveNewsFeed — institutional editorial feed (Tiingo News).

  - Fetches GET /market-data/news on mount and on `tickers` prop change.
  - Auto-refreshes every `refreshIntervalMs` (default 60s).
  - Renders a dense, scrollable list: relative time, ticker badges,
    headline (clickable, opens source in new tab), source name.
  - All interval state cleaned up via $effect return.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { createClientApiClient } from "$lib/api/client";

	interface NewsItem {
		id: string | number | null;
		title: string;
		description: string;
		url: string;
		source: string;
		published_at: string;
		tickers: string[];
	}

	interface Props {
		tickers?: string[];
		limit?: number;
		refreshIntervalMs?: number;
		maxHeight?: number;
	}

	let {
		tickers = [],
		limit = 25,
		refreshIntervalMs = 60_000,
		maxHeight = 520,
	}: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let items = $state<NewsItem[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let lastFetched = $state<Date | null>(null);

	async function loadNews() {
		try {
			loading = true;
			error = null;
			const api = createClientApiClient(getToken);
			const params = new URLSearchParams({ limit: String(limit) });
			if (tickers.length > 0) params.set("tickers", tickers.join(","));
			const resp = await api.get<{ items: NewsItem[] }>(`/market-data/news?${params}`);
			items = resp.items ?? [];
			lastFetched = new Date();
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load news";
		} finally {
			loading = false;
		}
	}

	// Initial load + reload when tickers prop changes.
	$effect(() => {
		// Read tickers + limit so the rune wires the dependency.
		void tickers.join(",");
		void limit;
		loadNews();
	});

	// Polling — separate $effect so it isn't restarted on every prop tick.
	$effect(() => {
		if (refreshIntervalMs <= 0) return;
		const id = setInterval(loadNews, refreshIntervalMs);
		return () => clearInterval(id);
	});

	// ── Relative time formatter ──────────────────────────────────────────
	function relativeTime(iso: string): string {
		if (!iso) return "";
		const then = new Date(iso).getTime();
		if (Number.isNaN(then)) return "";
		const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
		if (diffSec < 60) return `${diffSec}s ago`;
		const diffMin = Math.floor(diffSec / 60);
		if (diffMin < 60) return `${diffMin}m ago`;
		const diffHr = Math.floor(diffMin / 60);
		if (diffHr < 24) return `${diffHr}h ago`;
		const diffDay = Math.floor(diffHr / 24);
		if (diffDay < 7) return `${diffDay}d ago`;
		return new Date(iso).toLocaleDateString();
	}

	function hostFromUrl(url: string): string {
		try {
			return new URL(url).hostname.replace(/^www\./, "");
		} catch {
			return "";
		}
	}

	onMount(() => {
		// no-op — first load handled by $effect
	});
</script>

<section class="news-feed" style:max-height="{maxHeight}px">
	<header class="news-header">
		<div class="news-title">
			<span class="dot" class:dot--live={!loading && !error}></span>
			<h3>Live News</h3>
			{#if tickers.length > 0}
				<span class="news-filter">{tickers.join(" · ")}</span>
			{/if}
		</div>
		<button type="button" class="refresh-btn" onclick={loadNews} disabled={loading}>
			{loading ? "Loading…" : "Refresh"}
		</button>
	</header>

	{#if error}
		<div class="news-error">{error}</div>
	{:else if loading && items.length === 0}
		{#each Array(5) as _}
			<div class="news-skeleton">
				<div class="sk-meta"></div>
				<div class="sk-line"></div>
				<div class="sk-line sk-short"></div>
			</div>
		{/each}
	{:else if items.length === 0}
		<div class="news-empty">No news available.</div>
	{:else}
		<ul class="news-list">
			{#each items as item (item.id ?? item.url)}
				{@const uniqueTickers = Array.from(new Set(item.tickers))}
				<li class="news-item">
					<div class="news-meta">
						<time class="news-time">{relativeTime(item.published_at)}</time>
						{#if uniqueTickers.length > 0}
							<div class="news-tickers">
								{#each uniqueTickers.slice(0, 4) as t (t)}
									<span class="ticker-badge">{t}</span>
								{/each}
								{#if uniqueTickers.length > 4}
									<span class="ticker-badge ticker-more">+{uniqueTickers.length - 4}</span>
								{/if}
							</div>
						{/if}
					</div>
					<a
						class="news-headline"
						href={item.url}
						target="_blank"
						rel="noopener noreferrer"
					>{item.title}</a>
					<div class="news-source">{item.source || hostFromUrl(item.url)}</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.news-feed {
		display: flex;
		flex-direction: column;
		background: var(--ii-surface, #0d0d0d);
		border: 1px solid var(--ii-border, rgba(255, 255, 255, 0.06));
		border-radius: var(--ii-radius-lg, 16px);
		overflow: hidden;
	}

	.news-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--ii-border, rgba(255, 255, 255, 0.06));
		flex-shrink: 0;
	}

	.news-title {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.news-title h3 {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-primary, #ffffff);
	}

	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--ii-text-muted, #85a0bd);
	}

	.dot--live {
		background: var(--ii-success, #11ec79);
		box-shadow: 0 0 8px rgba(17, 236, 121, 0.6);
		animation: pulse 2s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.news-filter {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		font-variant-numeric: tabular-nums;
	}

	.refresh-btn {
		background: transparent;
		border: 1px solid var(--ii-border, rgba(255, 255, 255, 0.1));
		color: var(--ii-text-secondary, #c2c2c2);
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 4px 10px;
		border-radius: var(--ii-radius-sm, 6px);
		cursor: pointer;
		transition: all 150ms ease;
	}

	.refresh-btn:hover:not(:disabled) {
		background: var(--ii-surface-elevated, rgba(255, 255, 255, 0.05));
		color: var(--ii-text-primary, #ffffff);
	}

	.refresh-btn:disabled {
		opacity: 0.5;
		cursor: wait;
	}

	.news-list {
		list-style: none;
		margin: 0;
		padding: 0;
		overflow-y: auto;
		flex: 1;
	}

	.news-item {
		padding: 12px 16px;
		border-bottom: 1px solid var(--ii-border, rgba(255, 255, 255, 0.04));
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.news-item:hover {
		background: var(--ii-surface-elevated, rgba(255, 255, 255, 0.02));
	}

	.news-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}

	.news-time {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		font-variant-numeric: tabular-nums;
	}

	.news-tickers {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}

	.ticker-badge {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.04em;
		padding: 1px 6px;
		border-radius: 4px;
		background: rgba(1, 119, 251, 0.15);
		color: var(--ii-brand-primary, #0177fb);
		border: 1px solid rgba(1, 119, 251, 0.3);
	}

	.ticker-badge.ticker-more {
		background: transparent;
		color: var(--ii-text-muted, #85a0bd);
		border-color: var(--ii-border, rgba(255, 255, 255, 0.1));
	}

	.news-headline {
		font-size: 13px;
		line-height: 1.45;
		color: var(--ii-text-primary, #ffffff);
		text-decoration: none;
		font-weight: 500;
	}

	.news-headline:hover {
		color: var(--ii-brand-primary, #0177fb);
		text-decoration: underline;
	}

	.news-source {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.news-empty,
	.news-error {
		padding: 24px 16px;
		text-align: center;
		font-size: 13px;
		color: var(--ii-text-muted, #85a0bd);
	}

	.news-error {
		color: var(--ii-danger, #fc1a1a);
	}

	.news-skeleton {
		padding: 12px 16px;
		border-bottom: 1px solid var(--ii-border, rgba(255, 255, 255, 0.04));
	}

	.sk-meta,
	.sk-line {
		background: linear-gradient(
			90deg,
			rgba(255, 255, 255, 0.04) 0%,
			rgba(255, 255, 255, 0.08) 50%,
			rgba(255, 255, 255, 0.04) 100%
		);
		border-radius: 4px;
		animation: shimmer 1.4s ease-in-out infinite;
	}

	.sk-meta {
		height: 10px;
		width: 30%;
		margin-bottom: 8px;
	}

	.sk-line {
		height: 12px;
		width: 100%;
		margin-bottom: 6px;
	}

	.sk-line.sk-short {
		width: 60%;
	}

	@keyframes shimmer {
		0%, 100% { opacity: 0.6; }
		50% { opacity: 1; }
	}
</style>
