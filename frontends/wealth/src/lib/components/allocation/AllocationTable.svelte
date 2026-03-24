<!--
  AllocationTable — hierarchical L1 (Geography) / L2 (Asset Class) table
  with columns per risk profile. Used in strategic, tactical, and effective tabs.
-->
<script lang="ts">
	import { formatPercent } from "@netz/ui";
	import type { BlockMeta, AllocationRow } from "./types";

	type ProfileKey = string;

	type GroupedRow = {
		block_id: string;
		display_name: string;
		geography: string;
		asset_class: string;
		values: Record<ProfileKey, number>;
	};

	type TabMode = "strategic" | "tactical" | "effective";

	interface Props {
		blocks: BlockMeta[];
		/** Map of profileKey -> array of { block_id, weight } */
		data: Record<ProfileKey, AllocationRow[]>;
		profiles: ProfileKey[];
		profileLabels: Record<ProfileKey, string>;
		mode: TabMode;
	}

	let { blocks, data, profiles, profileLabels, mode }: Props = $props();

	// Build grouped rows: geography -> asset_class -> block rows
	type GeoGroup = {
		geography: string;
		rows: GroupedRow[];
	};

	let groupedData = $derived.by((): GeoGroup[] => {
		// Merge block metadata with allocation data
		const rowMap = new Map<string, GroupedRow>();

		for (const block of blocks) {
			rowMap.set(block.block_id, {
				block_id: block.block_id,
				display_name: block.display_name,
				geography: block.geography,
				asset_class: block.asset_class,
				values: {},
			});
		}

		// Fill in values from each profile's data
		for (const profile of profiles) {
			const profileData = data[profile] ?? [];
			for (const item of profileData) {
				const row = rowMap.get(item.block_id);
				if (row) {
					row.values[profile] = item.weight;
				}
			}
		}

		// Group by geography
		const geoMap = new Map<string, GroupedRow[]>();
		for (const row of rowMap.values()) {
			// Only include rows that have at least one non-zero value
			const hasValue = profiles.some((p) => (row.values[p] ?? 0) !== 0);
			if (!hasValue) continue;

			const group = geoMap.get(row.geography) ?? [];
			group.push(row);
			geoMap.set(row.geography, group);
		}

		// Sort geographies and rows within each group
		const groups: GeoGroup[] = [];
		for (const [geography, rows] of [...geoMap.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
			rows.sort((a, b) => a.asset_class.localeCompare(b.asset_class));
			groups.push({ geography, rows });
		}

		return groups;
	});

	let isEmpty = $derived(groupedData.length === 0);

	function formatValue(value: number | undefined, tabMode: TabMode): string {
		if (value === undefined || value === null) return "—";
		if (tabMode === "tactical") {
			if (Math.abs(value) < 0.00005) return "—";
			const sign = value >= 0 ? "+" : "";
			return `${sign}${formatPercent(value, 1, "en-US")}`;
		}
		return formatPercent(value, 1, "en-US");
	}

	function tacticalColor(value: number | undefined): string {
		if (value === undefined || value === null || Math.abs(value) < 0.00005) return "";
		return value > 0 ? "at-val--positive" : "at-val--negative";
	}
</script>

{#if isEmpty}
	<div class="at-empty">
		{#if mode === "strategic"}
			No strategic allocation configured. Set allocation targets to begin.
		{:else if mode === "tactical"}
			No tactical tilts active.
		{:else}
			No effective allocation computed.
		{/if}
	</div>
{:else}
	<div class="at-wrapper">
		<table class="at-table">
			<thead>
				<tr>
					<th class="at-th at-th--block">Block</th>
					{#each profiles as profile (profile)}
						<th class="at-th at-th--value">{profileLabels[profile] ?? profile}</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each groupedData as group (group.geography)}
					<!-- L1 Geography group header -->
					<tr class="at-group-row">
						<td class="at-group-label" colspan={profiles.length + 1}>
							{group.geography}
						</td>
					</tr>
					<!-- L2 Asset Class rows -->
					{#each group.rows as row (row.block_id)}
						<tr class="at-data-row">
							<td class="at-cell at-cell--block">
								<span class="at-block-name">{row.display_name}</span>
								<span class="at-block-class">{row.asset_class}</span>
							</td>
							{#each profiles as profile (profile)}
								{@const val = row.values[profile]}
								<td
									class="at-cell at-cell--value {mode === 'tactical' ? tacticalColor(val) : ''}"
								>
									{formatValue(val, mode)}
								</td>
							{/each}
						</tr>
					{/each}
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.at-empty {
		padding: var(--netz-space-stack-xl, 48px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.at-wrapper {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
	}

	.at-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.at-th {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.at-th--value {
		text-align: right;
		min-width: 100px;
	}

	.at-th--block {
		min-width: 200px;
	}

	/* L1 Geography group header */
	.at-group-row {
		background: var(--netz-surface-alt);
	}

	.at-group-label {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		color: var(--netz-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid var(--netz-border-subtle);
		border-top: 1px solid var(--netz-border-subtle);
	}

	/* L2 data rows */
	.at-data-row {
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.at-data-row:last-child {
		border-bottom: none;
	}

	.at-cell {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		vertical-align: middle;
	}

	.at-cell--block {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.at-block-name {
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.at-block-class {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.at-cell--value {
		text-align: right;
		font-variant-numeric: tabular-nums;
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	/* Tactical colors */
	.at-val--positive {
		color: var(--netz-success);
	}

	.at-val--negative {
		color: var(--netz-danger);
	}

	@media (max-width: 640px) {
		.at-th--value {
			min-width: 70px;
		}
	}
</style>
