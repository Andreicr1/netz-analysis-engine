#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Netz DNS Setup — Cloudflare API
# ═══════════════════════════════════════════════════════════════════
#
# Creates DNS records for api.netz.app → gateway worker
#
# Prerequisites:
#   export CF_API_TOKEN="your-cloudflare-api-token"
#   export CF_ZONE_ID="your-zone-id-for-netz.app"
#
# Get zone ID:
#   curl -s "https://api.cloudflare.com/client/v4/zones?name=netz.app" \
#     -H "Authorization: Bearer $CF_API_TOKEN" | jq '.result[0].id'
#
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

: "${CF_API_TOKEN:?Set CF_API_TOKEN}"
: "${CF_ZONE_ID:?Set CF_ZONE_ID — run: curl -s 'https://api.cloudflare.com/client/v4/zones?name=netz.app' -H 'Authorization: Bearer \$CF_API_TOKEN' | jq '.result[0].id'}"

API="https://api.cloudflare.com/client/v4"
AUTH="Authorization: Bearer ${CF_API_TOKEN}"

create_record() {
  local type="$1" name="$2" content="$3" proxied="${4:-true}"

  echo -n "Creating ${type} ${name} → ${content} ... "

  # Check if record already exists
  existing=$(curl -s "${API}/zones/${CF_ZONE_ID}/dns_records?type=${type}&name=${name}" \
    -H "${AUTH}" | python3 -c "import sys,json; r=json.load(sys.stdin); print(len(r.get('result',[])))" 2>/dev/null || echo "0")

  if [[ "$existing" -gt 0 ]]; then
    echo "already exists (skipped)"
    return
  fi

  result=$(curl -s -X POST "${API}/zones/${CF_ZONE_ID}/dns_records" \
    -H "${AUTH}" \
    -H "Content-Type: application/json" \
    -d "{
      \"type\": \"${type}\",
      \"name\": \"${name}\",
      \"content\": \"${content}\",
      \"proxied\": ${proxied},
      \"ttl\": 1
    }")

  success=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success',False))" 2>/dev/null)

  if [[ "$success" == "True" ]]; then
    echo "OK"
  else
    echo "FAILED"
    echo "$result" | python3 -m json.tool 2>/dev/null || echo "$result"
  fi
}

echo "═══ Netz DNS Records ═══"
echo ""

# API gateway — proxied CNAME to the gateway worker
# Replace <account-subdomain> with your actual Cloudflare workers.dev subdomain
GATEWAY_TARGET="${GATEWAY_TARGET:-netz-gateway.netz.workers.dev}"

create_record "CNAME" "api.netz.app" "${GATEWAY_TARGET}" "true"

echo ""
echo "Done. Pages custom domains (credit/wealth/admin.netz.app) are"
echo "configured via Cloudflare Pages Dashboard → Custom domains."
echo ""
echo "Verify: curl -I https://api.netz.app/api/v1/admin/health"
