<!--
  Wealth Sign-In — institutional gate with Clerk mount and dev bypass.
  First impression of the wealth platform: refined, composed, institutional trust.
-->
<script lang="ts">
	const DEV_MODE = import.meta.env.DEV;
</script>

<div class="sign-in-shell">
	<!-- Ambient background -->
	<div class="sign-in-bg" aria-hidden="true">
		<div class="sign-in-bg__wash"></div>
		<div class="sign-in-bg__dots"></div>
		<div class="sign-in-bg__vignette"></div>
	</div>

	<!-- Content -->
	<main class="sign-in-content">
		<!-- Brand mark -->
		<div class="sign-in-mark">
			<div class="sign-in-mark__icon">
				<span class="sign-in-mark__glyph" aria-hidden="true">N</span>
			</div>
			<div class="sign-in-mark__text">
				<span class="sign-in-mark__name">Netz</span>
				<span class="sign-in-mark__product">Wealth OS</span>
			</div>
		</div>

		<div class="sign-in-card">
			<!-- Accent bar -->
			<div class="sign-in-card__accent" aria-hidden="true"></div>

			<!-- Header -->
			<div class="sign-in-card__header">
				<h1 class="sign-in-card__title">Welcome back</h1>
				<p class="sign-in-card__subtitle">Sign in to your wealth management console</p>
			</div>

			<!-- Auth surface -->
			<div class="sign-in-auth">
				{#if DEV_MODE}
					<div class="sign-in-dev">
						<p class="sign-in-dev__label">Development bypass</p>
						<a
							href="/"
							class="sign-in-dev__button"
						>
							Continue as Dev User
						</a>
					</div>
				{:else}
					<!-- svelte-clerk SignIn component will be mounted here -->
					<div id="clerk-sign-in" class="sign-in-clerk">
						<p class="sign-in-clerk__loading">Loading authentication...</p>
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="sign-in-card__footer">
				<p>Institutional access &middot; Authorized users only</p>
			</div>
		</div>

		<!-- System label -->
		<p class="sign-in-system">Netz Analysis Engine &middot; Wealth</p>
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
		background: var(--netz-brand-primary, #1b365d);
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
		background:
			radial-gradient(
				ellipse 60% 50% at 30% 40%,
				color-mix(in srgb, var(--netz-brand-secondary, #c9a84c) 8%, transparent) 0%,
				transparent 60%
			),
			radial-gradient(
				ellipse 50% 40% at 70% 60%,
				color-mix(in srgb, var(--netz-brand-secondary, #c9a84c) 5%, transparent) 0%,
				transparent 50%
			);
	}

	.sign-in-bg__dots {
		position: absolute;
		inset: 0;
		opacity: 0.03;
		background-image: radial-gradient(circle, rgba(255, 255, 255, 0.6) 1px, transparent 1px);
		background-size: 32px 32px;
		mask-image: radial-gradient(ellipse 65% 55% at 50% 50%, black 20%, transparent 70%);
	}

	.sign-in-bg__vignette {
		position: absolute;
		inset: 0;
		background: radial-gradient(
			ellipse 100% 100% at 50% 50%,
			transparent 40%,
			rgba(0, 0, 0, 0.15) 100%
		);
	}

	/* ── Content ───────────────────────────────────── */
	.sign-in-content {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 32px;
		padding: 40px 24px;
		width: 100%;
		max-width: 420px;
		animation: sign-in-enter 700ms cubic-bezier(0.22, 1, 0.36, 1) both;
	}

	@keyframes sign-in-enter {
		from {
			opacity: 0;
			transform: translateY(16px);
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
		gap: 14px;
	}

	.sign-in-mark__icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 44px;
		height: 44px;
		border-radius: var(--netz-radius-md, 8px);
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.12);
		backdrop-filter: blur(8px);
	}

	.sign-in-mark__glyph {
		font-family: var(--netz-font-sans, system-ui);
		font-size: 20px;
		font-weight: 700;
		letter-spacing: -0.04em;
		color: rgba(255, 255, 255, 0.9);
		line-height: 1;
	}

	.sign-in-mark__text {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.sign-in-mark__name {
		font-family: var(--netz-font-sans, system-ui);
		font-size: 16px;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: rgba(255, 255, 255, 0.9);
		line-height: 1.1;
	}

	.sign-in-mark__product {
		font-family: var(--netz-font-sans, system-ui);
		font-size: 11px;
		font-weight: 500;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: rgba(255, 255, 255, 0.38);
		line-height: 1.2;
	}

	/* ── Card ──────────────────────────────────────── */
	.sign-in-card {
		width: 100%;
		background: var(--netz-surface-elevated, #fff);
		border: 1px solid var(--netz-border-subtle, rgba(0, 0, 0, 0.08));
		border-radius: var(--netz-radius-lg, 12px);
		box-shadow:
			0 1px 2px rgba(0, 0, 0, 0.06),
			0 6px 20px rgba(0, 0, 0, 0.1),
			0 20px 44px rgba(0, 0, 0, 0.08);
		overflow: hidden;
	}

	.sign-in-card__accent {
		height: 2px;
		background: linear-gradient(
			90deg,
			transparent 0%,
			color-mix(in srgb, var(--netz-brand-secondary, #c9a84c) 50%, transparent) 30%,
			var(--netz-brand-secondary, #c9a84c) 50%,
			color-mix(in srgb, var(--netz-brand-secondary, #c9a84c) 50%, transparent) 70%,
			transparent 100%
		);
	}

	.sign-in-card__header {
		padding: 30px 32px 0;
		text-align: center;
	}

	.sign-in-card__title {
		margin: 0;
		font-family: var(--netz-font-sans, system-ui);
		font-size: 22px;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: var(--netz-text-primary, #111);
		line-height: 1.2;
	}

	.sign-in-card__subtitle {
		margin: 6px 0 0;
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0.01em;
		color: var(--netz-text-muted, #888);
	}

	.sign-in-card__footer {
		padding: 16px 32px;
		border-top: 1px solid var(--netz-border-subtle, rgba(0, 0, 0, 0.06));
		background: var(--netz-surface-highlight, rgba(0, 0, 0, 0.015));
		text-align: center;
	}

	.sign-in-card__footer p {
		margin: 0;
		font-size: 11px;
		font-weight: 500;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--netz-text-muted, #999);
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
		color: var(--netz-text-muted, #999);
		text-align: center;
	}

	.sign-in-dev__button {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 42px;
		padding: 0 24px;
		font-family: var(--netz-font-sans, system-ui);
		font-size: 14px;
		font-weight: 600;
		letter-spacing: -0.01em;
		color: var(--netz-text-on-accent, #fff);
		background: var(--netz-brand-primary, #1b365d);
		border: none;
		border-radius: var(--netz-radius-md, 8px);
		text-decoration: none;
		cursor: pointer;
		transition: opacity 150ms ease, box-shadow 150ms ease;
	}

	.sign-in-dev__button:hover {
		opacity: 0.92;
		box-shadow: 0 2px 8px color-mix(in srgb, var(--netz-brand-primary, #1b365d) 30%, transparent);
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
		color: var(--netz-text-muted, #999);
		animation: sign-in-pulse 2s ease-in-out infinite;
	}

	@keyframes sign-in-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}

	/* ── System label ──────────────────────────────── */
	.sign-in-system {
		margin: 0;
		font-family: var(--netz-font-mono, monospace);
		font-size: 11px;
		letter-spacing: 0.04em;
		color: rgba(255, 255, 255, 0.22);
	}

	/* ── Dark theme adjustments ────────────────────── */
	:global([data-theme="dark"]) .sign-in-card {
		box-shadow:
			0 1px 2px rgba(0, 0, 0, 0.2),
			0 6px 20px rgba(0, 0, 0, 0.3),
			0 20px 44px rgba(0, 0, 0, 0.2);
	}

	:global([data-theme="dark"]) .sign-in-bg__dots {
		opacity: 0.02;
	}

	:global([data-theme="dark"]) .sign-in-card__accent {
		opacity: 0.7;
	}
</style>
