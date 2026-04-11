<!--
  RollingReturnsChart — Compact line chart for 3m, 6m, 1y rolling returns.
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';
    import { formatPercent } from "@investintell/ui";

    let { rollingReturns, height = 300 } = $props();

    const options = $derived({
        backgroundColor: 'transparent',
        grid: { top: 40, right: 20, bottom: 40, left: 50, containLabel: true },
        legend: {
            top: 10,
            itemWidth: 10,
            itemHeight: 2,
            textStyle: { color: '#71717a', fontSize: 9, fontFamily: 'monospace' },
            data: ['3M', '6M', '1Y']
        },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            formatter: (params: any) => {
                let s = `<div class="font-mono text-[10px] uppercase p-1">
                    <div class="text-[#71717a] mb-1">${params[0].axisValue}</div>`;
                params.forEach((p: any) => {
                    s += `<div class="flex justify-between gap-4">
                        <span style="color:${p.color}">${p.seriesName}:</span>
                        <span class="font-bold text-white">${formatPercent(p.value)}</span>
                    </div>`;
                });
                s += `</div>`;
                return s;
            }
        },
        xAxis: {
            type: 'category',
            data: rollingReturns?.dates ?? [],
            axisLabel: { 
                color: '#71717a', 
                fontSize: 9, 
                fontFamily: 'monospace',
                formatter: (val: string) => val.split('-').slice(1).join('/')
            },
            axisLine: { lineStyle: { color: '#222' } }
        },
        yAxis: {
            type: 'value',
            splitLine: { lineStyle: { color: '#222' } },
            axisLabel: { 
                color: '#71717a', 
                fontSize: 9, 
                fontFamily: 'monospace',
                formatter: (val: number) => formatPercent(val)
            }
        },
        series: [
            {
                name: '3M',
                type: 'line',
                data: rollingReturns?.returns_3m ?? [],
                symbol: 'none',
                smooth: true,
                lineStyle: { width: 1.5, color: '#0177fb' }
            },
            {
                name: '6M',
                type: 'line',
                data: rollingReturns?.returns_6m ?? [],
                symbol: 'none',
                smooth: true,
                lineStyle: { width: 1.5, color: '#1b9858' }
            },
            {
                name: '1Y',
                type: 'line',
                data: rollingReturns?.returns_1y ?? [],
                symbol: 'none',
                smooth: true,
                lineStyle: { width: 1.5, color: '#ef4343' }
            }
        ]
    });
</script>

<div class="bg-black border border-[#222]">
    <GenericEChart {options} {height} theme="dark" />
</div>
