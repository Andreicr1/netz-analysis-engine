<!--
  Admin Sign-In — institutional gate with Clerk mount and dev bypass.
  First impression of the governance console: authoritative, restrained, secure.
-->
<script lang="ts">
	import { page } from "$app/state";
	const DEV_MODE = import.meta.env.DEV;
	const error = $derived(page.url.searchParams.get("error"));
</script>

<div class="sign-in-shell">
	<!-- Ambient background -->
	<div class="sign-in-bg" aria-hidden="true">
		<div class="sign-in-bg__wash"></div>
		<div class="sign-in-bg__grid"></div>
	</div>

	<!-- Content -->
	<main class="sign-in-content">
		<!-- Branding mark -->
		<div class="sign-in-mark">
			<span class="sign-in-mark__glyph" aria-hidden="true">N</span>
		</div>

		<div class="sign-in-card">
			<!-- Header -->
			<div class="sign-in-card__header">
				<h1 class="sign-in-card__title">Netz Admin</h1>
				<p class="sign-in-card__subtitle">Platform governance console</p>
			</div>

			<!-- Error state -->
			{#if error === "unauthorized"}
				<div class="sign-in-error" role="alert">
					<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
						<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>
					</svg>
					<span>Platform admin credentials required to access this console.</span>
				</div>
			{/if}

			<!-- Auth surface -->
			<div class="sign-in-auth">
				{#if DEV_MODE}
					<div class="sign-in-dev">
						<p class="sign-in-dev__label">Development bypass</p>
						<a
							href="/"
							class="sign-in-dev__button"
						>
							Continue as dev admin
						</a>
					</div>
				{:else}
					<!-- Clerk SignIn component mount point -->
					<div id="clerk-sign-in" class="sign-in-clerk">
						<p class="sign-in-clerk__loading">Initializing authentication...</p>
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="sign-in-card__footer">
				<p>Restricted access — authorized administrators only</p>
			</div>
		</div>

		<!-- System label -->
		<p class="sign-in-system">Netz Analysis Engine</p>
	</main>
</div>

<style>
	/* ── Shell ──────────────────────────────────────── */
	.sign-in-shell {
		position: relative;
		display: flex;
		min-height: 100vh;
		align-items: center;
		justify-content: center;
		overflow: hidden;
		background: var(--netz-brand-primary);
	}

	/* ── Ambient background ────────────────────────── */
	.sign-in-bg {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}

	.sign-in-bg__wash {
		position: absolute;
		inset: 0;
		background: radial-gradient(
			ellipse 80% 60% at 50% 40%,
			color-mix(in srgb, var(--netz-brand-secondary) 16%, transparent) 0%,
			transparent 70%
		);
	}

	.sign-in-bg__grid {
		position: absolute;
		inset: 0;
		opacity: 0.04;
		background-image:
			linear-gradient(rgba(255, 255, 255, 0.5) 1px, transparent 1px),
			linear-gradient(90deg, rgba(255, 255, 255, 0.5) 1px, transparent 1px);
		background-size: 48px 48px;
		mask-image: radial-gradient(ellipse 70% 50% at 50% 50%, black 30%, transparent 80%);
	}

	/* ── Content ───────────────────────────────────── */
	.sign-in-content {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 28px;
		padding: 40px 24px;
		width: 100%;
		max-width: 420px;
		animation: sign-in-enter 600ms cubic-bezier(0.22, 1, 0.36, 1) both;
	}

	@keyframes sign-in-enter {
		from {
			opacity: 0;
			transform: translateY(12px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* ── Brand mark ────────────────────────────────── */
	.sign-in-mark {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 48px;
		height: 48px;
		border-radius: var(--netz-radius-md);
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.1);
		backdrop-filter: blur(8px);
	}

	.sign-in-mark__glyph {
		font-family: var(--netz-font-sans);
		font-size: 22px;
		font-weight: 700;
		letter-spacing: -0.04em;
		color: rgba(255, 255, 255, 0.92);
		line-height: 1;
	}

	/* ── Card ──────────────────────────────────────── */
	.sign-in-card {
		width: 100%;
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-lg);
		box-shadow:
			0 1px 2px rgba(0, 0, 0, 0.06),
			0 8px 24px rgba(0, 0, 0, 0.12),
			0 24px 48px rgba(0, 0, 0, 0.06);
		overflow: hidden;
	}

	.sign-in-card__header {
		padding: 32px 32px 0;
		text-align: center;
	}

	.sign-in-card__title {
		margin: 0;
		font-family: var(--netz-font-sans);
		font-size: 22px;
		font-weight: 700;
		letter-spacing: -0.025em;
		color: var(--netz-text-primary);
		line-height: 1.2;
	}

	.sign-in-card__subtitle {
		margin: 6px 0 0;
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0.02em;
		color: var(--netz-text-muted);
	}

	.sign-in-card__footer {
		padding: 16px 32px;
		border-top: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-highlight);
		text-align: center;
	}

	.sign-in-card__footer p {
		margin: 0;
		font-size: 11px;
		font-weight: 500;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
	}

	/* ── Error state ───────────────────────────────── */
	.sign-in-error {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		margin: 20px 32px 0;
		padding: 12px 14px;
		font-size: 13px;
		line-height: 1.5;
		color: var(--netz-danger);
		background: var(--netz-danger-subtle);
		border: 1px solid color-mix(in srgb, var(--netz-danger) 20%, transparent);
		border-radius: var(--netz-radius-sm);
	}

	.sign-in-error svg {
		flex-shrink: 0;
		margin-top: 2px;
	}

	/* ── Auth surface ──────────────────────────────── */
	.sign-in-auth {
		padding: 24px 32px 28px;
	}

	/* Dev bypass */
	.sign-in-dev {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.sign-in-dev__label {
		margin: 0;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		text-align: center;
	}

	.sign-in-dev__button {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 42px;
		padding: 0 24px;
		font-family: var(--netz-font-sans);
		font-size: 14px;
		font-weight: 600;
		letter-spacing: -0.01em;
		color: var(--netz-text-on-accent);
		background: var(--netz-brand-primary);
		border: none;
		border-radius: var(--netz-radius-md);
		text-decoration: none;
		cursor: pointer;
		transition: opacity 150ms ease, box-shadow 150ms ease;
	}

	.sign-in-dev__button:hover {
		opacity: 0.92;
		box-shadow: 0 2px 8px color-mix(in srgb, var(--netz-brand-primary) 30%, transparent);
	}

	.sign-in-dev__button:active {
		opacity: 0.85;
	}

	/* Clerk mount */
	.sign-in-clerk {
		display: flex;
		justify-content: center;
		min-height: 48px;
		align-items: center;
	}

	.sign-in-clerk__loading {
		margin: 0;
		font-size: 13px;
		color: var(--netz-text-muted);
		animation: sign-in-pulse 2s ease-in-out infinite;
	}

	@keyframes sign-in-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}

	/* ── System label ──────────────────────────────── */
	.sign-in-system {
		margin: 0;
		font-family: var(--netz-font-mono);
		font-size: 11px;
		letter-spacing: 0.04em;
		color: rgba(255, 255, 255, 0.28);
	}

	/* ── Dark theme adjustments ────────────────────── */
	:global([data-theme="dark"]) .sign-in-card {
		box-shadow:
			0 1px 2px rgba(0, 0, 0, 0.2),
			0 8px 24px rgba(0, 0, 0, 0.32),
			0 24px 48px rgba(0, 0, 0, 0.2);
	}

	:global([data-theme="dark"]) .sign-in-bg__grid {
		opacity: 0.03;
	}
</style>
