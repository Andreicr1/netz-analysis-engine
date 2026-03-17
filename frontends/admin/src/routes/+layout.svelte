<!--
  Root layout — delegates to shared AppLayout with admin-specific nav items.
  TopNav uses text items (no icons). Sections: Health, Tenants, Config, Prompts.
-->
<script lang="ts">
	import "../app.css";
	import { AppLayout } from "@netz/ui";
	import type { NavItem } from "@netz/ui/utils";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	const navItems: NavItem[] = [
		{ label: "Health", href: "/health" },
		{ label: "Tenants", href: "/tenants" },
		{ label: "Config", href: "/config/liquid_funds" },
		{ label: "Prompts", href: "/prompts/private_credit" },
	];
</script>

<AppLayout
	{navItems}
	appName="Admin"
	branding={data.branding}
	token={data.token}
	{children}
/>
