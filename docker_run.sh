#docker run -p 9090:9090 \
#  -e GITHUB_HOST=https://your-ghe.example.com \
#  git-mcp-bridge:latest
#
#
#.env :>
# GITHUB_HOST=https://your-ghe.example.com
#
# Legacy host compatibility is also supported:
# GITHUB_API_URL=https://your-ghe.example.com/api/v3

# Client agents should authenticate with Authorization: Bearer <token>
# or use OAuth when they connect to the MCP HTTP endpoint.

docker run -p 9090:9090 \
  --rm \
  --env-file .env \
  git-mcp-bridge:latest


