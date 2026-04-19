<!--
  LibraryBreadcrumbs — reactive folder hierarchy header.

  Phase 3 of the Library frontend (spec §3.4 Fase 3). The breadcrumbs
  derive entirely from the encoded `selectedPath` prop — no internal
  state, no separate fetch — so they stay in lock-step with the URL
  adapter wherever it lives. Each segment is a button that emits an
  `onNavigate` callback with the cumulative encoded path so the
  parent shell can both push the URL and ask the tree-loader to
  expand the right folder.
-->
<script lang="ts">
	import ChevronRight from "lucide-svelte/icons/chevron-right";

	interface Props {
		selectedPath: string | null;
		onNavigate: (path: string | null) => void;
	}

	let { selectedPath, onNavigate }: Props = $props();

	interface Crumb {
		label: string;
		path: string;
	}

	const crumbs = $derived.by<Crumb[]>(() => {
		if (!selectedPath) return [];
		const segments = selectedPath.split("/").filter((s) => s.length > 0);
		const out: Crumb[] = [];
		for (let i = 0; i < segments.length; i += 1) {
			const path = segments.slice(0, i + 1).join("/");
			let label = segments[i]!;
			try {
				label = decodeURIComponent(label);
			} catch {
				// Leave the raw segment in place if decoding fails —
				// better than crashing the breadcrumb bar.
			}
			out.push({ label, path });
		}
		return out;
	});
</script>

<nav class="crumbs" aria-label="Library breadcrumbs">
	<button
		type="button"
		class="crumb crumb--root"
		onclick={() => onNavigate(null)}
	>
		Library
	</button>
	{#each crumbs as crumb, idx (crumb.path)}
		<span class="separator" aria-hidden="true">
			<ChevronRight size={12} />
		</span>
		<button
			type="button"
			class="crumb"
			class:crumb--leaf={idx === crumbs.length - 1}
			onclick={() => onNavigate(crumb.path)}
		>
			{crumb.label}
		</button>
	{/each}
</nav>

<style>
	.crumbs {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 14px 24px;
		background: #141519;
		border-bottom: 1px solid #404249;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		font-size: 13px;
		color: #85a0bd;
		flex-wrap: wrap;
	}

	.crumb {
		background: none;
		border: none;
		color: #85a0bd;
		font-family: inherit;
		font-size: inherit;
		font-weight: 500;
		cursor: pointer;
		padding: 4px 6px;
		border-radius: 4px;
		transition: color 120ms ease, background-color 120ms ease;
	}

	.crumb:hover {
		color: #ffffff;
		background: #1d1f25;
	}

	.crumb:focus-visible {
		outline: 2px solid #0177fb;
		outline-offset: 1px;
	}

	.crumb--root { color: #cbccd1; }

	.crumb--leaf {
		color: #ffffff;
		font-weight: 600;
	}

	.separator {
		display: inline-flex;
		align-items: center;
		color: #404249;
	}
</style>
