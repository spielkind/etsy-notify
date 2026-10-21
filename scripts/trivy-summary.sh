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
    echo "No fixable CRITICAL/HIGH/MEDIUM vulnerabilities found ✓"
  else
    jq -r '[.Results[]?.Vulnerabilities[]?.Severity]
      | "**\(length) fixable vulnerabilities:** "
        + ([("CRITICAL", "HIGH", "MEDIUM") as $s
            | (map(select(. == $s)) | length) as $n
            | select($n > 0) | "\($n) \($s | ascii_downcase)"] | join(", "))' "$report"
    echo
    echo "| Severity | Package | Installed | Fixed | ID |"
    echo "|---|---|---|---|---|"
    jq -r '[.Results[]?.Vulnerabilities[]?]
      | sort_by({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}[.Severity] // 3)[]
      | "| \(.Severity) | \(.PkgName) | \(.InstalledVersion) | \(.FixedVersion) | \(if .PrimaryURL then "[\(.VulnerabilityID)](\(.PrimaryURL))" else .VulnerabilityID end) |"' "$report"
    echo
    echo "Critical and high findings fail builds of pull requests, main and releases."
    echo "Details: ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/security/code-scanning"
  fi
} >> "$GITHUB_STEP_SUMMARY"
