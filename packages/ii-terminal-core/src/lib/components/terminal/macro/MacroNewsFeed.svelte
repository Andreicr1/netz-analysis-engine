<script lang="ts">
	interface Props {
		active?: boolean;
	}

	let { active = false }: Props = $props();

	const news = [
		{
			src: "BLOOMBERG",
			time: "14:22",
			tag: "FED",
			title: "Fed officials split on timing of next cut as services inflation stays sticky",
			tickers: ["US10Y", "US02Y"],
		},
		{
			src: "REUTERS",
			time: "13:58",
			tag: "DATA",
			title: "US CPI 3.4% YoY vs 3.2% consensus - shelter prints hotter",
			tickers: ["TLT", "US10Y", "DXY"],
		},
		{
			src: "FT",
			time: "13:41",
			tag: "ECB",
			title: "Lagarde: June cut conditional on wage data",
			tickers: ["EURUSD", "DE10Y"],
		},
		{
			src: "VALOR",
			time: "13:20",
			tag: "BCB",
			title: "COPOM mantem Selic 10,50% e sinaliza pausa prolongada",
			tickers: ["BR10Y", "USDBRL"],
		},
		{
			src: "BLOOMBERG",
			time: "12:44",
			tag: "BOJ",
			title: "BoJ minutes hint at gradual tightening - JGB yields test 1.2%",
			tickers: ["JP10Y", "USDJPY"],
		},
		{
			src: "WSJ",
			time: "12:18",
			tag: "GEO",
			title: "Middle East tensions lift Brent; gold extends record pace",
			tickers: ["CO", "XAU"],
		},
		{
			src: "REUTERS",
			time: "11:52",
			tag: "CN",
			title: "China PMI back in expansion - copper catches bid",
			tickers: ["HG", "HSI", "USDCNY"],
		},
		{
			src: "BLOOMBERG",
			time: "11:30",
			tag: "CREDIT",
			title: "IG spreads tighten to 18-month lows as IG supply absorbed",
			tickers: ["CDX IG", "iTraxx"],
		},
		{
			src: "FT",
			time: "10:58",
			tag: "EM",
			title: "EMBI narrows 12bps this week on disinflation optimism",
			tickers: ["EMBI", "BR EMBI"],
		},
		{
			src: "REUTERS",
			time: "10:22",
			tag: "EQUITY",
			title: "US tech earnings surprise - cloud capex accelerating",
			tickers: ["NDX", "SPX"],
		},
	];
</script>

<div class="mnf-root" class:mnf-root--active={active}>
	<div class="mnf-header">
		<div>
			<span class="mnf-title">MACRO NEWS</span>
			<span class="mnf-badge">LIVE</span>
		</div>
		<span class="mnf-flag">⚑</span>
	</div>
	<div class="mnf-feed">
		{#each news as item}
			<article class="mnf-item">
				<div class="mnf-meta">
					<span class="mnf-src">{item.src}</span>
					<span class="mnf-time">{item.time}</span>
					<span class="mnf-tag">{item.tag}</span>
				</div>
				<div class="mnf-story">{item.title}</div>
				<div class="mnf-tickers">
					{#each item.tickers as ticker}
						<span>{ticker}</span>
					{/each}
				</div>
			</article>
		{/each}
	</div>
</div>

<style>
	.mnf-root {
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--ii-bg);
		font-family: var(--ii-font-mono);
	}
	.mnf-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 32px;
		padding: 0 12px;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface);
	}
	.mnf-title {
		color: var(--ii-text-primary);
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.14em;
	}
	.mnf-badge {
		margin-left: 6px;
		padding: 0 4px;
		border: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-muted);
		font-size: 9px;
		letter-spacing: 0.1em;
	}
	.mnf-root--active .mnf-badge {
		border-color: var(--ii-terminal-up-dim);
		color: var(--ii-success);
	}
	.mnf-flag {
		color: var(--ii-text-muted);
		font-size: 11px;
	}
	.mnf-feed {
		flex: 1;
		min-height: 0;
		overflow: auto;
		background: var(--ii-bg);
	}
	.mnf-item {
		padding: 10px 12px 9px;
		border-bottom: 1px solid var(--ii-terminal-hair);
		background: var(--ii-bg);
		cursor: default;
	}
	.mnf-item:hover {
		background: var(--ii-surface);
	}
	.mnf-meta {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 5px;
		font-size: 9px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.mnf-src {
		color: var(--ii-brand-primary);
		font-weight: 700;
	}
	.mnf-time {
		color: var(--ii-text-muted);
	}
	.mnf-tag {
		padding: 0 6px;
		border: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-secondary);
	}
	.mnf-story {
		color: var(--ii-text-primary);
		font-family: var(--ii-font-sans);
		font-size: 13px;
		line-height: 1.35;
	}
	.mnf-tickers {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 6px;
	}
	.mnf-tickers span {
		padding: 1px 6px;
		border: 1px solid var(--ii-terminal-accent-dim);
		color: var(--ii-brand-primary);
		font-size: 9px;
	}
</style>
