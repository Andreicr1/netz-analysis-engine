<!--
  Generic ECharts Wrapper — Uses bundled echarts from @investintell/ui.
  Handles init, reactive option updates, resize, and cleanup.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { echarts } from '@investintell/ui/charts/echarts-setup';

    let { options, height = 400, theme = 'light' } = $props();

    let chartDom: HTMLElement;
    let chartInstance: ReturnType<typeof echarts.init> | null = null;

    $effect(() => {
        if (chartDom && options) {
            if (!chartInstance) {
                chartInstance = echarts.init(chartDom, theme, { renderer: 'svg' });
            }
            chartInstance.setOption(options, true);
        }
    });

    onMount(() => {
        const resizeHandler = () => {
            chartInstance?.resize();
        };
        window.addEventListener('resize', resizeHandler);

        return () => {
            window.removeEventListener('resize', resizeHandler);
            chartInstance?.dispose();
            chartInstance = null;
        };
    });
</script>

<div
    bind:this={chartDom}
    style:height="{height}px"
    style:width="100%"
></div>
