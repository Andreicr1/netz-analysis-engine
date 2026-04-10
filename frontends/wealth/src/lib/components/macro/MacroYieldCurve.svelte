<script lang="ts">
    import GenericEChart from '../charts/GenericEChart.svelte';

    const maturities = ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'];
    
    const currentYield = [5.40, 5.42, 5.35, 5.10, 4.60, 4.40, 4.30, 4.35, 4.45, 4.70, 4.65];
    const monthAgoYield = [5.38, 5.40, 5.30, 5.00, 4.45, 4.25, 4.15, 4.20, 4.30, 4.55, 4.50];
    const yearAgoYield = [4.10, 4.50, 4.80, 4.70, 4.10, 3.90, 3.60, 3.70, 3.50, 3.80, 3.75];

    const options = {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis'
        },
        legend: {
            data: ['Current', '1 Month Ago', '1 Year Ago'],
            textStyle: { color: '#94a3b8', fontSize: 10 },
            bottom: 10,
            icon: 'circle',
            itemWidth: 8,
            itemHeight: 8
        },
        grid: {
            left: 45,
            right: 20,
            top: 40,
            bottom: 50
        },
        xAxis: {
            type: 'category',
            data: maturities,
            axisLine: { lineStyle: { color: '#334155' } },
            axisLabel: { color: '#94a3b8', fontSize: 10 }
        },
        yAxis: {
            type: 'value',
            min: 3,
            max: 6,
            splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
            axisLabel: { 
                color: '#94a3b8', 
                fontSize: 10, 
                fontFamily: 'monospace',
                formatter: '{value}%'
            }
        },
        series: [
            {
                name: 'Current',
                type: 'line',
                data: currentYield,
                itemStyle: { color: '#2d7ef7' },
                lineStyle: { width: 2, type: 'solid' },
                showSymbol: false
            },
            {
                name: '1 Month Ago',
                type: 'line',
                data: monthAgoYield,
                itemStyle: { color: '#64748b' },
                lineStyle: { width: 1.5, type: 'dashed' },
                showSymbol: false
            },
            {
                name: '1 Year Ago',
                type: 'line',
                data: yearAgoYield,
                itemStyle: { color: '#475569' },
                lineStyle: { width: 1.5, type: 'dotted' },
                showSymbol: false
            }
        ]
    };
</script>

<div class="yc-root">
    <div class="yc-header">YIELD CURVE MONITOR</div>
    <div class="yc-body">
        <GenericEChart {options} height={100} />
    </div>
</div>

<style>
    .yc-root {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        background: #05080f;
    }
    .yc-header {
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
    .yc-body {
        flex: 1;
        min-width: 0;
        min-height: 0;
        position: relative;
    }
    .yc-body > :global(div) {
        position: absolute !important;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        height: 100% !important;
    }
</style>
