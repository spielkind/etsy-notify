#!/usr/bin/env bash
# Append the result of a Trivy JSON report to the GitHub job summary.
# Usage: trivy-summary.sh <description> <report.json>
set -euo pipefail
description=$1
report=$2
{
  echo "### Vulnerability scan: $description"
  echo
  if [[ ! -s "$report" ]]; then
    echo "⚠️ No scan report found – the scan did not run."
    exit 0
  fi
  count=$(jq '[.Results[]?.Vulnerabilities[]?] | length' "$report")
  if [[ "$count" == 0 ]]; then
    echo "No fixable CRITICAL/HIGH vulnerabilities found ✓"
  else
    echo "**$count fixable CRITICAL/HIGH vulnerabilities:**"
    echo
    echo "| Severity | Package | Installed | Fixed | ID |"
    echo "|---|---|---|---|---|"
    jq -r '.Results[]?.Vulnerabilities[]?
      | "| \(.Severity) | \(.PkgName) | \(.InstalledVersion) | \(.FixedVersion) | [\(.VulnerabilityID)](\(.PrimaryURL // "")) |"' "$report"
    echo
    echo "Details: ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/security/code-scanning"
  fi
} >> "$GITHUB_STEP_SUMMARY"
