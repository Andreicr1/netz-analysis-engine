<!--
  Dataroom — folder browser with breadcrumb navigation.
-->
<script lang="ts">
	import { Card, EmptyState } from "@netz/ui";
	import { page } from "$app/state";

	// Dataroom will use the /api/data-room/tree and /api/data-room/list endpoints.
	// For now, render a placeholder that will be wired to the API.
</script>

<div class="p-6">
	<h2 class="mb-4 text-xl font-semibold text-[var(--netz-text-primary)]">Dataroom</h2>
	<Card class="p-6">
		<EmptyState
			title="Dataroom Browser"
			description="Browse and manage documents in the virtual data room. Folder tree and file browser will connect to the dataroom API."
		/>
	</Card>
</div>
