<!--
  ThemeToggle — light/dark switcher, pill button matching the
  wealth topbar control style (Bell / Cpu). Writes `ii-theme`
  to localStorage AND `ii-theme=` cookie so the FOUC script in
  `static/theme-init.js` honors the choice on the next load.

  Wealth is dark-first; the toggle exists so institutional users
  can flip to light mode for printing / projectors and back.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { Sun, Moon } from "lucide-svelte";

	let theme = $state<"light" | "dark">("dark");

	onMount(() => {
		const attr = document.documentElement.getAttribute("data-theme");
		theme = attr === "light" ? "light" : "dark";
	});

	function toggle() {
		theme = theme === "dark" ? "light" : "dark";
		document.documentElement.setAttribute("data-theme", theme);
		try {
			localStorage.setItem("ii-theme", theme);
		} catch {
			// Ignore storage quota / private-mode failures.
		}
		document.cookie = `ii-theme=${theme};max-age=31536000;path=/;SameSite=Lax`;
	}
</script>

<button
	type="button"
	onclick={toggle}
	aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
	title={theme === "dark" ? "Light mode" : "Dark mode"}
	class="rounded-full bg-[var(--ii-surface-elevated)] hover:bg-[var(--ii-surface-raised)] p-2.5 flex items-center justify-center transition-colors border border-[var(--ii-border-subtle)] text-[var(--ii-text-primary)]"
>
	{#if theme === "dark"}
		<Sun size={18} />
	{:else}
		<Moon size={18} />
	{/if}
</button>
