#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
web_dir="${repo_dir}/control-center-web"
raw_dir="${web_dir}/output/showcase/raw"
asset_dir="${repo_dir}/assets/showcase"

if ! command -v cwebp >/dev/null 2>&1; then
  echo "cwebp is required to create the tracked Showcase images." >&2
  exit 1
fi

mkdir -p "${asset_dir}"

(
  cd "${web_dir}"
  pnpm exec playwright test --config=playwright.showcase.config.ts
)

for asset_name in pawos-agent-trace pawos-room-focus-satellite pawos-room-starfield; do
  cwebp -quiet -q 86 "${raw_dir}/${asset_name}.png" -o "${asset_dir}/${asset_name}.webp"
done

node "${script_dir}/write_pawos_showcase_manifest.mjs" "${repo_dir}"

echo "Showcase images: ${asset_dir}"
echo "Showcase video: ${web_dir}/output/showcase/pawos-showcase.webm"
