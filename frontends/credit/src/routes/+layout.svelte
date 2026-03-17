<!--
  Root layout — delegates to shared AppLayout with credit-specific nav items.
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
		{ label: "Pipeline", href: "/pipeline" },
		{ label: "Portfolio", href: "/portfolio" },
		{ label: "Documents", href: "/documents" },
		{ label: "Reporting", href: "/reporting" },
		{ label: "Copilot", href: "/copilot" },
	];
</script>

<AppLayout
	{navItems}
	appName="Netz Credit"
	branding={data.branding}
	token={data.token}
	contextNav={contextNavState.current}
	{children}
/>
