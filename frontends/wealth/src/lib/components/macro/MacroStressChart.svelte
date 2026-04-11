<script lang="ts">
    import GenericEChart from '../charts/GenericEChart.svelte';

    const dates = ['2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024'];
    const scores = [15, 22, 18, 30, 20, 85, 25, 45, 35, 15];

    const markAreas = [
        [
            { xAxis: '2020', itemStyle: { color: 'rgba(239, 68, 68, 0.08)' } },
            { xAxis: '2021' }
        ],
        [
            { xAxis: '2018', itemStyle: { color: 'rgba(202, 138, 4, 0.05)' } },
            { xAxis: '2019' }
        ],
        [
            { xAxis: '2022', itemStyle: { color: 'rgba(202, 138, 4, 0.05)' } },
            { xAxis: '2024' }
        ]
    ];

    const options = {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' }
        },
        grid: {
            left: 40,
            right: 20,
            top: 40,
            bottom: 30
        },
        xAxis: {
            type: 'category',
            data: dates,
            axisLine: { lineStyle: { color: '#334155' } },
            axisLabel: { color: '#94a3b8', fontSize: 10 }
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
            axisLabel: { color: '#94a3b8', fontSize: 10, fontFamily: 'monospace' }
        },
        series: [
            {
                name: 'Composite Score',
                type: 'line',
                data: scores,
                itemStyle: { color: '#2d7ef7' },
                lineStyle: { width: 2 },
                showSymbol: false,
                markArea: {
                    silent: true,
                    data: markAreas
                }
            }
        ]
    };
</script>

<div class="chart-root">
    <div class="chart-header">NETZ STRESS INDEX</div>
    <div class="chart-body">
        <GenericEChart {options} height={100} />
    </div>
</div>

<style>
    .chart-root {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        background: #05080f;
    }
    .chart-header {
        height: 32px;
        line-height: 32px;
        padding: 0 12px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.05em;
        color: #94a3b8;
        background: #0e1320;
        border-bottom: 1px solid #1e293b;
        flex-shrink: 0;
    }
    .chart-body {
        flex: 1;
        min-width: 0;
        min-height: 0;
        position: relative;
    }
    .chart-body > :global(div) {
        position: absolute !important;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        height: 100% !important;
    }
</style>
