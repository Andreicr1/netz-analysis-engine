<!--
  Dataroom — folder browser with breadcrumb navigation.
-->
<script lang="ts">
	import { SectionCard, EmptyState, PageHeader } from "@netz/ui";
</script>

<div class="px-6">
	<PageHeader
		title="Dataroom"
		breadcrumbs={[{ label: "Funds", href: "/funds" }, { label: "Documents" }, { label: "Dataroom" }]}
	/>
	<SectionCard title="Dataroom Browser">
		<EmptyState
			title="No Documents"
			description="Browse and manage documents in the virtual data room. Folder tree and file browser will connect to the dataroom API."
		/>
	</SectionCard>
</div>
