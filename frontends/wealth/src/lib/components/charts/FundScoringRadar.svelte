<!--
  Fund Scoring Radar Chart (ECharts Radar).
  Displays multi-dimensional score components (e.g. Risk, Return, Manager).
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';

    let { scoringMetrics = null, height = 350 } = $props();

    let chartOptions = $derived.by(() => {
        if (!scoringMetrics || !scoringMetrics.score_components) return null;

        const components = scoringMetrics.score_components;
        const indicators = Object.keys(components).map(key => ({
            name: key.replace(/_/g, ' ').toUpperCase(),
            max: 100
        }));
        
        const values = Object.values(components).map(v => Number(v));

        return {
            title: {
                text: `Overall: ${scoringMetrics.manager_score?.toFixed(1) || '—'}`,
                left: 'center',
                top: 'center',
                textStyle: { fontSize: 24, fontWeight: '800', color: '#1d293d' }
            },
            tooltip: { trigger: 'item' },
            radar: {
                indicator: indicators,
                radius: '65%',
                splitNumber: 4,
                axisName: { color: '#64748b' },
                splitLine: { lineStyle: { color: ['rgba(203, 213, 225, 0.4)'] } },
                splitArea: { areaStyle: { color: ['rgba(241, 245, 249, 0.2)', 'rgba(248, 250, 252, 0.4)'] } },
                axisLine: { lineStyle: { color: 'rgba(203, 213, 225, 0.4)' } }
            },
            series: [
                {
                    name: 'Fund Score',
                    type: 'radar',
                    data: [
                        {
                            value: values,
                            name: 'Score Components',
                            areaStyle: { color: 'rgba(59, 130, 246, 0.3)' },
                            lineStyle: { color: '#3b82f6', width: 2 },
                            itemStyle: { color: '#3b82f6' },
                            symbol: 'circle',
                            symbolSize: 6
                        }
                    ]
                }
            ]
        };
    });
</script>

{#if scoringMetrics && scoringMetrics.score_components}
    <GenericEChart options={chartOptions} {height} />
{:else}
    <div class="no-data">Scoring components not available.</div>
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
