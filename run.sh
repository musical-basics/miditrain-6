#!/usr/bin/env bash

set -e

cd "$(dirname "$0")"

cd visualizer

pnpm install

echo "Booting visualizer UI on http://localhost:3000..."
pnpm dev
