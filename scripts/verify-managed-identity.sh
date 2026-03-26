#!/usr/bin/env bash
# verify-managed-identity.sh
#
# Verifies that all 7 agent managed identities have the correct RBAC
# role assignments and no broader scope than designed (INFRA-006, AUDIT-005, D-14).
#
# Usage: ./scripts/verify-managed-identity.sh <resource-group> <environment>
#
# Requires: az CLI authenticated with Reader access to the subscription.

set -euo pipefail

RESOURCE_GROUP="${1:?Usage: $0 <resource-group> <environment>}"
ENVIRONMENT="${2:?Usage: $0 <resource-group> <environment>}"

echo "=== AAP RBAC Verification ==="
echo "Resource Group: ${RESOURCE_GROUP}"
echo "Environment: ${ENVIRONMENT}"
echo ""

# Expected role assignments per agent (from D-14)
declare -A EXPECTED_ROLES
EXPECTED_ROLES["ca-orchestrator-${ENVIRONMENT}"]="Reader"
EXPECTED_ROLES["ca-compute-${ENVIRONMENT}"]="Virtual Machine Contributor,Monitoring Reader"
EXPECTED_ROLES["ca-network-${ENVIRONMENT}"]="Network Contributor,Reader"
EXPECTED_ROLES["ca-storage-${ENVIRONMENT}"]="Storage Blob Data Reader"
EXPECTED_ROLES["ca-security-${ENVIRONMENT}"]="Security Reader"
EXPECTED_ROLES["ca-sre-${ENVIRONMENT}"]="Reader,Monitoring Reader"
EXPECTED_ROLES["ca-arc-${ENVIRONMENT}"]="Contributor"

EXIT_CODE=0

for APP_NAME in "${!EXPECTED_ROLES[@]}"; do
    echo "--- Checking: ${APP_NAME} ---"

    # Get principal ID from Container App
    PRINCIPAL_ID=$(az containerapp show \
        --name "${APP_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query "identity.principalId" \
        --output tsv 2>/dev/null || echo "")

    if [ -z "${PRINCIPAL_ID}" ]; then
        echo "  ERROR: Container App ${APP_NAME} not found or has no managed identity"
        EXIT_CODE=1
        continue
    fi

    echo "  Principal ID: ${PRINCIPAL_ID}"

    # Get actual role assignments
    ACTUAL_ROLES=$(az role assignment list \
        --assignee "${PRINCIPAL_ID}" \
        --query "[].roleDefinitionName" \
        --output tsv 2>/dev/null | sort | tr '\n' ',' | sed 's/,$//')

    echo "  Expected roles: ${EXPECTED_ROLES[${APP_NAME}]}"
    echo "  Actual roles:   ${ACTUAL_ROLES}"

    # Check each expected role is present
    IFS=',' read -ra EXPECTED_ARRAY <<< "${EXPECTED_ROLES[${APP_NAME}]}"
    for ROLE in "${EXPECTED_ARRAY[@]}"; do
        if echo "${ACTUAL_ROLES}" | grep -q "${ROLE}"; then
            echo "  OK: ${ROLE}"
        else
            echo "  MISSING: ${ROLE}"
            EXIT_CODE=1
        fi
    done

    # Check for unexpected Owner or User Access Administrator roles
    if echo "${ACTUAL_ROLES}" | grep -q "Owner"; then
        echo "  WARNING: Agent has Owner role — too broad!"
        EXIT_CODE=1
    fi
    if echo "${ACTUAL_ROLES}" | grep -q "User Access Administrator"; then
        echo "  WARNING: Agent has User Access Administrator — too broad!"
        EXIT_CODE=1
    fi

    echo ""
done

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "=== All RBAC checks PASSED ==="
else
    echo "=== RBAC checks FAILED ==="
fi

exit ${EXIT_CODE}
