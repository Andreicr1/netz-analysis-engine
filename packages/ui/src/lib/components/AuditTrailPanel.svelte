<script lang="ts">
	import Card from "./Card.svelte";
	import Button from "./Button.svelte";
	import { cn } from "../utils/cn.js";
	import { formatDate, formatDateTime } from "../utils/format.js";
	import type { Snippet } from "svelte";

	export type AuditTrailStatus = "success" | "warning" | "error" | "info" | "pending";

	export interface AuditTrailFieldChange {
		field: string;
		from?: string | null;
		to?: string | null;
	}

	export interface AuditTrailEntry {
		id?: string;
		actor: string;
		actorCapacity?: string;
		actorEmail?: string;
		timestamp: string | number | Date;
		action: string;
		scope: string;
		rationale?: string;
		outcome: string;
		status?: AuditTrailStatus;
		immutable?: boolean;
		sourceSystem?: string;
		changedFields?: AuditTrailFieldChange[];
	}

	interface RenderedAuditTrailEntry {
		entry: AuditTrailEntry;
		key: string;
		groupLabel: string | null;
		timestampLabel: string;
		datetimeValue: string;
	}

	interface Props {
		/**
		 * Audit trail entries. In parent components, declare this with $state.raw([...]) instead
		 * of $state([...]) — entries are replaced wholesale, not mutated in-place, so deep
		 * reactivity tracking is unnecessary overhead.
		 */
		entries?: AuditTrailEntry[];
		title?: string;
		description?: string;
		emptyMessage?: string;
		maxVisible?: number;
		class?: string;
		/** Domain-specific entry renderer. When provided, renders inside each entry li instead of the default layout. */
		entryRenderer?: Snippet<[AuditTrailEntry]>;
	}

	let {
		entries = [],
		title = "Audit trail",
		description = "Visible post-mutation record for consequential actions.",
		emptyMessage = "No audit events are available yet.",
		maxVisible = 50,
		class: className,
		entryRenderer,
	}: Props = $props();

	let showAll = $state(false);

	const statusStyles: Record<AuditTrailStatus, string> = {
		success: "bg-emerald-50 text-emerald-700 border-emerald-200",
		warning: "bg-amber-50 text-amber-700 border-amber-200",
		error: "bg-rose-50 text-rose-700 border-rose-200",
		info: "bg-slate-100 text-slate-700 border-slate-200",
		pending: "bg-blue-50 text-blue-700 border-blue-200",
	};

	const locale = Intl.DateTimeFormat().resolvedOptions().locale || "en-US";
	const millisecondsPerDay = 24 * 60 * 60 * 1000;

	function resolveMaxVisible(value: number): number {
		return Number.isFinite(value) && value > 0 ? Math.floor(value) : 50;
	}

	function toDate(value: AuditTrailEntry["timestamp"]): Date | null {
		const date = value instanceof Date ? value : new Date(value);
		return Number.isNaN(date.getTime()) ? null : date;
	}

	function toStartOfDay(value: Date): number {
		return new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
	}

	function getTitleId(value: string): string {
		const slug = value
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, "-")
			.replace(/^-+|-+$/g, "");

		return `audit-trail-panel-${slug || "title"}`;
	}

	function formatDateGroup(date: Date): string {
		const today = new Date();
		const delta = Math.round((toStartOfDay(today) - toStartOfDay(date)) / millisecondsPerDay);

		if (delta === 0) {
			return "Today";
		}

		if (delta === 1) {
			return "Yesterday";
		}

		return formatDate(date, "medium", locale);
	}

	function getHiddenEntryCount(source: AuditTrailEntry[], expanded: boolean, limit: number): number {
		if (expanded) {
			return 0;
		}

		return Math.max(0, source.length - resolveMaxVisible(limit));
	}

	function getVisibleEntries(
		source: AuditTrailEntry[],
		expanded: boolean,
		limit: number,
	): RenderedAuditTrailEntry[] {
		const safeMaxVisible = resolveMaxVisible(limit);
		const startIndex = expanded || source.length <= safeMaxVisible ? 0 : source.length - safeMaxVisible;
		const visibleEntries = source.slice(startIndex);
		const showDateGroups = source.length > 3;
		let previousGroupLabel: string | null = null;

		return visibleEntries.map((entry, index) => {
			const date = toDate(entry.timestamp);
			const dateGroup = date ? formatDateGroup(date) : null;
			const nextGroupLabel =
				showDateGroups && dateGroup && dateGroup !== previousGroupLabel ? dateGroup : null;

			previousGroupLabel = dateGroup;

			return {
				entry,
				key: entry.id ?? `${entry.action}-${entry.actor}-${startIndex + index}`,
				groupLabel: nextGroupLabel,
				timestampLabel: date ? formatDateTime(date, locale) : String(entry.timestamp),
				datetimeValue: date ? date.toISOString() : String(entry.timestamp),
			};
		});
	}
