<script lang="ts">
	let {
		hedge_fund_count,
		pe_fund_count,
		vc_fund_count,
		mutual_fund_count,
	}: {
		hedge_fund_count: number | null;
		pe_fund_count: number | null;
		vc_fund_count: number | null;
		mutual_fund_count: number | null;
	} = $props();

	let hasAny = $derived(
		(hedge_fund_count ?? 0) > 0 ||
		(pe_fund_count ?? 0) > 0 ||
		(vc_fund_count ?? 0) > 0 ||
		(mutual_fund_count ?? 0) > 0
	);
</script>

<div class="flex items-center gap-1">
	{#if !hasAny}
		<span class="text-muted-foreground">{"\u2014"}</span>
	{:else}
		{#if mutual_fund_count && mutual_fund_count > 0}
			<span class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-sky-100 text-[9px] font-bold text-sky-700" title="Mutual Funds">MF</span>
		{/if}
		{#if hedge_fund_count && hedge_fund_count > 0}
			<span class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-[9px] font-bold text-blue-700" title="Hedge Funds">HF</span>
		{/if}
		{#if pe_fund_count && pe_fund_count > 0}
			<span class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-violet-100 text-[9px] font-bold text-violet-700" title="Private Equity">PE</span>
		{/if}
		{#if vc_fund_count && vc_fund_count > 0}
			<span class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-100 text-[9px] font-bold text-emerald-700" title="Venture Capital">VC</span>
		{/if}
	{/if}
</div>
