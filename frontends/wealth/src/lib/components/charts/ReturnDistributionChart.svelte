<!--
  ReturnDistributionChart — Histogram of daily returns with VaR/CVaR markers.
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';
    import { formatPercent } from "@investintell/ui";

    let { distribution, tailRisk, height = 300 } = $props();

    const options = $derived({
        backgroundColor: 'transparent',
        grid: { top: 20, right: 20, bottom: 40, left: 40, containLabel: true },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter: (params: any) => {
                const p = params[0];
                return `<div class="font-mono text-[10px] uppercase p-1">
                    <div class="text-[#71717a] mb-1">Bin: ${p.name}</div>
                    <div class="font-bold text-white">Count: ${p.value}</div>
                </div>`;
            }
        },
        xAxis: {
            type: 'category',
            data: distribution?.bins?.map((b: number) => formatPercent(b)) ?? [],
            axisLabel: { color: '#71717a', fontSize: 9, fontStyle: 'normal', fontFamily: 'monospace' },
            axisLine: { lineStyle: { color: '#222' } }
        },
        yAxis: {
            type: 'value',
            splitLine: { lineStyle: { color: '#222' } },
            axisLabel: { color: '#71717a', fontSize: 9, fontFamily: 'monospace' }
        },
        series: [
            {
                name: 'Returns',
                type: 'bar',
                data: distribution?.counts ?? [],
                itemStyle: { color: '#0177fb' },
                barWidth: '90%',
                markLine: {
                    symbol: ['none', 'none'],
                    label: { show: true, position: 'end', fontSize: 9, fontFamily: 'monospace', formatter: '{b}' },
                    lineStyle: { type: 'dashed', width: 1 },
                    data: [
                        { xAxis: findClosestBin(tailRisk?.var_parametric_95), name: 'VaR 95', lineStyle: { color: '#ef4343' } },
                        { xAxis: findClosestBin(tailRisk?.etl_95), name: 'CVaR 95', lineStyle: { color: '#ef4343', width: 2 } }
                    ].filter(d => d.xAxis !== null)
                }
            }
        ]
    });

    function findClosestBin(val: number | null | undefined): string | null {
        if (val == null || !distribution?.bins) return null;
        let closest = distribution.bins[0];
        let minDiff = Math.abs(val - closest);
        for (const b of distribution.bins) {
            const diff = Math.abs(val - b);
            if (diff < minDiff) {
                minDiff = diff;
                closest = b;
            }
        }
        return formatPercent(closest);
    }
</script>

<div class="bg-black border border-[#222]">
    <GenericEChart {options} {height} theme="dark" />
</div>
