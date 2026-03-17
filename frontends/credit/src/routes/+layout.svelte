<!--
  Root layout — delegates to shared AppLayout with credit-specific nav items.
-->
<script lang="ts">
	import "../app.css";
	import { AppLayout } from "@netz/ui";
	import type { NavItem } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	const navItems: NavItem[] = [
		{ label: "Dashboard", href: "/dashboard", icon: "\u{1F4CA}" },
		{ label: "Pipeline", href: "/pipeline", icon: "\u{1F4C8}" },
		{ label: "Portfolio", href: "/portfolio", icon: "\u{1F4BC}" },
		{ label: "Documents", href: "/documents", icon: "\u{1F4C4}" },
		{ label: "Reporting", href: "/reporting", icon: "\u{1F4D1}" },
		{ label: "Copilot", href: "/copilot", icon: "\u{1F916}" },
	];
</script>

<AppLayout
	{navItems}
	appName="Netz Credit"
	branding={data.branding}
	token={data.token}
	{children}
/>
