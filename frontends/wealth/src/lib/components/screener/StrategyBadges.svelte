<script lang="ts">
	let {
		hedge_fund_count,
		pe_fund_count,
		vc_fund_count,
	}: {
		hedge_fund_count: number | null;
		pe_fund_count: number | null;
		vc_fund_count: number | null;
	} = $props();
</script>

<div class="flex items-center gap-1">
	{#if hedge_fund_count && hedge_fund_count > 0}
		<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold leading-none bg-blue-50 text-blue-600">HF {hedge_fund_count}</span>
	{/if}
	{#if pe_fund_count && pe_fund_count > 0}
		<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold leading-none bg-violet-50 text-violet-600">PE {pe_fund_count}</span>
	{/if}
	{#if vc_fund_count && vc_fund_count > 0}
		<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold leading-none bg-emerald-50 text-emerald-600">VC {vc_fund_count}</span>
	{/if}
	{#if !hedge_fund_count && !pe_fund_count && !vc_fund_count}
		<span class="text-muted-foreground">{"\u2014"}</span>
	{/if}
</div>
