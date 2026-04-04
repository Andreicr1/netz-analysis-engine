<!--
  Market Intelligence Lab — Advanced ECharts Test Page.
  Three interactive visualizations: Scatter, Force Graph, Treemap/Sunburst morph.
-->
<script lang="ts">
  import FundScatterChart from "$lib/components/charts-v2/FundScatterChart.svelte";
  import ContagionNetworkGraph from "$lib/components/charts-v2/ContagionNetworkGraph.svelte";
  import SectorAllocationTransition from "$lib/components/charts-v2/SectorAllocationTransition.svelte";
</script>

<svelte:head>
  <title>Market Intelligence Lab — InvestIntell</title>
</svelte:head>

<div class="lab-page">
  <header class="lab-header">
    <h1 class="lab-title">Market Intelligence Lab</h1>
    <p class="lab-subtitle">Advanced interactive visualizations — ECharts 5.6</p>
  </header>

  <div class="lab-grid">
    <!-- A: Risk-Return Galaxy (full width) -->
    <div class="lab-card lab-card--full">
      <FundScatterChart />
    </div>

    <!-- B: Contagion Map (full width) -->
    <div class="lab-card lab-card--full">
      <ContagionNetworkGraph />
    </div>

    <!-- C: Sector Deep Dive (full width) -->
    <div class="lab-card lab-card--full">
      <SectorAllocationTransition />
    </div>
  </div>
</div>

<style>
  .lab-page {
    padding: 24px;
    max-width: 1400px;
    margin: 0 auto;
  }

  .lab-header {
    margin-bottom: 24px;
  }

  .lab-title {
    font-family: "Urbanist", sans-serif;
    font-size: 24px;
    font-weight: 800;
    color: var(--ii-text-primary, #fafafa);
    margin: 0;
  }

  .lab-subtitle {
    font-family: "Urbanist", sans-serif;
    font-size: 13px;
    color: var(--ii-text-muted, #71717a);
    margin: 4px 0 0 0;
  }

  .lab-grid {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .lab-card {
    border-radius: 16px;
    overflow: hidden;
  }

  .lab-card--full {
    width: 100%;
  }
</style>
