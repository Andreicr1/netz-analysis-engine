<!--
  Sector Allocation Evolution Chart (ECharts Area Stack).
  Shows how fund sector weights change over report dates.
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';

    let { history = [], height = 350 } = $props();

    let chartOptions = $derived.by(() => {
        if (!history || history.length === 0) return null;

        // Extract unique sectors and dates
        const dates = history.map(h => h.report_date);
        const allSectors = new Set<string>();
        history.forEach(h => {
            Object.keys(h.sector_weights).forEach(s => allSectors.add(s));
        });
        const sectors = Array.from(allSectors).sort();

        // Build series data
        const series = sectors.map(sector => {
            return {
                name: sector,
                type: 'line',
                stack: 'Total',
                areaStyle: {},
                emphasis: { focus: 'series' },
                data: history.map(h => (h.sector_weights[sector] || 0) * 100)
            };
        });

        return {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross', label: { backgroundColor: '#6a7985' } },
                formatter: (params: any) => {
                    let res = `${params[0].name}<br/>`;
                    params.forEach((p: any) => {
                        if (p.value > 0) {
                            res += `${p.marker} ${p.seriesName}: <b>${p.value.toFixed(2)}%</b><br/>`;
                        }
                    });
                    return res;
                }
            },
            legend: {
                data: sectors,
                bottom: 0,
                type: 'scroll'
            },
            grid: {
                left: '3%',
                right: '4%',
                bottom: '15%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                boundaryGap: false,
                data: dates
            },
            yAxis: {
                type: 'value',
                max: 100,
                axisLabel: { formatter: '{value}%' }
            },
            series: series
        };
    });
</script>

{#if history && history.length > 0}
    <GenericEChart options={chartOptions} {height} />
{:else}
    <div class="no-data">No sector history available.</div>
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
