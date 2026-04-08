<!--
  DiscoveryManagersTable — renders the manager universe via EnterpriseTable.
  Columns switch between compact (col1 in expand-2/3) and full (expand-1) modes.
-->
<script lang="ts">
	import { EnterpriseTable } from "@investintell/ui";
	import { managerColumns, type ManagerRow } from "./columns";

	interface Props {
		rows: ManagerRow[];
		compact: boolean;
		selectedId: string | null;
		onSelect: (id: string) => void;
	}

	let { rows, compact, selectedId, onSelect }: Props = $props();
	const columns = $derived(managerColumns(compact));
</script>

<EnterpriseTable
	{rows}
	{columns}
	rowKey={(r) => r.manager_id}
	freezeFirstColumn={!compact}
	onRowClick={(r) => onSelect(r.manager_id)}
	rowAttrs={(r) => ({
		"data-selected": r.manager_id === selectedId ? "true" : undefined,
	})}
/>

<style>
	:global([data-selected="true"] td) {
		background: var(--ii-surface-accent, rgba(80, 140, 255, 0.12)) !important;
	}
</style>
