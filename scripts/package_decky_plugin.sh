#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

cd "$repo_root"

plugin_name="$(
  node -e 'const pkg = require("./package.json"); process.stdout.write(pkg.name);'
)"
plugin_version="$(
  node -e 'const pkg = require("./package.json"); process.stdout.write(pkg.version);'
)"

if [[ ! "$plugin_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
  printf 'Unsupported plugin package name: %s\n' "$plugin_name" >&2
  exit 2
fi

archive_name="${plugin_name}-v${plugin_version}.zip"
out_dir="$repo_root/out"
archive_path="$out_dir/$archive_name"
stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/${plugin_name}.package.XXXXXX")"
bundle_dir="$stage_dir/$plugin_name"
stage_archive="$stage_dir/$archive_name"

npm exec --yes pnpm@9 -- install --frozen-lockfile
npm exec --yes pnpm@9 -- run check
npm exec --yes pnpm@9 -- run build

required_files=(
  "dist/index.js"
  "main.py"
  "package.json"
  "plugin.json"
  "LICENSE"
  "README.md"
  "AGENTS.md"
  "CLAUDE.md"
  "CONTRIBUTING.md"
  "ROADMAP.md"
)

for file_path in "${required_files[@]}"; do
  if [[ ! -f "$file_path" ]]; then
    printf 'Missing required plugin package file: %s\n' "$file_path" >&2
    exit 1
  fi
done

required_dirs=(
  "agent-pack"
  "docs"
)

for dir_path in "${required_dirs[@]}"; do
  if [[ ! -d "$dir_path" ]]; then
    printf 'Missing required plugin package directory: %s\n' "$dir_path" >&2
    exit 1
  fi
done

mkdir -p "$bundle_dir/packages/core" "$bundle_dir/packages/mcp-server"

mkdir -p "$bundle_dir/dist"
cp dist/index.js "$bundle_dir/dist/"
cp \
  main.py \
  package.json \
  plugin.json \
  LICENSE \
  README.md \
  AGENTS.md \
  CLAUDE.md \
  CONTRIBUTING.md \
  ROADMAP.md \
  "$bundle_dir/"
rsync -a --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
  packages/core/src "$bundle_dir/packages/core/"
rsync -a --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
  packages/mcp-server/src "$bundle_dir/packages/mcp-server/"
rsync -a --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
  agent-pack "$bundle_dir/"
rsync -a --exclude '.DS_Store' \
  docs "$bundle_dir/"

mkdir -p "$out_dir"
(
  cd "$stage_dir"
  find "$plugin_name" -type f -exec touch -t 202601010000 {} +
  zip -X -r "$stage_archive" "$plugin_name" >/dev/null
)

unzip -t "$stage_archive" >/dev/null
mkdir -p "$out_dir"
cp "$stage_archive" "$archive_path"

printf 'Created %s\n' "$archive_path"
