<script lang="ts">
	import { MetricCard, SectionCard, StatusBadge } from "@netz/ui";
	import { resolveAdminStatus } from "$lib/utils/status-maps.js";
	import type { TenantDetail } from "$lib/types";

type PageData = {
  tenant: TenantDetail | null;
  orgId: string;
};

	let { data }: { data: PageData } = $props();
	const tenant = $derived(data.tenant);
	const supportedVerticals = ["liquid_funds", "private_credit"];
	const verticals = $derived(
		Array.from(
			new Set(
				(tenant?.configs ?? []).map((config) => config.vertical).filter((vertical): vertical is string => Boolean(vertical)),
			),
		).length > 0
			? Array.from(
					new Set(
						(tenant?.configs ?? []).map((config) => config.vertical).filter((vertical): vertical is string => Boolean(vertical)),
					),
				)
			: supportedVerticals,
	);

	const groupedConfigs = $derived(
		verticals.map((vertical) => ({
			vertical,
			configs: (tenant?.configs ?? []).filter((config) => config.vertical === vertical),
		})),
	);

	function humanize(value: string) {
		return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
	}
</script>

<div class="space-y-6 p-6">
	<div class="space-y-2">
		<p class="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--netz-text-muted)]">Tenant config</p>
		<h2 class="text-2xl font-bold text-[var(--netz-text-primary)]">Configuration workspace for {tenant?.org_name ?? data.orgId}</h2>
		<p class="max-w-3xl text-sm text-[var(--netz-text-secondary)]">
			This page is the tenant-scoped index for config overrides. Open the vertical workspace to edit the active config, review diffs, and check what currently overrides the global default.
		</p>
	</div>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<MetricCard label="Override Count" value={String(tenant?.configs?.length ?? 0)} />
		<MetricCard label="Supported Verticals" value={String(verticals.length)} />
	</div>

	<SectionCard title="Workspace map">
		<div class="space-y-4">
			{#each groupedConfigs as group}
				<div class="rounded-xl border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4">
					<div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
						<div class="space-y-1">
							<p class="text-sm font-semibold text-[var(--netz-text-primary)]">{humanize(group.vertical)}</p>
							<p class="text-sm text-[var(--netz-text-secondary)]">
								{group.configs.length} override{group.configs.length === 1 ? "" : "s"} available for this tenant.
							</p>
						</div>
						<a href="/config/{group.vertical}" class="inline-flex h-8 items-center justify-center rounded-md border border-[var(--netz-border)] bg-transparent px-3 text-xs font-medium text-[var(--netz-text-primary)] transition-colors hover:bg-[var(--netz-surface-alt)]">Open {humanize(group.vertical)} workspace</a>
					</div>

					<div class="mt-4 grid gap-3 sm:grid-cols-2">
						{#if group.configs.length > 0}
							{#each group.configs as config}
								<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3">
									<div class="flex items-start justify-between gap-3">
										<div>
											<p class="text-sm font-medium text-[var(--netz-text-primary)]">{config.config_type}</p>
											<p class="text-xs text-[var(--netz-text-secondary)]">Version {config.version ?? "\u2014"}</p>
										</div>
										<StatusBadge status={config.has_override ? "warning" : "success"} resolve={resolveAdminStatus} />
									</div>
								</div>
							{/each}
						{:else}
							<p class="text-sm text-[var(--netz-text-muted)]">
								No overrides are stored yet. Open the vertical workspace to create the first tenant-specific values.
							</p>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</SectionCard>

	<SectionCard title="Replacement warning">
		<div class="space-y-3 text-sm text-[var(--netz-text-secondary)]">
			<p>
				Config changes are centralized. This tenant page only points you at the authoritative vertical editor.
			</p>
			<p>
				Use the setup surface when you need to seed or replace default tenant overrides. Existing overrides stay untouched unless you explicitly choose to replace them.
			</p>
		</div>
	</SectionCard>
</div>




