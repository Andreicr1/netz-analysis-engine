<!-- Top 50 Advisers by AUM — compact table widget (F-01) -->
<script lang="ts">
	import { formatCompact } from "@netz/ui/utils";
	import type { SecManagerSearchPage } from "$lib/types/sec-analysis";

	let {
		api,
		onSelect,
	}: {
		api: { get: <T>(url: string, params?: Record<string, string>) => Promise<T> };
		onSelect?: (cik: string, name: string) => void;
	} = $props();

	let data = $state<SecManagerSearchPage | null>(null);
	let loading = $state(true);
	let error = $state(false);

	async function load() {
		loading = true;
		error = false;
		try {
			data = await api.get<SecManagerSearchPage>("/sec/managers/search", {
				entity_type: "Registered",
				sort_by: "aum_total",
				sort_dir: "desc",
				page_size: "50",
			});
		} catch {
			error = true;
			data = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});
</script>

<div class="ta-widget">
	<div class="ta-header">
		<span class="ta-title">Top 50 Registered Advisers by AUM</span>
		<span class="ta-subtitle">{data ? `${data.total_count.toLocaleString()} total registered` : ""}</span>
	</div>

	{#if loading}
		<div class="ta-loading">Loading advisers...</div>
	{:else if error || !data}
		<div class="ta-error">Failed to load advisers.</div>
	{:else if data.managers.length === 0}
		<div class="ta-empty">No registered advisers found.</div>
	{:else}
		<div class="ta-table-wrap">
			<table class="ta-table">
				<thead>
					<tr>
						<th class="ta-th ta-th--rank">#</th>
						<th class="ta-th">Firm Name</th>
						<th class="ta-th ta-th--right">AUM</th>
						<th class="ta-th ta-th--right">State</th>
					</tr>
				</thead>
				<tbody>
					{#each data.managers as mgr, i (mgr.crd_number)}
						<tr
							class="ta-row"
							onclick={() => onSelect?.(mgr.cik ?? "", mgr.firm_name)}
							role="button"
							tabindex="0"
							onkeydown={(e) => {
								if (e.key === "Enter") onSelect?.(mgr.cik ?? "", mgr.firm_name);
							}}
						>
							<td class="ta-td ta-td--rank">{i + 1}</td>
							<td class="ta-td ta-td--name">{mgr.firm_name}</td>
							<td class="ta-td ta-td--right">
								{mgr.aum_total != null ? formatCompact(mgr.aum_total) : "\u2014"}
							</td>
							<td class="ta-td ta-td--right ta-td--state">{mgr.state ?? "\u2014"}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<style>
	.ta-widget {
		border: 1px solid var(--netz-border-subtle);
		border-radius: 12px;
		background: var(--netz-surface-secondary);
		overflow: hidden;
	}

	.ta-header {
		display: flex;
		align-items: baseline;
		gap: 12px;
		padding: 16px 20px 12px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.ta-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--netz-text-primary);
	}

	.ta-subtitle {
		font-size: 12px;
		color: var(--netz-text-muted);
	}

	.ta-loading,
	.ta-error,
	.ta-empty {
		padding: 24px 20px;
		font-size: 13px;
		color: var(--netz-text-muted);
	}

	.ta-error {
		color: var(--netz-color-error, #ef4444);
	}

	.ta-table-wrap {
		max-height: 420px;
		overflow-y: auto;
	}

	.ta-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.ta-th {
		position: sticky;
		top: 0;
		padding: 8px 12px;
		text-align: left;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		background: var(--netz-surface-secondary);
		border-bottom: 1px solid var(--netz-border-subtle);
		white-space: nowrap;
		z-index: 1;
	}

	.ta-th--rank {
		width: 40px;
		text-align: center;
	}

	.ta-th--right {
		text-align: right;
	}

	.ta-row {
		cursor: pointer;
		transition: background 0.1s;
	}

	.ta-row:hover {
		background: var(--netz-surface-alt);
	}

	.ta-td {
		padding: 6px 12px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.ta-td--rank {
		text-align: center;
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.ta-td--name {
		font-weight: 500;
		max-width: 300px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.ta-td--right {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.ta-td--state {
		color: var(--netz-text-secondary);
	}
</style>
