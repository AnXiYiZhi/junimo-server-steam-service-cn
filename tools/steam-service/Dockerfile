# Built with the repo root as context (see docker-compose.yml) so the repo-level
# build props and code-style rules apply inside the image build too.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY Directory.Build.props CodeStyle.props .editorconfig ./
COPY tools/steam-service/*.csproj ./
RUN dotnet restore

COPY tools/steam-service/ .
ARG AUTH_VERSION=0.0.0-dev
RUN dotnet publish -c Release -o /app -p:Version=$AUTH_VERSION
    # -p:EnableCompressionInSingleFile=true \
    # -p:PublishSingleFile=true \
    # -p:PublishTrimmed=true \
    # -p:PublishAot=true \

FROM mcr.microsoft.com/dotnet/aspnet:10.0
ARG AUTH_VERSION=0.0.0-dev
ARG SOURCE_REVISION=unknown
ARG SOURCE_TREE_SHA256=unknown
ARG UPSTREAM_REVISION=f318717ac06a780b6b21080b0263c16278d8e6e1
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.version="$AUTH_VERSION" \
    org.opencontainers.image.revision="$SOURCE_REVISION" \
    org.opencontainers.image.created="$BUILD_DATE" \
    com.anxi-panel.source-tree-sha256="$SOURCE_TREE_SHA256" \
    com.anxi-panel.upstream-revision="$UPSTREAM_REVISION"
WORKDIR /app

# gosu drops privileges to the configured USER_ID:GROUP_ID in the entrypoint (see
# tools/steam-service/entrypoint.sh) so the shared game-data volume is owned by the operator's
# host user instead of root. Defaults to 1000:1000; USER_ID=0 keeps running as root.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app .
COPY tools/steam-service/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PORT=3001
ENV SESSION_DIR=/data/steam-session
ENV GAME_DIR=/data/game

EXPOSE 3001

# Healthcheck using dotnet to invoke a simple HTTP request (no curl/wget needed)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD dotnet SteamService.dll healthcheck || exit 1

# Default command is "serve" (HTTP API), but can be overridden:
#   docker run ... setup    # Interactive login + download
#   docker run ... login    # Just login
#   docker run ... download # Download game
#   docker run ... ticket   # Output app ticket
ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
