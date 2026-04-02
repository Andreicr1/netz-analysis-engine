<!--
  Current Sector Allocation Treemap (ECharts Treemap).
  Provides a hierarchical view of current portfolio exposure.
-->
<script lang="ts">
    import GenericEChart from './GenericEChart.svelte';

    let { sectorWeights = {}, height = 350 } = $props();

    let chartOptions = $derived.by(() => {
        if (!sectorWeights || Object.keys(sectorWeights).length === 0) return null;

        const data = Object.entries(sectorWeights)
            .filter(([_, v]) => v > 0)
            .map(([name, value]) => ({
                name,
                value: Number(value) * 100
            }))
            .sort((a, b) => b.value - a.value);

        return {
            tooltip: {
                formatter: (info: any) => {
                    return `${info.name}: <b>${info.value.toFixed(2)}%</b>`;
                }
            },
            series: [
                {
                    name: 'Sectors',
                    type: 'treemap',
                    visibleMin: 300,
                    label: { show: true, formatter: '{b}' },
                    itemStyle: {
                        borderColor: '#fff',
                        borderWidth: 1,
                        gapWidth: 1
                    },
                    upperLabel: { show: false },
                    data: data,
                    levels: [
                        {
                            itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 },
                            color: ['#3b82f6', '#60a5fa', '#93c5fd', '#bfdbfe', '#dbeafe']
                        }
                    ]
                }
            ]
        };
    });
</script>

{#if sectorWeights && Object.keys(sectorWeights).length > 0}
    <GenericEChart options={chartOptions} {height} />
{:else}
    <div class="no-data">Current allocation data not available.</div>
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
