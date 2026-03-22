<!--
  Document detail — metadata, chunks, evidence.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { PageHeader } from "@netz/ui";

	const documentId = $derived($page.params.documentId!);
</script>

<PageHeader
	title="Document"
	breadcrumbs={[{ label: "Documents", href: "/documents" }, { label: documentId }]}
/>

<div class="p-6">
	<div class="rounded-lg border border-(--netz-border-subtle) bg-(--netz-surface-elevated) p-8 text-center">
		<p class="text-sm text-(--netz-text-muted)">Document {documentId} — metadata, chunks, classification, evidence</p>
	</div>
</div>
