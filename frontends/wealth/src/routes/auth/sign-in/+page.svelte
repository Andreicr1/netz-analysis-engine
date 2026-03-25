<!--
  Wealth Sign-In — institutional gate with Clerk mount and dev bypass.
  First impression of the wealth platform: refined, composed, institutional trust.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { browser } from "$app/environment";
	import { page } from "$app/stores";

	const DEV_MODE = import.meta.env.DEV;

	/** Decode Clerk publishable key to get the frontend API domain. */
	function clerkDomain(pk: string): string {
		const encoded = pk.replace(/^pk_(test|live)_/, "");
		return atob(encoded).replace(/\$$/, "");
	}

	onMount(async () => {
		const CLERK_PK = $page.data.clerkPublishableKey ?? "";
		if (DEV_MODE || !browser || !CLERK_PK) return;

		const domain = clerkDomain(CLERK_PK);

		// Load Clerk from their hosted CDN (includes full UI bundle).
		// npm dynamic import gets tree-shaken on Cloudflare Pages, stripping mountSignIn.
		// IMPORTANT: do NOT set data-clerk-publishable-key on the script tag —
		// that triggers Clerk's auto-initialization with navigation handlers
		// which causes infinite redirect loops on non-localhost domains with dev keys.
		await new Promise<void>((resolve, reject) => {
			if (document.querySelector('script[data-clerk-script]')) {
				resolve();
				return;
			}
			const script = document.createElement("script");
			script.setAttribute("data-clerk-script", "");
			script.async = true;
			script.src = `https://${domain}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`;
			script.onload = () => resolve();
			script.onerror = () => reject(new Error("Failed to load Clerk"));
			document.head.appendChild(script);
		});

		// Without data-clerk-publishable-key, window.Clerk is the class (not an auto-initialized instance).
		// We must construct and load manually to avoid Clerk's built-in routing/navigation.
		const ClerkClass = (window as any).Clerk;
		if (!ClerkClass) return;

		let clerk: any;
		if (typeof ClerkClass.load === "function") {
			// Already an auto-initialized instance (script was cached with old attribute)
			clerk = ClerkClass;
		} else {
			// Class constructor — manual initialization (no routing side-effects)
			clerk = new ClerkClass(CLERK_PK);
		}
		await clerk.load({ routerPush: () => {}, routerReplace: () => {} });

		// If already signed in, sync session cookie and redirect to app
		if (clerk.session) {
			const token = await clerk.session.getToken();
			if (token) {
				document.cookie = `__session=${token}; path=/; secure; samesite=lax`;
				window.location.href = "/";
				return;
			}
		}

		const el = document.getElementById("clerk-sign-in") as HTMLDivElement | null;
		if (el) {
			el.innerHTML = "";
			clerk.mountSignIn(el, {
				fallbackRedirectUrl: "/",
				afterSignInUrl: "/",
				appearance: {
					variables: {
						colorPrimary: "#6366f1",
					},
				},
			});
		}

		// After sign-in completes, sync session cookie before navigation
		clerk.addListener(({ session }: any) => {
			if (session) {
				session.getToken().then((t: string) => {
					if (t) document.cookie = `__session=${t}; path=/; secure; samesite=lax`;
				});
			}
		});
	});
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
		background:
			radial-gradient(
				ellipse 60% 50% at 30% 40%,
				color-mix(in srgb, var(--netz-brand-secondary) 8%, transparent) 0%,
				transparent 60%
			),
			radial-gradient(
				ellipse 50% 40% at 70% 60%,
				color-mix(in srgb, var(--netz-brand-secondary) 5%, transparent) 0%,
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
		border-radius: var(--netz-radius-md);
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.12);
		backdrop-filter: blur(8px);
	}

	.sign-in-mark__glyph {
		font-family: var(--netz-font-sans);
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
		font-family: var(--netz-font-sans);
		font-size: 16px;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: rgba(255, 255, 255, 0.9);
		line-height: 1.1;
	}

	.sign-in-mark__product {
		font-family: var(--netz-font-sans);
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
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-lg);
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
			color-mix(in srgb, var(--netz-brand-secondary) 50%, transparent) 30%,
			var(--netz-brand-secondary) 50%,
			color-mix(in srgb, var(--netz-brand-secondary) 50%, transparent) 70%,
			transparent 100%
		);
	}

	.sign-in-card__header {
		padding: 30px 32px 0;
		text-align: center;
	}

	.sign-in-card__title {
		margin: 0;
		font-family: var(--netz-font-sans);
		font-size: 22px;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: var(--netz-text-primary);
		line-height: 1.2;
	}

	.sign-in-card__subtitle {
		margin: 6px 0 0;
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0.01em;
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
