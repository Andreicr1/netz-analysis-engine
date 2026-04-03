<!--
  Screener Level 1 — Manager Catalog.
-->
<script lang="ts">
  import { CatalogTable } from "$lib/components/screener";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();
</script>

<svelte:head>
  <title>Screener — Netz Wealth</title>
</svelte:head>

<div class="h-full p-6">
  <CatalogTable managers={data.managers} totalCount={data.totalCount} />
</div>
