<script lang="ts">
	import { MetricCard, PageHeader, SectionCard, StatusBadge } from "@netz/ui";
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

	function humanize(value: string) {
		return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Prompt workspace for {tenant?.org_name ?? data.orgId}" />
	<p class="mt-1 max-w-3xl text-sm text-(--netz-text-muted)">
		Prompt editing is centralized by vertical. This tenant page is the scoped index for the prompt workspaces that apply to it.
	</p>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
		<MetricCard label="Linked Verticals" value={String(verticals.length)} />
		<MetricCard label="Tenant Overrides" value={String(tenant?.configs?.length ?? 0)} />
	</div>

	<SectionCard title="Workspace map">
		<div class="space-y-4">
			{#each verticals as vertical (vertical)}
				<div class="rounded-xl border border-(--netz-border) bg-(--netz-surface-alt) p-4">
					<div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
						<div class="space-y-1">
							<p class="text-sm font-semibold text-(--netz-text-primary)">{humanize(vertical)}</p>
							<p class="text-sm text-(--netz-text-secondary)">
								Use the global prompt editor to manage templates for this tenant's {humanize(vertical)} workflows.
							</p>
						</div>
						<div class="flex items-center gap-3">
							<StatusBadge status="success" resolve={resolveAdminStatus} />
							<a href="/prompts/{vertical}" class="inline-flex h-8 items-center justify-center rounded-md border border-(--netz-border) bg-transparent px-3 text-xs font-medium text-(--netz-text-primary) transition-colors hover:bg-(--netz-surface-alt)">Open {humanize(vertical)} prompts</a>
						</div>
					</div>
				</div>
			{/each}
		</div>
	</SectionCard>

	<SectionCard title="Scope note">
		<p class="text-sm text-(--netz-text-secondary)">
			Tenant-scoped prompt changes are resolved through the vertical workspaces. This page exists to keep the tenant context visible while the editable surface stays centralized.
		</p>
	</SectionCard>
</div>




