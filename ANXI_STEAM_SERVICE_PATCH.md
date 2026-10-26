# Anxi Steam Service Patch Plan

## 2026-10-26 upstream-aligned Auth release

The .140 Auth release is named `1.5.0-preview.140-anxi.1`, with fork tag `sdvd-server-v1.5.0-preview.140-anxi.1`. This keeps the upstream preview build visible and starts the fork patch sequence for that upstream version. The earlier local `1.5.0-anxi.3` image was an engineering candidate for the same .140 protocol; it is not the public release name.

`tools/steam-service/upstream-release.json` pins upstream `preview-1.5.0.140` to commit `f318717ac06a780b6b21080b0263c16278d8e6e1`. Upstream preview tags may be removed, so publication fetches this reviewed commit directly and still requires it to be a real ancestor of the release commit. A mismatched version or nonexact revision fails publication. The fork retains its connection wait, bounded connection/authentication retries and pure health/readiness behavior.

The authorized publication covers this Auth repository and its fixed image tag in the existing Docker Hub, GHCR and Alibaba Cloud repositories. Panel 0.7.3/0.8.0 publication remains deferred. The previous local dedicated-account migration and invitation-code acceptance are recorded below; final release identity and publication evidence will be added after verification.

## 2026-10-25 fixed local Auth candidate and Panel upgrade closeout

The Panel task built local `j140-closeout-20261025-auth:rc1` as `1.5.0-anxi.3`, with OCI index/content identity `sha256:f9a363a9fde9e786d5d43bdafe7a7e41c048fd35665172b8b378795d049b9f79`. Its 17-file engineering input manifest has source-tree SHA256 `a0046eae829c671fbfcfec9bbac14b2a6aecddc0a9a6a7cccba1bf95c0721c30`, upstream `f318717ac06a780b6b21080b0263c16278d8e6e1`, and the current dirty checkout's base revision `7905c209b2d14011cffd54f9a4d8658acebcc8e5`. This is not a clean formal release revision. Only the task's isolated loopback registry received the image; nothing was published externally.

Dockerfile now passes AUTH_VERSION to dotnet publish and records version, source revision/tree hash, upstream revision and UTC build time. The exact-tag publishing workflow passes those arguments and derives its source-tree digest from the archived service/build inputs. Workflow tests (17) and the patch invariant checker pass. A bounded 256 MiB probe of the same cached image, using two empty task volumes, returned health 200, Steam readiness 503 and game validation status 200; its container and volumes were removed. Evidence: `E:/stardew-server-anxi-panel/tmp/junimo140-closeout-20261025/auth-target-http-v2.json` and `auth-target-probe-result-v2.json`.

On 2026-10-26 the dedicated account and Steam Guard completed on the isolated old Panel. The real Auth 2 session migrated to the exact Auth 3 image above, became ready, and produced a valid nonempty invitation code after the real old-Panel Web upgrade and explicit .140 scope confirmation. An injected stop of the new Auth 3 target also exercised the unchanged production timeout: the whole group restored the original .125/Auth 2 stack and invitation-code availability. Save, user, custom Mod, session and unrelated-container checks passed. The user explicitly accepts successful invitation-code retrieval for this task; independent Steam/GOG player joining was not performed. Long-term token expiry/renewal is not claimed. Evidence is in the Panel task's `major-full-v5-success-*`, `major-full-v5-auth-failure-*` and `world-*-success.json` artifacts.

No tag, release, image promotion or external publishing workflow is authorized for this closeout. The engineering digest remains local. Formal Auth preparation must replace the dirty engineering source revision with a clean reviewed revision and its final published digest; the Panel manifest and affected candidate proofs must then be renewed. C-drive reserve was recovered through verified cache cleanup and archival, without pruning Docker or restarting shared services.

## 2026-10-15 local Junimo .140 adaptation (not released)

The service source is locally adapted to upstream `f318717ac06a780b6b21080b0263c16278d8e6e1` for the Panel's `.125 -> .140` work. The existing ConnectedCallback wait, connection/authentication retries and pure `/health` and `/steam/ready` contracts are retained. The service now includes upstream session selection, token maintenance, pinned-manifest content validation, non-root entrypoint and the associated validation/execstack helpers. Only `tools/steam-service` and its contract tests are adapted; the fork's server Mod is not synchronized by this task.

`AUTO_DOWNLOAD_ON_BOOT=false` disables implicit first-run downloads. Panel-managed Compose also sets `VALIDATE_ON_BOOT=false`, so a missing completion marker cannot silently trigger a public-branch game update. Explicit setup/download and manual validate requests remain separate operations. Creating the verified completion marker and migrating the shared game volume still require the Panel migration transaction; disabling automatic writers alone does not make an existing `.125` volume ready for `.140`.

Local image `junimo140-20261015-auth:local-v2` has image ID `sha256:b6186712daf4f2715c1a1cc62ad14294d81d87b1955b49d226810609a900d7b5`. Build and 9 contract tests passed, with HTTP proof for pure health, unavailable-account readiness, validate status and disabled bootstrap. Evidence is under `E:/stardew-server-anxi-panel/tmp/junimo140-20261015/`, including `auth-build-v2.log`, `auth-contract-tests-v2-restored.log`, `auth-final-http.json` and `auth-managed-bootstrap.json`. Login reached Steam Guard; the user explicitly deferred verification for this round, so login was stopped. No completed login, live renewal, license, real-client or game-download compatibility result is claimed. Isolated containers and session/game volumes were removed; the final engineering image and redacted evidence remain local. No image was pushed and no release workflow, tag or commit was created.

The following sections describe the previously published patch and its original plan.

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

## 2026-07-14 发布/兼容矩阵接手补充

本仓库在统一矩阵中的可追溯身份为：精确 fork image tag、buildx digest、`refs/tags/<Junimo upstream tag>` 与发布源码 revision。以上四项由发布成功后的可选 repository_dispatch 通知 Panel；不把本仓库自己的“发布成功”解释为五组件兼容性通过，Panel 端只能先记为 discovered。

影响文件：`.github/workflows/publish-steam-service.yml`、`tests/workflows/test_workflow_contracts.py`、本说明、`ANXI_UPSTREAM_SYNC_CN.md` 和 CI/CD 文档。运行时 anxi 补丁代码未修改。后续发布必须保留精确 tag/digest 与 upstreamRef 标签，若 tag 已指向不同 digest，应停止发布列车并调查，不能用 latest 或覆盖旧 tag 修复。
