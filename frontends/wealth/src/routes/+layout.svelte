<!--
  Root layout — delegates to shared AppLayout with wealth-specific nav items.
  TopNav uses text items (no icons). Nav items reduced from 12 to 7 (Phase 3 consolidation).
-->
<script lang="ts">
	import "../app.css";
	import { AppLayout } from "@netz/ui";
	import type { NavItem } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";
	import { initContextNav } from "$lib/state/context-nav.svelte";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	const contextNavState = initContextNav();

	const navItems: NavItem[] = [
		{ label: "Dashboard", href: "/dashboard" },
		{ label: "Screener", href: "/screener" },
		{ label: "Portfolios", href: "/model-portfolios" },
		{ label: "Risk", href: "/risk" },
		{ label: "Analytics", href: "/analytics" },
		{ label: "Documents", href: "/documents" },
		{ label: "Macro", href: "/macro" },
		{ label: "Content", href: "/content" },
		{ label: "ESMA", href: "/esma" },
	];
</script>

<AppLayout
	{navItems}
	appName="Wealth OS"
	branding={data.branding}
	token={data.token}
	contextNav={contextNavState.current ?? undefined}
	{children}
/>
