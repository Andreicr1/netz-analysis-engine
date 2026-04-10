<script lang="ts">
    type Signal = { name: string; value: string; trend: 'up' | 'down' | 'neutral'; state: 'stress' | 'relief' };

    const fastSignals: Signal[] = [
        { name: 'VIX', value: '14.20', trend: 'down', state: 'relief' },
        { name: 'US HY OAS', value: '3.12%', trend: 'down', state: 'relief' },
        { name: 'Energy Shock', value: '1.05', trend: 'up', state: 'stress' },
        { name: 'DXY Z-score', value: '0.85', trend: 'neutral', state: 'stress' },
    ];

    const slowSignals: Signal[] = [
        { name: 'CFNAI', value: '-0.15', trend: 'down', state: 'stress' },
        { name: 'Yield Curve 10Y-2Y', value: '-45 bps', trend: 'up', state: 'stress' },
        { name: 'BAA-10Y', value: '1.85%', trend: 'neutral', state: 'relief' },
        { name: 'Fed Funds Δ6m', value: '0 bps', trend: 'neutral', state: 'relief' },
        { name: 'Sahm Rule', value: '0.35', trend: 'up', state: 'stress' },
    ];
</script>

<div class="sig-root">
    <div class="sig-header">ECONOMIC CLOCK</div>
    <div class="sig-scroll">
        <div class="sig-group-title">FAST SIGNALS</div>
        <table class="sig-table">
            <tbody>
                {#each fastSignals as sig}
                    <tr>
                        <td class="sig-name">{sig.name}</td>
                        <td class="sig-val">{sig.value}</td>
                        <td class="sig-trend {sig.state}">
                            {#if sig.trend === 'up'}▲
                            {:else if sig.trend === 'down'}▼
                            {:else}━{/if}
                        </td>
                    </tr>
                {/each}
            </tbody>
        </table>

        <div class="sig-group-title mt-4">SLOW SIGNALS</div>
        <table class="sig-table">
            <tbody>
                {#each slowSignals as sig}
                    <tr>
                        <td class="sig-name">{sig.name}</td>
                        <td class="sig-val">{sig.value}</td>
                        <td class="sig-trend {sig.state}">
                            {#if sig.trend === 'up'}▲
                            {:else if sig.trend === 'down'}▼
                            {:else}━{/if}
                        </td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
</div>

<style>
    .sig-root {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        background: #05080f;
    }
    .sig-header {
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
    .sig-scroll {
        flex: 1;
        overflow-y: auto;
        padding: 12px;
    }
    .sig-group-title {
        font-size: 10px;
        font-weight: 700;
        color: #64748b;
        margin-bottom: 8px;
        letter-spacing: 0.05em;
    }
    .mt-4 { margin-top: 16px; }
    .sig-table {
        width: 100%;
        border-collapse: collapse;
    }
    .sig-table td {
        padding: 6px 0;
        border-bottom: 1px solid rgba(255,255,255,0.04);
        font-size: 11px;
    }
    .sig-name {
        color: #cbd5e1;
        text-align: left;
    }
    .sig-val {
        color: #ffffff;
        text-align: right;
        font-variant-numeric: tabular-nums;
        font-family: monospace;
    }
    .sig-trend {
        text-align: right;
        width: 24px;
        font-size: 10px;
    }
    .stress { color: #ef4444; } /* Red */
    .relief { color: #10b981; } /* Green */

    .sig-scroll::-webkit-scrollbar { width: 4px; }
    .sig-scroll::-webkit-scrollbar-track { background: transparent; }
    .sig-scroll::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); }
</style>
