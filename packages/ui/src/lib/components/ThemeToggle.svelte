<!--
  @component ThemeToggle
  Sun/moon button — toggles data-theme between "light" and "dark".
  Updates the DOM immediately + writes netz-theme cookie for SSR persistence.
  No framework dependency: pure DOM + document.cookie.
-->
<script lang="ts">
	function getInitialTheme(): "light" | "dark" {
		if (typeof document !== "undefined") {
			const attr = document.documentElement.getAttribute("data-theme");
			if (attr === "light" || attr === "dark") return attr;
		}
		return "dark";
	}

	let theme = $state<"light" | "dark">(getInitialTheme());

	function toggle() {
		theme = theme === "dark" ? "light" : "dark";
		document.documentElement.setAttribute("data-theme", theme);
		// Persist across page loads (1-year expiry, SameSite=Lax)
		document.cookie = `netz-theme=${theme};max-age=31536000;path=/;SameSite=Lax`;
	}
</script>

<button
	type="button"
	onclick={toggle}
	aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
	title={theme === "dark" ? "Light mode" : "Dark mode"}
	class="theme-toggle"
>
	{#if theme === "dark"}
		<!-- Sun -->
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<circle cx="12" cy="12" r="4"/>
			<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
		</svg>
	{:else}
		<!-- Moon -->
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
		</svg>
	{/if}
</button>

<style>
	.theme-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: 1px solid var(--netz-border);
		border-radius: 6px;
		background: transparent;
		color: var(--netz-text-secondary);
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
		flex-shrink: 0;
	}

	.theme-toggle:hover {
		background: var(--netz-surface-alt);
		color: var(--netz-text-primary);
		border-color: var(--netz-brand-secondary);
	}

	.theme-toggle:focus-visible {
		outline: 2px solid var(--netz-brand-secondary);
		outline-offset: 2px;
	}
</style>
