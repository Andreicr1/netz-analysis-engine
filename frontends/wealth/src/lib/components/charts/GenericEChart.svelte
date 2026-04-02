<!--
  Generic ECharts Wrapper — Loads ECharts from CDN and handles resizing.
  Used to overcome environment package installation restrictions.
-->
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';

    let { options, height = 400, theme = 'light' } = $props();
    
    let chartDom: HTMLElement;
    let chartInstance: any = null;
    let echartsLoaded = $state(false);

    async function loadECharts() {
        if ((window as any).echarts) {
            echartsLoaded = true;
            return;
        }

        return new Promise<void>((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js';
            script.onload = () => {
                echartsLoaded = true;
                resolve();
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    $effect(() => {
        if (echartsLoaded && chartDom && options) {
            if (!chartInstance) {
                chartInstance = (window as any).echarts.init(chartDom, theme, { renderer: 'svg' });
            }
            chartInstance.setOption(options, true);
        }
    });

    onMount(() => {
        loadECharts();

        const resizeHandler = () => {
            chartInstance?.resize();
        };
        window.addEventListener('resize', resizeHandler);

        return () => {
            window.removeEventListener('resize', resizeHandler);
            chartInstance?.dispose();
        };
    });

    onDestroy(() => {
        chartInstance?.dispose();
    });
</script>

<div 
    bind:this={chartDom} 
    style:height="{height}px" 
    style:width="100%"
>
    {#if !echartsLoaded}
        <div class="echart-loading">Loading charts...</div>
    {/if}
</div>

<style>
    .echart-loading {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: var(--ii-text-muted);
        font-size: 13px;
        background: var(--ii-surface-alt);
        border-radius: 8px;
    }
</style>
