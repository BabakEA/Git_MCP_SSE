FROM alpine/git:2.49.1 AS source

ARG GITHUB_MCP_REPO=https://github.com/github/github-mcp-server.git
ARG GITHUB_MCP_REF=main

WORKDIR /src
RUN git clone --depth 1 --branch "${GITHUB_MCP_REF}" "${GITHUB_MCP_REPO}" github-mcp-server

FROM node:20-alpine AS ui-build

WORKDIR /src

COPY --from=source /src/github-mcp-server/ui/package*.json /src/github-mcp-server/ui/
RUN cd /src/github-mcp-server/ui && npm ci

COPY --from=source /src/github-mcp-server/ui/ /src/github-mcp-server/ui/
RUN mkdir -p /src/github-mcp-server/pkg/github/ui_dist && \
	cd /src/github-mcp-server/ui && npm run build

FROM golang:1.25.9-alpine AS build

WORKDIR /src/github-mcp-server
RUN apk add --no-cache git

COPY --from=source /src/github-mcp-server/ /src/github-mcp-server/
COPY --from=ui-build /src/github-mcp-server/pkg/github/ui_dist/ /src/github-mcp-server/pkg/github/ui_dist/

RUN CGO_ENABLED=0 go build -o /bin/github-mcp-server ./cmd/github-mcp-server

FROM alpine:3.22

RUN apk add --no-cache ca-certificates

WORKDIR /server

COPY --from=build /bin/github-mcp-server /usr/local/bin/github-mcp-server
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 9090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
	CMD wget -q -O - http://127.0.0.1:9090/.well-known/oauth-protected-resource >/dev/null 2>&1 || exit 1

ENV PORT=9090 \
	MCP_BASE_URL="" \
	MCP_BASE_PATH="" \
	MCP_READ_ONLY="false" \
	MCP_SCOPE_CHALLENGE="false" \
	MCP_TOOLSETS="" \
	MCP_TOOLS="" \
	MCP_EXCLUDE_TOOLS=""

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]