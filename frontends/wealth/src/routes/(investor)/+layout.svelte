<!--
  Investor layout — InvestorShell with tenant branding, language toggle, sign out.
-->
<script lang="ts">
	import { InvestorShell } from "@netz/ui";
	import { goto } from "$app/navigation";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: import("svelte").Snippet } = $props();

	function getInitialLanguage(): "pt" | "en" {
		if (typeof localStorage !== 'undefined') {
			const saved = localStorage.getItem('netz-investor-language');
			if (saved === 'pt' || saved === 'en') return saved;
		}
		return 'pt';
	}

	let language = $state<"pt" | "en">(getInitialLanguage());

	$effect(() => {
		if (typeof localStorage !== 'undefined') {
			localStorage.setItem('netz-investor-language', language);
		}
	});

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
