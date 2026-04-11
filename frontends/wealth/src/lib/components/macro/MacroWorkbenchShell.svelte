<script lang="ts">
    import MacroSignalsGrid from './MacroSignalsGrid.svelte';
    import MacroStressChart from './MacroStressChart.svelte';
    import MacroYieldCurve from './MacroYieldCurve.svelte';
</script>

<div class="macro-root">
    <div class="macro-col macro-col-left">
        <MacroSignalsGrid />
    </div>
    <div class="macro-col macro-col-center">
        <MacroStressChart />
    </div>
    <div class="macro-col macro-col-right">
        <MacroYieldCurve />
    </div>
</div>

<style>
    .macro-root {
        display: grid;
        grid-template-columns: 300px 1fr 350px;
        gap: 1px;
        background: #1e293b;
        width: 100%;
        height: 100%;
        min-width: 0;
        min-height: 0;
        overflow: hidden;
        font-family: "Urbanist", system-ui, sans-serif;
    }

    .macro-col {
        background: #05080f;
        min-width: 0;
        min-height: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }
</style>
