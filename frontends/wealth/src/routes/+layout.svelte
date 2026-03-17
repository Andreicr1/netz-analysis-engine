<!--
  Root layout — delegates to shared AppLayout with wealth-specific nav items.
  TopNav uses text items (no icons). Nav items match Figma design sections.
-->
<script lang="ts">
	import "../app.css";
	import { AppLayout } from "@netz/ui";
	import type { NavItem } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	const navItems: NavItem[] = [
		{ label: "Dashboard", href: "/dashboard" },
		{ label: "Portfolios", href: "/model-portfolios" },
		{ label: "Risk", href: "/risk" },
		{ label: "Funds", href: "/funds" },
		{ label: "Screener", href: "/screener" },
		{ label: "Analytics", href: "/analytics" },
		{ label: "Exposure", href: "/exposure" },
		{ label: "Allocation", href: "/allocation" },
		{ label: "Macro", href: "/macro" },
	];
</script>

<AppLayout
	{navItems}
	appName="Wealth OS"
	branding={data.branding}
	token={data.token}
	{children}
/>
