#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: %s <ssh-target> [remote-plugin-dir]\n' "$0" >&2
  printf 'Example: %s deck@steamdeck.local\n' "$0" >&2
  exit 2
fi

ssh_target="$1"
remote_dir="${2:-~/homebrew/plugins/decky-ai-assistant}"

if [[ ! "$remote_dir" =~ ^[A-Za-z0-9_./~-]+$ ]]; then
  printf 'Remote plugin dir contains unsupported shell characters: %s\n' "$remote_dir" >&2
  exit 2
fi

required_files=(
  "dist/index.js"
  "main.py"
  "package.json"
  "plugin.json"
  "LICENSE"
)

for file_path in "${required_files[@]}"; do
  if [[ ! -f "$file_path" ]]; then
    printf 'Missing required file: %s\n' "$file_path" >&2
    printf 'Run: npm exec --yes pnpm@9 -- run build\n' >&2
    exit 1
  fi
done

# The allowlist above restricts $remote_dir to path-safe characters (no shell
# metacharacters), so interpolating it into the remote command cannot inject.
# A leading "~" is left unquoted so the remote shell expands it to $HOME,
# matching how the rsync targets below resolve the same path.
ssh -o BatchMode=yes -o ConnectTimeout=10 "$ssh_target" \
  "mkdir -p $remote_dir/packages/core $remote_dir/packages/mcp-server"

rsync -az \
  main.py package.json plugin.json LICENSE README.md dist \
  "$ssh_target:$remote_dir/"

rsync -az packages/core/src "$ssh_target:$remote_dir/packages/core/"
rsync -az packages/mcp-server/src "$ssh_target:$remote_dir/packages/mcp-server/"

printf 'Deployed smoke plugin to %s:%s\n' "$ssh_target" "$remote_dir"
printf 'Reload Decky on the Steam Deck, then open Decky AI Assistant from Quick Access.\n'
