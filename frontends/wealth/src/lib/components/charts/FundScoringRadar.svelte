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
        const entries = Object.entries(components);

        // Indicator labels — clean name only, no score in parens
        const indicators = entries.map(([key]) => {
            const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            return { name: label, max: 100 };
        });

        const values = entries.map(([, v]) => Number(v));
        const score = scoringMetrics.manager_score;
        const overall = score != null ? Number(score).toFixed(1) : '—';

        return {
            title: {
                text: `Overall: ${overall}`,
                left: 16,
                top: 8,
                textStyle: { fontSize: 18, fontWeight: '700', color: '#e4e4e7' }
            },
            tooltip: {
                trigger: 'item',
                backgroundColor: '#1e1e22',
                borderColor: '#2a2a2e',
                textStyle: { color: '#e4e4e7', fontSize: 12 },
            },
            radar: {
                indicator: indicators,
                center: ['50%', '55%'],
                radius: '62%',
                splitNumber: 4,
                axisName: { color: '#94a3b8', fontSize: 12 },
                splitLine: { lineStyle: { color: ['rgba(148, 163, 184, 0.15)'] } },
                splitArea: { areaStyle: { color: ['rgba(30, 30, 34, 0.6)', 'rgba(42, 42, 46, 0.4)'] } },
                axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.2)' } }
            },
            series: [
                {
                    name: 'Fund Score',
                    type: 'radar',
                    data: [
                        {
                            value: values,
                            name: 'Score Components',
                            areaStyle: { color: 'rgba(1, 119, 251, 0.25)' },
                            lineStyle: { color: '#0177fb', width: 2 },
                            itemStyle: { color: '#0177fb' },
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
