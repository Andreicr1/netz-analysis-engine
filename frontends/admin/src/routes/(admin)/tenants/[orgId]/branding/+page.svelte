<!--
  Tenant Branding — color pickers, font selector, logo upload, live preview.
-->
<script lang="ts">
	import BrandingEditor from "$lib/components/BrandingEditor.svelte";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<div class="space-y-6 p-6">
	<h2 class="text-xl font-bold text-[var(--netz-text-primary)]">Branding</h2>
	<BrandingEditor branding={data.branding} orgId={data.orgId} />
</div>
