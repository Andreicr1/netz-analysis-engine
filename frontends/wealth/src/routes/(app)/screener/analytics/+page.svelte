<!--
  Screener Analytics — Advanced fund universe analysis.
  Placeholder — will be enriched with scatter plots, correlation, factor analysis.
-->
<script lang="ts">
  import { Axis3d } from "lucide-svelte";
</script>

<svelte:head>
  <title>Analytics — Screener — InvestIntell</title>
</svelte:head>

<div class="sa-empty">
  <Axis3d size={48} class="sa-icon" />
  <h2 class="sa-title">Fund Universe Analytics</h2>
  <p class="sa-desc">
    Advanced analytics for the fund universe — risk-return scatter, factor decomposition, correlation matrix, and peer clustering.
  </p>
  <p class="sa-hint">Coming soon.</p>
</div>

<style>
  .sa-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 400px;
    gap: 12px;
    text-align: center;
    color: #cbccd1;
  }

  :global(.sa-icon) {
    color: #0177fb;
    opacity: 0.5;
  }

  .sa-title {
    font-size: 22px;
    font-weight: 700;
    color: #fff;
    margin: 0;
  }

  .sa-desc {
    max-width: 480px;
    font-size: 14px;
    line-height: 1.6;
    color: #cbccd1;
    margin: 0;
  }

  .sa-hint {
    font-size: 13px;
    font-style: italic;
    color: #71717a;
    margin: 0;
  }
</style>
