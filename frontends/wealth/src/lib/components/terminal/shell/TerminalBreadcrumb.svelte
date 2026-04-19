<!--
	TerminalBreadcrumb.svelte
	=========================

	28px persistent row rendered BETWEEN TerminalTopNav and LayoutCage.
	Segments: Screener → Terminal → Macro → Builder. Each is an <a>
	with SvelteKit preload. Active segment matches page.route.id.

	Keyboard: Alt+1..4 jumps to each segment. Ignored when focus is in
	an editable field. Namespace does not collide with CommandPalette
	go-to sequences (g-prefix) or palette shortcut (Cmd+K).

	Source: docs/plans/2026-04-18-netz-terminal-parity.md §A.4, §C.1.
-->
<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";

	interface Segment {
		key: string;
		label: string;
		href: string;
		/** Path prefix used to resolve the active state against page.route.id. */
		match: string;
	}

	const segments: Segment[] = [
		{ key: "screener", label: "SCREENER", href: "/screener", match: "/screener" },
		{ key: "terminal", label: "TERMINAL", href: "/live", match: "/live" },
		{ key: "macro", label: "MACRO", href: "/macro", match: "/macro" },
		{ key: "builder", label: "BUILDER", href: "/portfolio/builder", match: "/portfolio/builder" },
	];

	const activeKey = $derived.by(() => {
		const path = page.url.pathname;
		for (const seg of segments) {
			if (path.startsWith(seg.match)) return seg.key;
		}
		return null;
	});

	function isEditableTarget(target: EventTarget | null): boolean {
		if (!(target instanceof HTMLElement)) return false;
		const tag = target.tagName;
		if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
		if (target.isContentEditable) return true;
		const role = target.getAttribute("role");
		if (role === "textbox" || role === "searchbox" || role === "combobox") {
			return true;
		}
		return false;
	}

	$effect(() => {
		if (typeof window === "undefined") return;
		const handler = (event: KeyboardEvent) => {
			if (!event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return;
			if (isEditableTarget(event.target)) return;
			const idx = Number.parseInt(event.key, 10);
			if (Number.isNaN(idx) || idx < 1 || idx > segments.length) return;
			event.preventDefault();
			const target = segments[idx - 1];
			if (!target) return;
			// Route hrefs are string-typed here (mapped from segments[]),
			// so resolve() type inference narrows to never. Cast keeps
			// the runtime behavior identical and svelte-check quiet.
			void goto(target.href as Parameters<typeof goto>[0]);
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	});
</script>

<nav class="tb-crumb" aria-label="Terminal sections">
	{#each segments as seg, i (seg.key)}
		{#if i > 0}
			<span class="tb-sep" aria-hidden="true">›</span>
		{/if}
		<a
			class="tb-link"
			class:is-active={activeKey === seg.key}
			href={seg.href}
			data-sveltekit-preload-data="hover"
			aria-current={activeKey === seg.key ? "page" : undefined}
		>
			<span class="tb-alt" aria-hidden="true">{i + 1}</span>
			<span class="tb-label">{seg.label}</span>
		</a>
	{/each}
</nav>

<style>
	.tb-crumb {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-3);
		height: var(--terminal-shell-breadcrumb-height, 28px);
		padding: 0 var(--terminal-space-4);
		background: var(--terminal-bg-panel);
		border-bottom: var(--terminal-border-hairline);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
		overflow: hidden;
		white-space: nowrap;
	}

	.tb-link {
		display: inline-flex;
		align-items: center;
		gap: var(--terminal-space-1);
		color: var(--terminal-fg-tertiary);
		text-transform: uppercase;
		text-decoration: none;
		padding: 0 var(--terminal-space-2);
		height: 100%;
		transition: color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.tb-link:hover {
		color: var(--terminal-fg-primary);
	}
	.tb-link.is-active {
		color: var(--terminal-accent-amber);
		border-bottom: 1px solid var(--terminal-accent-amber);
	}
	.tb-link:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.tb-alt {
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-10);
		font-variant-numeric: tabular-nums;
	}
	.tb-link.is-active .tb-alt {
		color: var(--terminal-accent-amber-dim);
	}

	.tb-sep {
		color: var(--terminal-fg-muted);
	}
</style>
