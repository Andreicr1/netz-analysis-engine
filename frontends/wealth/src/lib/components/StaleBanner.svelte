<!--
  Stale data banner — shown when store status is 'stale'.
  "Data may be out of date. Pipeline last ran: [time]. [Refresh →]"
-->
<script lang="ts">
	import { formatLastUpdated } from "$lib/stores/stale";

	let {
		lastUpdated,
		onRefresh,
	}: {
		lastUpdated: Date | null;
		onRefresh: () => void;
	} = $props();
</script>

<div
	class="flex items-center gap-2 rounded-md border border-(--ii-warning)/30 bg-(--ii-warning)/5 px-4 py-2 text-sm text-(--ii-warning)"
	role="alert"
>
	<span>
		Data may be out of date. Pipeline last ran: {formatLastUpdated(lastUpdated)}.
	</span>
	<button
		class="font-medium underline hover:no-underline"
		onclick={onRefresh}
	>
		Refresh &rarr;
	</button>
</div>
