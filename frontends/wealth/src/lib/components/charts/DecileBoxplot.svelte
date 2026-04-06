<!--
  Decile Position Boxplot (ECharts).
  Shows where the fund sits relative to its strategy peers.
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';

    let { percentiles = null, strategy = "Peer Group", height = 300 } = $props();

    let chartOptions = $derived.by(() => {
        if (!percentiles) return null;

        const metrics = [
            { name: 'Sharpe', value: percentiles.sharpe },
            { name: 'Sortino', value: percentiles.sortino },
            { name: 'Return', value: percentiles.return },
            { name: 'Drawdown', value: percentiles.drawdown }
        ].filter(m => m.value != null);

        if (metrics.length === 0) return null;

        const categories = metrics.map(m => m.name);
        // Boxplot data: [min, Q1, median, Q3, max]
        // Since we only have the fund's percentile (0-100), we show it as a scatter point
        // over a standard 0-100 boxplot context.
        const boxData = metrics.map(() => [0, 25, 50, 75, 100]);
        const fundData = metrics.map((m, i) => [i, m.value]);

        return {
            title: { text: `Percentile Rank: ${strategy}`, left: 'center', top: 8, textStyle: { fontSize: 13, color: '#71717a' } },
            tooltip: {
                trigger: 'item',
                backgroundColor: '#1e1e22',
                borderColor: '#2a2a2e',
                textStyle: { color: '#e4e4e7', fontSize: 12 },
            },
            grid: { left: 16, right: 16, bottom: 16, top: 48, containLabel: true },
            xAxis: {
                type: 'category',
                data: categories,
                boundaryGap: true,
                axisLabel: { color: '#a1a1aa', fontSize: 12 },
                axisLine: { lineStyle: { color: '#3f3f46' } },
                axisTick: { show: false },
            },
            yAxis: {
                type: 'value',
                min: 0,
                max: 100,
                axisLabel: { formatter: '{value}th', color: '#71717a', fontSize: 11 },
                splitLine: { lineStyle: { type: 'dashed', color: '#2a2a2e' } },
                axisLine: { show: false },
                axisTick: { show: false },
            },
            series: [
                {
                    name: 'Peer Universe',
                    type: 'boxplot',
                    data: boxData,
                    itemStyle: { color: 'rgba(255,255,255,0.03)', borderColor: '#3f3f46' },
                    emphasis: { disabled: true },
                },
                {
                    name: 'This Fund',
                    type: 'scatter',
                    data: fundData,
                    symbolSize: 14,
                    itemStyle: { color: '#0177fb', shadowBlur: 12, shadowColor: 'rgba(1, 119, 251, 0.5)' },
                    label: {
                        show: true,
                        position: 'top',
                        formatter: (p: any) => `${p.value[1].toFixed(0)}th`,
                        fontSize: 12,
                        fontWeight: 'bold',
                        color: '#fafafa',
                    },
                },
            ],
        };
    });
</script>

{#if percentiles}
    <GenericEChart options={chartOptions} {height} />
{:else}
    <div class="no-data">Peer ranking data not available.</div>
{/if}

<style>
    .no-data {
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--ii-text-muted);
        font-style: italic;
        font-size: 13px;
    }
</style>