</script>

<Card class={cn("p-5", className)}>
	<div class="space-y-5">
		<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
			<div class="space-y-1">
				<h2 id={getTitleId(title)} class="text-lg font-semibold text-[var(--netz-text-primary)]">
					{title}
				</h2>
				<p class="text-sm text-[var(--netz-text-secondary)]">{description}</p>
			</div>

			{#if getHiddenEntryCount(entries, showAll, maxVisible) > 0}
				<Button variant="ghost" size="sm" type="button" onclick={() => (showAll = true)}>
					Load earlier entries ({getHiddenEntryCount(entries, showAll, maxVisible)})
				</Button>
			{/if}
		</div>

		{#if entries.length === 0}
			<div class="rounded-lg border border-dashed border-[var(--netz-border)] p-4 text-sm text-[var(--netz-text-secondary)]">
				{emptyMessage}
			</div>
		{:else}
			<ul
				class="space-y-4"
				role="log"
				aria-labelledby={getTitleId(title)}
				aria-live="polite"
				aria-atomic="false"
			>
				{#each getVisibleEntries(entries, showAll, maxVisible) as row (row.key)}
					{#if row.groupLabel}
						<li class="pt-2">
							<h3
								class="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--netz-text-secondary)]"
							>
								{row.groupLabel}
							</h3>
						</li>
					{/if}

					<li class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] p-4">
						{#if entryRenderer}
							{@render entryRenderer(row.entry)}
						{:else}
						<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
							<div class="space-y-1">
								<p class="text-sm font-semibold text-[var(--netz-text-primary)]">
									{row.entry.action}
								</p>
								<p class="text-sm text-[var(--netz-text-secondary)]">{row.entry.scope}</p>
							</div>

							<div class="flex flex-wrap items-center justify-start gap-2 sm:justify-end">
								{#if row.entry.immutable}
									<span
										class="inline-flex w-fit items-center rounded-full border border-[var(--netz-border)] bg-[var(--netz-surface)] px-2.5 py-1 text-xs font-medium text-[var(--netz-text-secondary)]"
									>
										Immutable
									</span>
								{/if}

								<span
									class={cn(
										"inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-xs font-medium",
										statusStyles[row.entry.status ?? "info"],
									)}
								>
									{row.entry.outcome}
								</span>
							</div>
						</div>

						<dl class="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
							<div>
								<dt class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
									Actor
								</dt>
								<dd class="mt-1 text-[var(--netz-text-primary)]">{row.entry.actor}</dd>
							</div>

							{#if row.entry.actorCapacity}
								<div>
									<dt class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
										Capacity
									</dt>
									<dd class="mt-1 text-[var(--netz-text-primary)]">{row.entry.actorCapacity}</dd>
								</div>
							{/if}

							{#if row.entry.actorEmail}
								<div>
									<dt class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
										Actor email
									</dt>
									<dd class="mt-1 text-[var(--netz-text-primary)]">{row.entry.actorEmail}</dd>
								</div>
							{/if}

							<div>
								<dt class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
									Timestamp
								</dt>
								<dd class="mt-1 text-[var(--netz-text-primary)]">
									<time datetime={row.datetimeValue}>{row.timestampLabel}</time>
								</dd>
							</div>

							{#if row.entry.sourceSystem}
								<div>
									<dt class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
										Source system
									</dt>
									<dd class="mt-1 text-[var(--netz-text-primary)]">{row.entry.sourceSystem}</dd>
								</div>
							{/if}
						</dl>

						{#if row.entry.rationale}
							<div class="mt-4 rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3">
								<p class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
									Rationale
								</p>
								<p class="mt-2 text-sm leading-6 text-[var(--netz-text-primary)]">
									{row.entry.rationale}
								</p>
							</div>
						{/if}

						{#if row.entry.changedFields && row.entry.changedFields.length > 0}
							<div class="mt-4 space-y-3">
								<p class="text-xs font-medium uppercase tracking-[0.14em] text-[var(--netz-text-secondary)]">
									Changed fields
								</p>
								<ul class="space-y-2">
									{#each row.entry.changedFields as change}
										<li class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface)] p-3">
											<p class="text-sm font-medium text-[var(--netz-text-primary)]">{change.field}</p>
											<div class="mt-2 grid gap-2 text-sm sm:grid-cols-2">
												<div>
													<p class="text-xs uppercase tracking-[0.12em] text-[var(--netz-text-secondary)]">
														From
													</p>
													<p class="mt-1 text-[var(--netz-text-primary)]">{change.from ?? "Not set"}</p>
												</div>
												<div>
													<p class="text-xs uppercase tracking-[0.12em] text-[var(--netz-text-secondary)]">
														To
													</p>
													<p class="mt-1 text-[var(--netz-text-primary)]">{change.to ?? "Not set"}</p>
												</div>
											</div>
										</li>
									{/each}
								</ul>
							</div>
						{/if}
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</Card>
