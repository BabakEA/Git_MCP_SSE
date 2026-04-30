#!/usr/bin/env bash
set -euo pipefail

docker build -t git-mcp-bridge:latest .
docker run --rm -p 9090:9090 --env-file .env git-mcp-bridge:latest