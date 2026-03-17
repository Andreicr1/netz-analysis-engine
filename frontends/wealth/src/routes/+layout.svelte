<!--
  Root layout — delegates to shared AppLayout with wealth-specific nav items.
-->
<script lang="ts">
	import "../app.css";
	import { AppLayout } from "@netz/ui";
	import type { NavItem } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	const navItems: NavItem[] = [
		{ label: "Dashboard", href: "/dashboard", icon: "\u{1F4CA}" },
		{ label: "Funds", href: "/funds", icon: "\u{1F4B0}" },
		{ label: "Model Portfolios", href: "/model-portfolios", icon: "\u{1F3AF}" },
		{ label: "Allocation", href: "/allocation", icon: "\u{1F4CA}" },
		{ label: "Risk", href: "/risk", icon: "\u{1F6E1}" },
		{ label: "Analytics", href: "/analytics", icon: "\u{1F52C}" },
		{ label: "Macro", href: "/macro", icon: "\u{1F30D}" },
		{ label: "Content", href: "/content", icon: "\u{1F4DD}" },
		{ label: "DD Reports", href: "/dd-reports", icon: "\u{1F4CB}" },
	];
</script>

<AppLayout
	{navItems}
	appName="Netz Wealth"
	branding={data.branding}
	token={data.token}
	{children}
/>
