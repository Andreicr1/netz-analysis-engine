#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Netz Analysis Engine — Cloudflare Full Provisioning Script
# ═══════════════════════════════════════════════════════════════════
#
# Creates ALL services, secrets, R2 bucket, Pages projects,
# and GitHub Actions secrets via CLI. No console needed.
#
# Prerequisites:
#   npm install -g wrangler
#   wrangler login          # OAuth browser flow
#   gh auth login           # GitHub CLI
#
# Usage:
#   bash provision.sh
#
# Reads secrets from ../../.env.production (repo root)
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.production"

# ── Colors ──────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
step()  { echo -e "\n${GREEN}═══ $* ═══${NC}"; }

# ── Load .env.production ──────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  fail "Missing $ENV_FILE"
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

# ── Derived values (not in .env.production) ────────────────────
# Shared secret for gateway↔backend↔cron internal auth
WORKER_DISPATCH_SECRET="${WORKER_DISPATCH_SECRET:-Gwq3H8bEhDqOCVIks8Xd4dJZugKTrl_KlfX54jYyi7c}"

# Map .env.production names to what Cloudflare services expect
PUBLIC_CLERK_PUBLISHABLE_KEY="${CLERK_PUBLISHABLE_KEY}"

ACCOUNT_ID="${R2_ACCOUNT_ID}"
GITHUB_REPO="${GITHUB_REPO:-$(cd "$REPO_ROOT" && gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo '')}"

# ── Validate ────────────────────────────────────────────────────
REQUIRED_VARS=(
  DATABASE_URL REDIS_URL OPENAI_API_KEY MISTRAL_API_KEY
  CLERK_SECRET_KEY CLERK_JWKS_URL
  R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET_NAME
  FRED_API_KEY WORKER_DISPATCH_SECRET
)

missing=()
for var in "${REQUIRED_VARS[@]}"; do
  [[ -n "${!var:-}" ]] || missing+=("$var")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  fail "Missing vars:\n  ${missing[*]}"
fi

info "Account ID: ${ACCOUNT_ID}"
info "GitHub repo: ${GITHUB_REPO:-'(not detected)'}"
echo ""

# ═══════════════════════════════════════════════════════════════════
# 1. R2 Bucket
# ═══════════════════════════════════════════════════════════════════
step "1/7 — R2 Bucket"

if wrangler r2 bucket list 2>/dev/null | grep -q "${R2_BUCKET_NAME}"; then
  ok "Bucket '${R2_BUCKET_NAME}' already exists"
else
  info "Creating R2 bucket '${R2_BUCKET_NAME}'..."
  wrangler r2 bucket create "${R2_BUCKET_NAME}"
  ok "Bucket created"
fi

# ═══════════════════════════════════════════════════════════════════
# 2. Gateway Worker
# ═══════════════════════════════════════════════════════════════════
step "2/7 — Gateway Worker (netz-gateway)"

cd "${SCRIPT_DIR}/gateway"
npm install --silent 2>/dev/null || true

info "Deploying netz-gateway..."
npx wrangler deploy

info "Setting WORKER_SECRET..."
echo "${WORKER_DISPATCH_SECRET}" | npx wrangler secret put WORKER_SECRET

ok "netz-gateway deployed"

# ═══════════════════════════════════════════════════════════════════
# 3. Cron Worker
# ═══════════════════════════════════════════════════════════════════
step "3/7 — Cron Worker (netz-cron)"

cd "${SCRIPT_DIR}/cron"
npm install --silent 2>/dev/null || true

info "Deploying netz-cron..."
npx wrangler deploy

info "Setting WORKER_SECRET..."
echo "${WORKER_DISPATCH_SECRET}" | npx wrangler secret put WORKER_SECRET

ok "netz-cron deployed"

# ═══════════════════════════════════════════════════════════════════
# Helper: push secrets to a container config
# ═══════════════════════════════════════════════════════════════════
push_container_secrets() {
  local config_file="$1"
  local label="$2"

  local secrets=(
    DATABASE_URL REDIS_URL OPENAI_API_KEY MISTRAL_API_KEY
    CLERK_SECRET_KEY CLERK_JWKS_URL
    R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET_NAME
    WORKER_DISPATCH_SECRET FRED_API_KEY
    EDGAR_IDENTITY
  )

  info "Setting ${label} secrets..."
  for name in "${secrets[@]}"; do
    if [[ -n "${!name:-}" ]]; then
      echo "${!name}" | npx wrangler secret put "$name" --config "$config_file" 2>/dev/null && \
        ok "  ${name}" || warn "  ${name} — set manually"
    fi
  done
}

# ═══════════════════════════════════════════════════════════════════
# 4. Backend Container
# ═══════════════════════════════════════════════════════════════════
step "4/7 — Backend Container (netz-backend)"

cd "${SCRIPT_DIR}"
push_container_secrets "wrangler.backend.jsonc" "backend"

info "Deploying netz-backend container..."
npx wrangler containers deploy --config wrangler.backend.jsonc 2>&1 || \
  warn "Container deploy requires Docker build+push first (CI handles this)"

ok "netz-backend configured"

# ═══════════════════════════════════════════════════════════════════
# 5. Workers Container
# ═══════════════════════════════════════════════════════════════════
step "5/7 — Workers Container (netz-workers)"

