<!--
  Credit Sign-In — institutional gate with Clerk mount and dev bypass.
  First impression of the credit intelligence platform: precise, authoritative, data-driven.
-->
<script lang="ts">
	import { onMount } from "svelte";
	import { browser } from "$app/environment";
	import { env } from "$env/dynamic/public";

	const DEV_MODE = import.meta.env.DEV;
	const CLERK_PK = env.PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";

	/** Decode Clerk publishable key to get the frontend API domain. */
	function clerkDomain(pk: string): string {
		const encoded = pk.replace(/^pk_(test|live)_/, "");
		return atob(encoded).replace(/\$$/, "");
	}

	onMount(async () => {
		if (DEV_MODE || !browser || !CLERK_PK) return;

		const domain = clerkDomain(CLERK_PK);

		// Load Clerk from their hosted CDN (includes full UI bundle).
		// npm dynamic import gets tree-shaken on Cloudflare Pages, stripping mountSignIn.
		await new Promise<void>((resolve, reject) => {
			if (document.querySelector('script[data-clerk-script]')) {
				resolve();
				return;
			}
			const script = document.createElement("script");
			script.setAttribute("data-clerk-script", "");
			script.setAttribute("data-clerk-publishable-key", CLERK_PK);
			script.async = true;
			script.src = `https://${domain}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`;
			script.onload = () => resolve();
			script.onerror = () => reject(new Error("Failed to load Clerk"));
			document.head.appendChild(script);
		});

		// Clerk hosted script auto-initializes window.Clerk as an instance
		const clerk = (window as any).Clerk;
		if (!clerk) return;
		await clerk.load();

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
					variables: { colorPrimary: "#2563eb" },
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
		<div class="sign-in-bg__grid"></div>
		<div class="sign-in-bg__accent"></div>
	</div>

	<!-- Content -->
	<main class="sign-in-content">
		<!-- Brand mark -->
		<div class="sign-in-mark">
			<span class="sign-in-mark__glyph" aria-hidden="true">N</span>
			<span class="sign-in-mark__badge">CREDIT</span>
		</div>

		<div class="sign-in-card">
			<!-- Header -->
			<div class="sign-in-card__header">
				<h1 class="sign-in-card__title">Netz Credit Intelligence</h1>
				<p class="sign-in-card__subtitle">Private credit analysis platform</p>
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
				<p>Institutional access — authorized personnel only</p>
			</div>
		</div>

		<!-- System label -->
		<p class="sign-in-system">Netz Analysis Engine &middot; Credit</p>
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
			ellipse 70% 50% at 50% 35%,
			color-mix(in srgb, var(--netz-brand-secondary) 12%, transparent) 0%,
			transparent 70%
		);
	}

	.sign-in-bg__grid {
		position: absolute;
		inset: 0;
		opacity: 0.035;
		background-image:
			linear-gradient(rgba(255, 255, 255, 0.4) 1px, transparent 1px),
			linear-gradient(90deg, rgba(255, 255, 255, 0.4) 1px, transparent 1px);
		background-size: 56px 56px;
		mask-image: radial-gradient(ellipse 60% 45% at 50% 50%, black 25%, transparent 75%);
	}

	.sign-in-bg__accent {
		position: absolute;
		top: -20%;
		right: -10%;
		width: 50%;
		height: 60%;
		background: radial-gradient(
			circle at center,
			color-mix(in srgb, var(--netz-brand-secondary) 6%, transparent) 0%,
			transparent 60%
		);
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
		animation: sign-in-enter 650ms cubic-bezier(0.22, 1, 0.36, 1) both;
	}

	@keyframes sign-in-enter {
		from {
			opacity: 0;
			transform: translateY(14px);
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
		gap: 12px;
	}

	.sign-in-mark__glyph {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 46px;
		height: 46px;
		border-radius: var(--netz-radius-md);
		background: rgba(255, 255, 255, 0.07);
		border: 1px solid rgba(255, 255, 255, 0.1);
		backdrop-filter: blur(8px);
		font-family: var(--netz-font-sans);
		font-size: 21px;
		font-weight: 700;
		letter-spacing: -0.04em;
		color: rgba(255, 255, 255, 0.9);
		line-height: 1;
	}

	.sign-in-mark__badge {
		font-family: var(--netz-font-mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: rgba(255, 255, 255, 0.4);
		padding: 4px 8px;
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: var(--netz-radius-sm);
		background: rgba(255, 255, 255, 0.03);
	}

	/* ── Card ──────────────────────────────────────── */
	.sign-in-card {
		width: 100%;
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-lg);
		box-shadow:
			0 1px 3px rgba(0, 0, 0, 0.08),
			0 8px 24px rgba(0, 0, 0, 0.14),
			0 24px 48px rgba(0, 0, 0, 0.08);
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
		color: rgba(255, 255, 255, 0.24);
	}

	/* ── Dark theme adjustments ────────────────────── */
	:global([data-theme="dark"]) .sign-in-card {
		box-shadow:
			0 1px 3px rgba(0, 0, 0, 0.24),
			0 8px 24px rgba(0, 0, 0, 0.36),
			0 24px 48px rgba(0, 0, 0, 0.24);
	}

	:global([data-theme="dark"]) .sign-in-bg__grid {
		opacity: 0.025;
	}
</style>
