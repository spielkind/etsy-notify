#!/usr/bin/env bash
# Label a Trivy SARIF report so that GitHub code scanning shows which image a
# finding belongs to: sets the tool name and prefixes every message with the image.
# Usage: sarif-label.sh <report.sarif> <tool name> <image description>
set -euo pipefail
report=$1
tool=$2
image=$3
tmp=$(mktemp)
jq --arg tool "$tool" --arg image "$image" '
  .runs[].tool.driver.name = $tool
  | .runs[].tool.driver.fullName = $tool
  | .runs[].results[]?.message.text |= "Image: \($image)\n\(.)"
' "$report" > "$tmp"
mv "$tmp" "$report"
