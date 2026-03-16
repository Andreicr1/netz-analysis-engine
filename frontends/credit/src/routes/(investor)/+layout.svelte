<!--
  Investor layout — InvestorShell with tenant branding, language toggle, sign out.
-->
<script lang="ts">
	import { InvestorShell } from "@netz/ui";
	import { goto } from "$app/navigation";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	let language = $state<"pt" | "en">("pt");

	function handleLanguageChange(lang: string) {
		language = lang as "pt" | "en";
	}

	function handleSignOut() {
		goto("/auth/sign-out");
	}
</script>

<InvestorShell
	orgName={data.branding.org_name}
	logoUrl={data.branding.logo_light_url}
	{language}
	onLanguageChange={handleLanguageChange}
	onSignOut={handleSignOut}
>
	{@render children()}
</InvestorShell>
