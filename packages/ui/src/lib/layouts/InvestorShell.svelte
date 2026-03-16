<!--
  @component InvestorShell
  Minimal layout for investor portal: top bar (logo + org + language toggle + sign out), main content, footer.
-->
<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	let {
		orgName = "",
		logoUrl = null,
		onSignOut,
		onLanguageChange,
		language = "pt",
		class: className,
		children,
	}: {
		orgName?: string;
		logoUrl?: string | null;
		onSignOut?: () => void;
		onLanguageChange?: (lang: string) => void;
		language?: "pt" | "en";
		class?: string;
		children?: Snippet;
	} = $props();

	let currentYear = $derived(new Date().getFullYear());

	function toggleLanguage() {
		const next = language === "pt" ? "en" : "pt";
		onLanguageChange?.(next);
	}
</script>

<div class={cn("netz-investor-shell", className)}>
	<header class="netz-investor-shell__topbar">
		<div class="netz-investor-shell__brand">
			{#if logoUrl}
				<img
					src={logoUrl}
					alt={orgName ? `${orgName} logo` : "Logo"}
					class="netz-investor-shell__logo"
				/>
			{/if}
			{#if orgName}
				<span class="netz-investor-shell__org-name">{orgName}</span>
			{/if}
		</div>

		<div class="netz-investor-shell__actions">
			{#if onLanguageChange}
				<button
					class="netz-investor-shell__lang-toggle"
					onclick={toggleLanguage}
					type="button"
					aria-label={language === "pt" ? "Switch to English" : "Mudar para Portugues"}
				>
					{language === "pt" ? "EN" : "PT"}
				</button>
			{/if}

			{#if onSignOut}
				<button
					class="netz-investor-shell__sign-out"
					onclick={onSignOut}
					type="button"
				>
					{language === "pt" ? "Sair" : "Sign out"}
				</button>
			{/if}
		</div>
	</header>

	<main class="netz-investor-shell__main">
		{@render children?.()}
	</main>

	<footer class="netz-investor-shell__footer">
		<span>{orgName ? orgName : "Netz"} &copy; {currentYear}</span>
	</footer>
</div>

<style>
	.netz-investor-shell {
		display: flex;
		flex-direction: column;
		min-height: 100vh;
		background: var(--netz-surface-alt, #f9fafb);
	}

	.netz-investor-shell__topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 24px;
		background: var(--netz-surface, #ffffff);
		border-bottom: 1px solid var(--netz-border, #e5e7eb);
		flex-shrink: 0;
	}

	.netz-investor-shell__brand {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.netz-investor-shell__logo {
		height: 32px;
		width: auto;
		object-fit: contain;
	}

	.netz-investor-shell__org-name {
		font-size: 16px;
		font-weight: 600;
		color: var(--netz-text-primary, #111827);
	}

	.netz-investor-shell__actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.netz-investor-shell__lang-toggle {
		padding: 6px 12px;
		border: 1px solid var(--netz-border, #e5e7eb);
		border-radius: 6px;
		background: transparent;
		color: var(--netz-text-secondary, #6b7280);
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.netz-investor-shell__lang-toggle:hover {
		background: var(--netz-surface-alt, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-investor-shell__sign-out {
		padding: 6px 16px;
		border: 1px solid var(--netz-border, #e5e7eb);
		border-radius: 6px;
		background: transparent;
		color: var(--netz-text-secondary, #6b7280);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.netz-investor-shell__sign-out:hover {
		background: var(--netz-surface-alt, #f3f4f6);
		color: var(--netz-text-primary, #111827);
	}

	.netz-investor-shell__main {
		flex: 1;
		padding: 24px;
	}

	.netz-investor-shell__footer {
		padding: 16px 24px;
		text-align: center;
		font-size: 13px;
		color: var(--netz-text-muted, #9ca3af);
		border-top: 1px solid var(--netz-border, #e5e7eb);
		flex-shrink: 0;
	}

	@media (max-width: 599px) {
		.netz-investor-shell__topbar {
			padding: 12px 16px;
		}
		.netz-investor-shell__main {
			padding: 16px;
		}
	}
</style>
