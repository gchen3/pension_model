#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/dev/create_issue.sh --title-file PATH --body-file PATH [--repo OWNER/REPO] [--label LABEL ...]

Creates a GitHub issue with a title read from a file and a body read from a file.
This avoids fragile shell quoting for long Markdown issue bodies.

Options:
  --title-file PATH   File containing the issue title
  --body-file PATH    File containing the issue body
  --repo OWNER/REPO   GitHub repo; defaults to origin remote if omitted
  --label LABEL       Label to apply; may be repeated
  --help              Show this help text
EOF
}

infer_repo() {
  local remote_url
  remote_url="$(git remote get-url origin)"

  case "$remote_url" in
    https://github.com/*)
      remote_url="${remote_url#https://github.com/}"
      remote_url="${remote_url%.git}"
      printf '%s\n' "$remote_url"
      ;;
    git@github.com:*)
      remote_url="${remote_url#git@github.com:}"
      remote_url="${remote_url%.git}"
      printf '%s\n' "$remote_url"
      ;;
    *)
      printf 'Could not infer GitHub repo from origin remote: %s\n' "$remote_url" >&2
      exit 1
      ;;
  esac
}

repo=""
title_file=""
body_file=""
declare -a labels=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --title-file)
      title_file="${2:-}"
      shift 2
      ;;
    --body-file)
      body_file="${2:-}"
      shift 2
      ;;
    --label)
      labels+=("${2:-}")
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ -n "$title_file" ]] || { printf 'Missing --title-file\n' >&2; exit 1; }
[[ -n "$body_file" ]] || { printf 'Missing --body-file\n' >&2; exit 1; }
[[ -f "$title_file" ]] || { printf 'Title file not found: %s\n' "$title_file" >&2; exit 1; }
[[ -f "$body_file" ]] || { printf 'Body file not found: %s\n' "$body_file" >&2; exit 1; }

if [[ -z "$repo" ]]; then
  repo="$(infer_repo)"
fi

title="$(tr -d '\r' < "$title_file")"

args=(issue create -R "$repo" -t "$title" -F "$body_file")
for label in "${labels[@]}"; do
  args+=(--label "$label")
done

gh "${args[@]}"
