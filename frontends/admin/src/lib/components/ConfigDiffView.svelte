<!--
  ConfigDiffView — CodeMirror merge view for config diff (default vs override).
  Uses @codemirror/merge for split/unified side-by-side rendering.
  Takes a ConfigDiffOut payload from the API.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { SectionCard } from "@netz/ui";

	/** Mirrors components["schemas"]["ConfigDiffOut"] from packages/ui/src/types/api.d.ts */
	export interface ConfigDiffOut {
		vertical: string;
		config_type: string;
		org_id?: string | null;
		default: Record<string, unknown>;
		override?: Record<string, unknown> | null;
		merged: Record<string, unknown>;
		changed_keys: string[];
		tenant_count_affected: number;
		has_override: boolean;
		computed_at: string;
	}

	interface Props {
		diff: ConfigDiffOut;
		class?: string;
	}

	let { diff, class: className }: Props = $props();

	let mergeHost: HTMLDivElement | undefined;
	let viewMode = $state<"split" | "unified">("split");
	let mergeView: { destroy: () => void } | undefined;

	// Summary text: count changed keys
	const summaryText = $derived(
		diff.changed_keys.length === 0
			? "No properties changed"
			: diff.changed_keys.length === 1
				? "1 property changed"
				: `${diff.changed_keys.length} properties changed`,
	);

	const beforeDoc = $derived(JSON.stringify(diff.default, null, 2));
	const afterDoc = $derived(JSON.stringify(diff.override ?? diff.default, null, 2));
	const hasOverride = $derived(diff.override !== null && diff.override !== undefined);

	function buildMergeTheme(EditorView: typeof import("@codemirror/view").EditorView) {
		return EditorView.theme({
			"&": {
				backgroundColor: "var(--netz-surface)",
				color: "var(--netz-text-primary)",
				fontSize: "12px",
				fontFamily:
					"ui-monospace, SFMono-Regular, SF Mono, Consolas, Liberation Mono, monospace",
			},
			".cm-gutters": {
				backgroundColor: "var(--netz-surface-alt)",
				color: "var(--netz-text-secondary)",
				borderRight: "1px solid var(--netz-border)",
			},
			".cm-deletedChunk .cm-deletedLine": {
				backgroundColor: "color-mix(in srgb, var(--netz-danger) 12%, transparent)",
			},
			".cm-insertedChunk .cm-insertedLine": {
				backgroundColor: "color-mix(in srgb, var(--netz-success) 12%, transparent)",
			},
			".cm-changedText": {
				backgroundColor: "color-mix(in srgb, var(--netz-warning) 20%, transparent)",
			},
			".cm-mergeGutter": {
				backgroundColor: "var(--netz-surface-alt)",
			},
		});
	}

	async function mountView(mode: "split" | "unified") {
		if (!mergeHost) return;

		// Destroy previous view if any
		if (mergeView) {
			mergeView.destroy();
			mergeView = undefined;
		}

		mergeHost.innerHTML = "";

		const [{ EditorState }, { EditorView }, { MergeView, unifiedMergeView }, { json }] =
			await Promise.all([
				import("@codemirror/state"),
				import("@codemirror/view"),
				import("@codemirror/merge"),
				import("@codemirror/lang-json"),
			]);

		const theme = buildMergeTheme(EditorView);
		const sharedExtensions = [json(), theme, EditorState.readOnly.of(true), EditorView.lineWrapping];

		if (mode === "unified") {
			const view = new EditorView({
				doc: afterDoc,
				extensions: [
					...sharedExtensions,
					unifiedMergeView({
						original: beforeDoc,
						collapseUnchanged: { margin: 3, minSize: 4 },
					}),
				],
				parent: mergeHost,
			});
			mergeView = view;
		} else {
			const view = new MergeView({
				a: {
					doc: beforeDoc,
					extensions: [...sharedExtensions],
				},
				b: {
					doc: afterDoc,
					extensions: [...sharedExtensions],
				},
				parent: mergeHost,
				collapseUnchanged: { margin: 3, minSize: 4 },
			});
			mergeView = view;
		}
	}

	$effect(() => {
		const _mode = viewMode;
		const _before = beforeDoc;
		const _after = afterDoc;
		if (mergeHost) {
			void mountView(_mode);
		}
	});

	onMount(() => {
		return () => {
			if (mergeView) {
				mergeView.destroy();
				mergeView = undefined;
			}
		};
	});
</script>

<SectionCard title="Diff — {diff.config_type}" class={className}>
	<div class="space-y-4">
		<!-- Summary + toggle row -->
		<div class="flex items-center justify-between">
			<div class="space-y-1">
				<p
					class="text-sm font-medium {diff.changed_keys.length > 0
						? 'text-(--netz-text-primary)'
						: 'text-(--netz-text-secondary)'}"
				>
					{summaryText}
				</p>
				{#if diff.changed_keys.length > 0}
					<div class="flex flex-wrap gap-1">
						{#each diff.changed_keys as key}
							<span
								class="rounded-full border border-(--netz-border) bg-(--netz-surface-alt) px-2 py-0.5 font-mono text-xs text-(--netz-text-secondary)"
							>
								{key}
							</span>
						{/each}
					</div>
				{/if}
			</div>

			<div class="flex shrink-0 gap-1 rounded-md border border-(--netz-border) p-0.5">
				<button
					onclick={() => (viewMode = "split")}
					class="rounded px-3 py-1 text-xs font-medium transition-colors {viewMode === 'split'
						? 'bg-(--netz-brand-primary) text-white'
						: 'text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)'}"
				>
					Split
				</button>
				<button
					onclick={() => (viewMode = "unified")}
					class="rounded px-3 py-1 text-xs font-medium transition-colors {viewMode === 'unified'
						? 'bg-(--netz-brand-primary) text-white'
						: 'text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)'}"
				>
					Unified
				</button>
			</div>
		</div>

		<!-- Column headers for split view -->
		{#if viewMode === "split"}
			<div class="grid grid-cols-2 gap-px">
				<p class="text-xs font-medium uppercase tracking-[0.14em] text-(--netz-text-secondary)">
					Default
				</p>
				<p class="text-xs font-medium uppercase tracking-[0.14em] text-(--netz-text-secondary)">
					{hasOverride ? "Override" : "No override — showing default"}
				</p>
			</div>
		{/if}

		<!-- Merge view host -->
		<div
			bind:this={mergeHost}
			class="overflow-hidden rounded-xl border border-(--netz-border) bg-(--netz-surface)"
			style="min-height: 200px;"
			aria-label="Config diff viewer"
		></div>
	</div>
</SectionCard>
