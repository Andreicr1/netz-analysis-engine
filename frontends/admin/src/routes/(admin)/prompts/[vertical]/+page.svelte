<script lang="ts">
	import { page } from "$app/stores";
	import { SectionCard, EmptyState } from "@netz/ui";

	const vertical = $derived($page.params.vertical);
</script>

<div class="space-y-6 p-6">
	<SectionCard title="Prompt Editor — {vertical}">
		<EmptyState message="Prompt editor coming soon." />
	</SectionCard>
</div>
