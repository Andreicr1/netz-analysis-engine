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
            title: { text: `Relative Performance: ${strategy}`, left: 'center', textStyle: { fontSize: 14, color: '#64748b' } },
            tooltip: { trigger: 'item' },
            grid: { left: '10%', right: '10%', bottom: '15%' },
            xAxis: {
                type: 'category',
                data: categories,
                boundaryGap: true,
                axisLabel: { color: '#64748b' }
            },
            yAxis: {
                type: 'value',
                min: 0,
                max: 100,
                axisLabel: { formatter: '{value}th', color: '#64748b' },
                splitLine: { lineStyle: { type: 'dashed', color: '#e2e8f0' } }
            },
            series: [
                {
                    name: 'Peer Universe',
                    type: 'boxplot',
                    data: boxData,
                    itemStyle: { color: '#f8fafc', borderColor: '#cbd5e1' },
                    emphasis: { disabled: true }
                },
                {
                    name: 'This Fund',
                    type: 'scatter',
                    data: fundData,
                    symbolSize: 12,
                    itemStyle: { color: '#3b82f6', shadowBlur: 10, shadowColor: 'rgba(59, 130, 246, 0.5)' },
                    label: {
                        show: true,
                        position: 'top',
                        formatter: (p: any) => `${p.value[1].toFixed(0)}%`,
                        fontSize: 11,
                        fontWeight: 'bold'
                    }
                }
            ]
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
