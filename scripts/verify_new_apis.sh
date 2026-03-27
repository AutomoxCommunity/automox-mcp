#!/bin/bash
# Non-destructive verification of new API endpoints
# All requests are GET-only (read-only)
# Usage: bash scripts/verify_new_apis.sh

set -euo pipefail

# Auto-export all variables from .env
set -a
source /Users/jkikta/automox/.env
set +a

BASE="https://console.automox.com/api"
ORG="${AUTOMOX_ORG_ID:?AUTOMOX_ORG_ID not set}"
KEY="${AUTOMOX_API_KEY:?AUTOMOX_API_KEY not set}"
ACCT_UUID="${AUTOMOX_ACCOUNT_UUID:-}"
AUTH="Authorization: Bearer ${KEY}"
TODAY=$(date -u +%Y-%m-%d)

# We need the org UUID for some endpoints. Get it from /orgs.
echo "=== Fetching org UUID ==="
ORG_RESP=$(curl -sf -H "$AUTH" "${BASE}/orgs" 2>&1) || { echo "FAIL: /orgs"; exit 1; }
ORG_UUID=$(echo "$ORG_RESP" | python3 -c "
import sys,json
orgs=json.load(sys.stdin)
for o in orgs:
    if o.get('id') == ${ORG}:
        print(o.get('uuid',''))
        break
" 2>/dev/null)
echo "Org UUID: ${ORG_UUID:-not found}"
echo "Account UUID: ${ACCT_UUID:-not found}"

# Get a device UUID for device-scoped endpoints
DEV_RESP=$(curl -sf -H "$AUTH" "${BASE}/servers?o=${ORG}&limit=1" 2>&1) || { echo "FAIL: /servers"; }
DEV_UUID=$(echo "$DEV_RESP" | python3 -c "
import sys,json
devs=json.load(sys.stdin)
if devs: print(devs[0].get('uuid',''))
" 2>/dev/null)
echo "Device UUID: ${DEV_UUID:-not found}"

# Get a group UUID
GRP_RESP=$(curl -sf -H "$AUTH" "${BASE}/servergroups?o=${ORG}&limit=1" 2>&1) || true
GRP_UUID=$(echo "$GRP_RESP" | python3 -c "
import sys,json
grps=json.load(sys.stdin)
if grps: print(grps[0].get('uuid',''))
" 2>/dev/null)
echo "Group UUID: ${GRP_UUID:-not found}"
echo ""

test_endpoint() {
    local name="$1"
    local url="$2"
    local extra_header="${3:-}"
    local http_code
    if [ -n "$extra_header" ]; then
        http_code=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH" -H "$extra_header" "$url" 2>&1)
    else
        http_code=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH" "$url" 2>&1)
    fi
    printf "%-55s %s\n" "$name" "$http_code"
}

echo "=== Already Confirmed (200 from round 1) ==="
echo "Endpoint                                                HTTP Status"
echo "--------------------------------------------------------------------"
test_endpoint "GET /sgapi/saved-search" "${BASE}/server-groups-api/v1/organizations/${ORG_UUID}/device/saved-search/list"
test_endpoint "GET /sgapi/metadata/fields" "${BASE}/server-groups-api/device/metadata/fields"
test_endpoint "GET /sgapi/metadata/scopes" "${BASE}/server-groups-api/device/metadata/scopes"
test_endpoint "GET /data-extracts" "${BASE}/data-extracts?o=${ORG}"
test_endpoint "GET /wis/search" "${BASE}/wis/search?o=${ORG}&limit=1"
test_endpoint "GET /orgs/{id}/api_keys" "${BASE}/orgs/${ORG}/api_keys"
test_endpoint "GET /rc-st device-status" "${BASE}/remotecontrol-st/device-status/${DEV_UUID}"

echo ""
echo "=== Fixed Parameters (were 400/405 in round 1) ==="
echo "Endpoint                                                HTTP Status"
echo "--------------------------------------------------------------------"

# Audit Service: requires date= param (required per OpenAPI spec)
test_endpoint "GET /audit-service (with date)" "${BASE}/audit-service/v1/orgs/${ORG_UUID}/events?date=${TODAY}&limit=1"

# Policy History: needs org UUID, not numeric ID
test_endpoint "GET /policy-history/runs (org UUID)" "${BASE}/policy-history/policy-runs?org=${ORG_UUID}&limit=5"
test_endpoint "GET /policy-history/policies (org UUID)" "${BASE}/policy-history/policies?org=${ORG_UUID}&limit=5"
test_endpoint "GET /policy-history/run-count" "${BASE}/policy-history/policy-run-count?org=${ORG_UUID}"
test_endpoint "GET /policy-history/runs grouped" "${BASE}/policy-history/policy-runs/grouped-by/policy?org=${ORG_UUID}&limit=5"

# RBAC Roles: needs account UUID, not numeric org ID
if [ -n "$ACCT_UUID" ]; then
    test_endpoint "GET /accounts/{uuid}/rbac-roles" "${BASE}/accounts/${ACCT_UUID}/rbac-roles"
    test_endpoint "GET /accounts/{uuid}/zones" "${BASE}/accounts/${ACCT_UUID}/zones"
    test_endpoint "GET /accounts/{uuid}/invitations" "${BASE}/accounts/${ACCT_UUID}/invitations"
    test_endpoint "GET /accounts/{uuid}/users" "${BASE}/accounts/${ACCT_UUID}/users"
    test_endpoint "GET /accounts/{uuid}" "${BASE}/accounts/${ACCT_UUID}"
fi

# Policy Windows: org-level is POST-only, test sub-endpoints with correct params
if [ -n "$GRP_UUID" ]; then
    test_endpoint "GET /policy-windows/group sched" "${BASE}/policy-windows/org/${ORG_UUID}/group/${GRP_UUID}/scheduled-windows"
fi
if [ -n "$DEV_UUID" ]; then
    test_endpoint "GET /policy-windows/device sched" "${BASE}/policy-windows/org/${ORG_UUID}/device/${DEV_UUID}/scheduled-windows"
fi

# Device Manifest Vendor: try with org header
test_endpoint "GET /dmv manifests (with org hdr)" "${BASE}/device-manifest-vendor/manifests" "ax-organization-uuid: ${ORG_UUID}"

# Remote Control config with org header
if [ -n "$DEV_UUID" ]; then
    test_endpoint "GET /rc config (with org hdr)" "${BASE}/remotecontrol-api/api/config/org/${ORG_UUID}/device/${DEV_UUID}" "ax-organization-uuid: ${ORG_UUID}"
fi

echo ""
echo "=== Additional Server Groups API v2 Endpoints ==="
echo "Endpoint                                                HTTP Status"
echo "--------------------------------------------------------------------"
test_endpoint "GET /sgapi/device-fields" "${BASE}/server-groups-api/device/metadata/device-fields"
test_endpoint "GET /sgapi/typeahead" "${BASE}/server-groups-api/v1/organizations/${ORG_UUID}/search/typeahead?q=test"
test_endpoint "GET /sgapi/assignments" "${BASE}/server-groups-api/v1/organizations/${ORG_UUID}/assignments"
if [ -n "$DEV_UUID" ]; then
    test_endpoint "GET /sgapi/server/{uuid}" "${BASE}/server-groups-api/v1/organizations/${ORG_UUID}/server/${DEV_UUID}"
fi

echo ""
echo "=== Vuln Sync / Remediations ==="
echo "Endpoint                                                HTTP Status"
echo "--------------------------------------------------------------------"
test_endpoint "GET /remediations/action-sets" "${BASE}/orgs/${ORG}/remediations/action-sets"
test_endpoint "GET /remediations/upload/formats" "${BASE}/orgs/${ORG}/remediations/action-sets/upload/formats"

echo ""
echo "=== Confirmed 404 (not routed / internal only) ==="
echo "Endpoint                                                HTTP Status"
echo "--------------------------------------------------------------------"
test_endpoint "GET /collections/{org}" "${BASE}/collections/${ORG_UUID}"
test_endpoint "GET /compliance/programs" "${BASE}/compliance/programs?o=${ORG}"
test_endpoint "GET /query-runtime (probe)" "${BASE}/query-runtime-api/"
test_endpoint "GET /llm (probe)" "${BASE}/llm/"
test_endpoint "GET /download-export (probe)" "${BASE}/download-export-service/"

echo ""
echo "=== Legend ==="
echo "200 = Accessible (public API)"
echo "401 = Auth rejected (may need different auth method)"
echo "403 = Forbidden (exists but not authorized for this key/org)"
echo "404 = Not found (endpoint doesn't exist or wrong path)"
echo "405 = Method not allowed (endpoint exists, POST-only)"
echo "500 = Server error (endpoint exists but errored)"
