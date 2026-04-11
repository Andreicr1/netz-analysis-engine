<!--
  TerminalNewsFeed — left sidebar news/activity feed.

  grid-area: news. Spans two rows (middle + bottom left).
  Mock data for now — will be wired to Tiingo News API later.
  11px body, subtle separators, internal scroll.
-->
<script lang="ts">
	interface NewsItem {
		id: string;
		time: string;
		headline: string;
		source: string;
		tag: "macro" | "fund" | "market" | "alert";
	}

	// Mock news feed
	const MOCK_NEWS: NewsItem[] = [
		{ id: "1", time: "15:42", headline: "Fed holds rates steady, signals data-dependent path forward", source: "Reuters", tag: "macro" },
		{ id: "2", time: "15:30", headline: "Treasury 10Y yield drops 4bps to 4.28% on softer CPI print", source: "Bloomberg", tag: "macro" },
		{ id: "3", time: "14:55", headline: "Vanguard Total Bond Market ETF sees $2.1B inflows in April", source: "Morningstar", tag: "fund" },
		{ id: "4", time: "14:20", headline: "Gold futures rally to $2,380/oz amid dollar weakness", source: "CNBC", tag: "market" },
		{ id: "5", time: "13:45", headline: "European equities close higher; Stoxx 600 +0.8%", source: "FT", tag: "market" },
		{ id: "6", time: "13:10", headline: "PIMCO Income Fund reduces duration to 3.2Y from 4.1Y", source: "SEC Filing", tag: "fund" },
		{ id: "7", time: "12:30", headline: "BIS warns of credit gap widening in emerging markets", source: "BIS Bulletin", tag: "macro" },
		{ id: "8", time: "11:55", headline: "Fidelity cuts expense ratio on 3 bond index funds", source: "Fidelity", tag: "fund" },
		{ id: "9", time: "11:20", headline: "Oil drops 2% as OPEC+ signals production increase in Q3", source: "Reuters", tag: "market" },
		{ id: "10", time: "10:45", headline: "JPM raises 2025 US GDP forecast to 2.4% from 2.1%", source: "JPMorgan", tag: "macro" },
		{ id: "11", time: "10:10", headline: "Portfolio drift alert: Conservative Income exceeds 3pp threshold", source: "System", tag: "alert" },
		{ id: "12", time: "09:30", headline: "US initial jobless claims 215K vs 220K expected", source: "DoL", tag: "macro" },
	];

	const TAG_COLORS: Record<string, string> = {
		macro: "#2d7ef7",
		fund: "#22c55e",
		market: "#f59e0b",
		alert: "#ef4444",
	};
</script>

<div class="nf-root">
	<div class="nf-header">
		<span class="nf-title">NEWS FEED</span>
	</div>
	<div class="nf-list">
		{#each MOCK_NEWS as item}
			<div class="nf-item">
				<div class="nf-item-top">
					<span class="nf-time">{item.time}</span>
					<span class="nf-tag" style="color: {TAG_COLORS[item.tag] ?? '#5a6577'}">{item.tag.toUpperCase()}</span>
				</div>
				<p class="nf-headline">{item.headline}</p>
				<span class="nf-source">{item.source}</span>
			</div>
		{/each}
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
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.nf-header {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		height: 30px;
		padding: 0 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.06);
	}
	.nf-title {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: #5a6577;
	}

	.nf-list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 0;
	}

	.nf-item {
		padding: 8px 10px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.04);
		cursor: default;
		transition: background 60ms;
	}
	.nf-item:hover {
		background: rgba(255, 255, 255, 0.02);
	}

	.nf-item-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 3px;
	}
	.nf-time {
		font-family: "JetBrains Mono", "SF Mono", monospace;
		font-size: 9px;
		font-weight: 600;
		color: #3d4654;
		font-variant-numeric: tabular-nums;
	}
	.nf-tag {
		font-size: 8px;
		font-weight: 800;
		letter-spacing: 0.08em;
	}

	.nf-headline {
		margin: 0;
		font-size: 11px;
		font-weight: 500;
		line-height: 1.35;
		color: #c8d0dc;
	}

	.nf-source {
		font-size: 9px;
		font-weight: 500;
		color: #3d4654;
		margin-top: 2px;
		display: block;
	}
</style>
