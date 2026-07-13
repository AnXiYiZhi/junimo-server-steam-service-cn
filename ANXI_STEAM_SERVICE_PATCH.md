# Anxi Steam Service Patch Plan

This fork is used to publish a patched JunimoServer `steam-service` image for
slower Steam network environments. The panel should still provide the normal
"run one Linux command, then operate from the web UI" user flow.

## Goal

Fix this observed QR login failure:

```text
Choose authentication method:
  [1] Username & Password
  [2] QR Code (Steam Mobile App)
Choice [1]: 2
[SteamAuth:A0] Connecting... +1.8s
[SteamAuth:A0] QR authentication failed: The SteamClient instance must be connected. +2.0s
[SteamAuth:A0] Disconnected (UserInitiated: True) +0.0s
```

The failure happens before a QR code is generated. The current `steam-service`
calls `SteamClient.Connect()`, waits a hard-coded 2 seconds, then starts QR auth.
On slower Steam CM connections the client is still not connected, so SteamKit2
throws `The SteamClient instance must be connected`.

## Minimal Change Boundary

Intended code change:

```text
tools/steam-service/SteamAuthService.cs
```

Do not change these unless a test proves it is necessary:

```text
docker/Dockerfile
docker/modern/Dockerfile
tools/steam-service/Dockerfile
mod/
tools/discord-bot/
Junimo server runtime code
```

This fork should publish only the patched steam auth sidecar image. The Stardew
panel will later point its `steam-auth` service image to this patched image.

## Planned Source Change

Replace fixed sleeps after `SteamClient.Connect()` with a real wait for
`SteamClient.ConnectedCallback`, plus retry loops for:

- Steam CM disconnects before the client reaches the connected state.
- transient auth-session failures such as `TryAnotherCM` and
  `SteamKit2.AsyncJobFailedException` during QR / Steam Guard / credentials auth.

Current pattern to remove:

```csharp
_steamClient.Connect();
await Task.Delay(ConnectionEstablishmentDelay);
```

Planned helper:

```csharp
private static readonly TimeSpan SteamConnectTimeout =
    TimeSpan.FromSeconds(ParsePositiveIntEnv("STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS", 60));

private static readonly int SteamConnectMaxAttempts =
    ParsePositiveIntEnv("STEAM_CLIENT_CONNECT_RETRIES", 5);

private static readonly int AuthSessionMaxAttempts =
    ParsePositiveIntEnv("STEAM_AUTH_SESSION_RETRIES", 3);

private TaskCompletionSource<bool>? _connectedTcs;

private async Task ConnectAndWaitAsync()
{
    if (_steamClient.IsConnected)
    {
        return;
    }

    _connectedTcs = new TaskCompletionSource<bool>(
        TaskCreationOptions.RunContinuationsAsynchronously
    );

    Logger.Log($"{_logPrefix} Connecting...");
    _steamClient.Connect();

    var completed = await Task.WhenAny(
        _connectedTcs.Task,
        Task.Delay(SteamConnectTimeout)
    );

    if (completed != _connectedTcs.Task || !await _connectedTcs.Task)
    {
        throw new TimeoutException(
            $"SteamClient did not connect within {SteamConnectTimeout.TotalSeconds}s"
        );
    }
}
```

Callback changes:

```csharp
private void OnConnected(SteamClient.ConnectedCallback cb)
{
    Logger.Log($"{_logPrefix} Connected to Steam");
    _connectedTcs?.TrySetResult(true);
}

private void OnDisconnected(SteamClient.DisconnectedCallback cb)
{
    Logger.Log($"{_logPrefix} Disconnected (UserInitiated: {cb.UserInitiated})");
    _connectedTcs?.TrySetResult(false);
    IsLoggedIn = false;
    _loginTcs?.TrySetResult(false);
    MaybeStartReconnect("disconnected", cb.UserInitiated, EResult.OK);
}
```

Replace the hard-coded connect waits in:

```text
LoginWithCredentialsInsideLockAsync
LoginWithQrCodeInsideLockAsync
ConnectAndLoginAsync
LoginWithTokenInternalAsync reconnect branch
```

Also wrap QR and credentials auth sessions so `PollingWaitForResultAsync()` can be
retried when Steam asks the client to try another CM.

The default connection behavior is 60 seconds and 5 attempts. Auth sessions are
retried 3 times with a 5-second delay. They are configurable with:

```text
STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60
STEAM_CLIENT_CONNECT_RETRIES=5
STEAM_AUTH_SESSION_RETRIES=3
STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS=5
```

Do not log Steam passwords, refresh tokens, app tickets, or session files.

## Local Validation

From the repository root:

```powershell
cd E:\junimo-server-steam-service-cn
dotnet build tools\steam-service\SteamService.csproj -c Release
```

Build a local Docker image:

```powershell
docker build `
  -f tools/steam-service/Dockerfile `
  -t junimo-steam-service-cn:connect-wait-test `
  .
```

Test QR login in a clean volume:

```powershell
docker volume rm junimo-test-game junimo-test-session 2>$null

docker run --rm -it `
  -e GAME_DIR=/data/game `
  -e SESSION_DIR=/data/steam-session `
  -e STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60 `
  -e STEAM_CLIENT_CONNECT_RETRIES=5 `
  -e STEAM_AUTH_SESSION_RETRIES=3 `
  -e STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS=5 `
  -v junimo-test-game:/data/game `
  -v junimo-test-session:/data/steam-session `
  junimo-steam-service-cn:connect-wait-test setup
```

