<!--
  NAV Performance Chart (ECharts Area Simple).
  Shows historical growth of the fund.
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';
    import { formatNumber } from "@investintell/ui";

    let { navData = [], height = 300 } = $props();

    let chartOptions = $derived.by(() => {
        if (!navData || navData.length === 0) return null;

        const dates = navData.map(d => d.nav_date);
        const values = navData.map(d => d.nav);

        return {
            tooltip: {
                trigger: 'axis',
                formatter: (params: any) => {
                    const p = params[0];
                    return `${p.name}<br/>NAV: <b>$${formatNumber(p.value, 2)}</b>`;
                }
            },
            grid: {
                left: '3%',
                right: '4%',
                bottom: '3%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                boundaryGap: false,
                data: dates,
                axisLabel: {
                    formatter: (value: string) => value.split('-')[0] // Show year only on axis for cleaner look
                }
            },
            yAxis: {
                type: 'value',
                scale: true, // Don't start at zero to show volatility better
                axisLabel: {
                    formatter: (value: number) => `$${formatNumber(value, 0, "en-US", { useGrouping: false })}`
                }
            },
            series: [
                {
                    name: 'NAV',
                    type: 'line',
                    smooth: true,
                    symbol: 'none',
                    areaStyle: {
                        color: {
                            type: 'linear',
                            x: 0, y: 0, x2: 0, y2: 1,
                            colorStops: [
                                { offset: 0, color: 'rgba(59, 130, 246, 0.5)' },
                                { offset: 1, color: 'rgba(59, 130, 246, 0.1)' }
                            ]
                        }
                    },
                    lineStyle: { color: '#3b82f6', width: 2 },
                    data: values
                }
            ]
        };
    });
</script>

{#if navData && navData.length > 0}
    <GenericEChart options={chartOptions} {height} />
{:else}
    <div class="no-data">Historical NAV data not available.</div>
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