cd "${SCRIPT_DIR}"
push_container_secrets "wrangler.workers.jsonc" "workers"

info "Deploying netz-workers container..."
npx wrangler containers deploy --config wrangler.workers.jsonc 2>&1 || \
  warn "Container deploy requires Docker build+push first (CI handles this)"

ok "netz-workers configured"

# ═══════════════════════════════════════════════════════════════════
# 6. Cloudflare Pages (3 frontends)
# ═══════════════════════════════════════════════════════════════════
step "6/7 — Cloudflare Pages (3 frontends)"

PAGES_APPS=("netz-credit" "netz-wealth" "netz-admin")
PAGES_DIRS=("frontends/credit" "frontends/wealth" "frontends/admin")

# Get API token for REST calls (wrangler stores it after login)
CF_TOKEN_FILE="${HOME}/.wrangler/config/default.toml"
CF_API_TOKEN_LOCAL=""
if [[ -f "$CF_TOKEN_FILE" ]]; then
  CF_API_TOKEN_LOCAL=$(grep -oP 'oauth_token\s*=\s*"\K[^"]+' "$CF_TOKEN_FILE" 2>/dev/null || echo "")
fi
# Fallback: env var
CF_API_TOKEN_LOCAL="${CF_API_TOKEN_LOCAL:-${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}}"

for i in "${!PAGES_APPS[@]}"; do
  app="${PAGES_APPS[$i]}"
  dir="${PAGES_DIRS[$i]}"

  info "Creating Pages project '${app}'..."
  npx wrangler pages project create "${app}" \
    --production-branch main 2>/dev/null && \
    ok "${app} created" || \
    ok "${app} already exists"

  # Set env vars via Cloudflare API (wrangler pages doesn't support env var management)
  if [[ -n "$CF_API_TOKEN_LOCAL" ]]; then
    info "Setting env vars for ${app}..."
    curl -s -X PATCH \
      "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/pages/projects/${app}" \
      -H "Authorization: Bearer ${CF_API_TOKEN_LOCAL}" \
      -H "Content-Type: application/json" \
      -d "{
        \"deployment_configs\": {
          \"production\": {
            \"env_vars\": {
              \"PUBLIC_BACKEND_URL\": { \"value\": \"https://api.netz.app\" },
              \"PUBLIC_CLERK_PUBLISHABLE_KEY\": { \"value\": \"${PUBLIC_CLERK_PUBLISHABLE_KEY}\" }
            }
          }
        }
      }" > /dev/null 2>&1 && ok "${app} env vars set" || warn "${app} env vars — set in Dashboard"
  else
    warn "${app} env vars — no API token found, set in Dashboard"
  fi
done

# ═══════════════════════════════════════════════════════════════════
# 7. GitHub Actions Secrets
# ═══════════════════════════════════════════════════════════════════
step "7/7 — GitHub Actions Secrets"

if [[ -n "${GITHUB_REPO:-}" ]] && command -v gh &>/dev/null; then
  info "Setting GitHub secrets for ${GITHUB_REPO}..."

  echo "${ACCOUNT_ID}" | gh secret set CF_ACCOUNT_ID --repo "${GITHUB_REPO}"
  ok "CF_ACCOUNT_ID"

  if [[ -n "${CF_API_TOKEN:-}" ]]; then
    echo "${CF_API_TOKEN}" | gh secret set CF_API_TOKEN --repo "${GITHUB_REPO}"
    ok "CF_API_TOKEN"
  else
    warn "CF_API_TOKEN — create at dash.cloudflare.com/profile/api-tokens then run:"
    warn "  gh secret set CF_API_TOKEN --repo ${GITHUB_REPO}"
    echo ""
    warn "Token permissions needed:"
    warn "  Account: Cloudflare Pages (Edit), Workers Scripts (Edit)"
    warn "  Account: Workers R2 Storage (Edit)"
    warn "  Zone: DNS (Edit) — for api.netz.app CNAME"
  fi
else
  warn "GitHub secrets skipped (gh CLI not authenticated or no repo detected)"
fi

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
step "Provisioning Complete"

cat <<'SUMMARY'

Services:
  R2 bucket:    netz-data-lake
  Worker:       netz-gateway  (API proxy + /internal/ auth)
  Worker:       netz-cron     (7 cron schedules → worker dispatch)
  Container:    netz-backend  (FastAPI, 1-3 instances)
  Container:    netz-workers  (background jobs, 0-1, sleep 30m)
  Pages:        netz-credit, netz-wealth, netz-admin

Remaining manual steps:
  1. Create CF_API_TOKEN at dash.cloudflare.com/profile/api-tokens
     Then: gh secret set CF_API_TOKEN
  2. Pages: connect GitHub repo in Dashboard for auto-deploy
     Build command:  pnpm install && pnpm build
     Output dir:     .svelte-kit/cloudflare
     Root dir:       frontends/<app>
  3. DNS (run provision-dns.sh or manually):
     api.netz.app    → CNAME → netz-gateway.<sub>.workers.dev (proxied)
     credit.netz.app → Pages custom domain
     wealth.netz.app → Pages custom domain
     admin.netz.app  → Pages custom domain
  4. Verify: curl https://api.netz.app/api/v1/admin/health

First deploy: git push origin main

SUMMARY