Choose QR login:

```text
Choice [1]: 2
```

Expected result:

```text
[SteamAuth:A0] Connecting...
[SteamAuth:A0] Connected to Steam
Scan this QR code with the Steam Mobile App:
...
Or open: <challenge-url>
Waiting for confirmation...
```

If the QR code appears, the original failure is fixed. After login succeeds,
confirm token export:

```powershell
docker run --rm -it `
  -e GAME_DIR=/data/game `
  -e SESSION_DIR=/data/steam-session `
  -v junimo-test-game:/data/game `
  -v junimo-test-session:/data/steam-session `
  junimo-steam-service-cn:connect-wait-test export-token
```

Optional regression checks:

```powershell
docker run --rm -it `
  -e GAME_DIR=/data/game `
  -e SESSION_DIR=/data/steam-session `
  -e STEAM_USERNAME=your_username `
  -e STEAM_PASSWORD=your_password `
  -e STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60 `
  -e STEAM_CLIENT_CONNECT_RETRIES=5 `
  -e STEAM_AUTH_SESSION_RETRIES=3 `
  -e STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS=5 `
  -v junimo-test-game:/data/game `
  -v junimo-test-session:/data/steam-session `
  junimo-steam-service-cn:connect-wait-test login
```

Do not paste real credentials into shell history on shared machines.

## Keeping The Patch Small

Before committing:

```powershell
git diff --stat
git diff -- tools/steam-service/SteamAuthService.cs ANXI_STEAM_SERVICE_PATCH.md
```

Expected touched files:

```text
ANXI_STEAM_SERVICE_PATCH.md
tools/steam-service/SteamAuthService.cs
```

No broad formatting pass. No dependency updates. No Dockerfile changes unless
the existing build is broken.

Use a focused commit message:

```text
fix(steam-service): wait for SteamClient connection before auth
```

## Automated sync validation and GitHub tag release

Upstream sync PRs run game-independent session migration tests and a static
invariant check for the Anxi connection timeout/retry patch. These checks use
no real Steam account and do not claim to validate the Steam network. Real
Steam-account and private-VPS tests are optional acceptance tests for this fork;
they do not block the automated fork tag or image release.

When no Anxi patch overlap exists, successful credential-free PR validation
automatically merge-commits the labeled `sync/upstream-*` PR. If
`needs-anxi-patch-review` is present, merging it manually with **Create a merge
commit** is the release approval. The closed-PR workflow revalidates the merged commit,
creates the exact recommended fork tag idempotently, and calls the reusable
publisher. Do not squash or rebase the PR: either method loses the upstream
ancestor relationship and the release workflow will reject it.

Manual exact tags remain a recovery path through `.github/workflows/publish-tag.yml`:

```powershell
git tag sdvd-server-v1.5.0-preview.125-anxi.1
git push origin sdvd-server-v1.5.0-preview.125-anxi.1
```

The workflow strictly parses the fork tag and publishes its normalized Docker tag, so the example above
publishes:

```text
anxiyizhi/junimo-steam-service-cn:1.5.0-preview.125-anxi.1
anxiyizhi/junimo-steam-service-cn:latest
crpi-9z3bkb9g7fxeohrg.cn-hangzhou.personal.cr.aliyuncs.com/anxi-panel/junimo-steam-service-cn:1.5.0-preview.125-anxi.1
crpi-9z3bkb9g7fxeohrg.cn-hangzhou.personal.cr.aliyuncs.com/anxi-panel/junimo-steam-service-cn:latest
ghcr.io/<github-owner>/junimo-steam-service-cn:1.5.0-preview.125-anxi.1
ghcr.io/<github-owner>/junimo-steam-service-cn:latest
```

Required GitHub repository secrets:

```text
DOCKERHUB_USERNAME
DOCKERHUB_TOKEN
ALIYUN_REGISTRY_USERNAME
ALIYUN_REGISTRY_PASSWORD
```

After the workflow succeeds, verify the versioned Docker Hub and GHCR tags. If
GitHub creates the package as private on first publish, open the package
settings and switch visibility to Public before using it as a public fallback.

```powershell
docker pull anxiyizhi/junimo-steam-service-cn:1.5.0-preview.125-anxi.1
docker pull ghcr.io/<github-owner>/junimo-steam-service-cn:1.5.0-preview.125-anxi.1
```

## Panel Integration Later

In `stardew-server-anxi-panel`, make the `steam-auth` image configurable:

```yaml
steam-auth:
  image: "${STEAM_SERVICE_IMAGE:-<dockerhub-namespace>/junimo-steam-service-cn:1.5.0-anxi.1}"
  environment:
    STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS: "${STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS:-60}"
    STEAM_CLIENT_CONNECT_RETRIES: "${STEAM_CLIENT_CONNECT_RETRIES:-5}"
    STEAM_AUTH_SESSION_RETRIES: "${STEAM_AUTH_SESSION_RETRIES:-3}"
    STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS: "${STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS:-5}"
```

Then write these defaults into the instance `.env`:

```text
STEAM_SERVICE_IMAGE=<dockerhub-namespace>/junimo-steam-service-cn:1.5.0-anxi.1
STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60
STEAM_CLIENT_CONNECT_RETRIES=5
STEAM_AUTH_SESSION_RETRIES=3
STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS=5
```

The user-facing install flow remains:

```text
run the panel container once
open the web panel
finish Steam auth, download, and server startup in the browser
```
