# 上游同步与补丁保留说明

## 2026-10-26 .140 Auth 正式发布

- 上游命名保持可见：镜像为 `1.5.0-preview.140-anxi.1`，annotated tag为 `sdvd-server-v1.5.0-preview.140-anxi.1`，指向真实包含上游 `f318717ac06a780b6b21080b0263c16278d8e6e1` 的提交 `db3f7d53b8e7705b01bbf5a87633e07dabdd34a4`。
- 三仓固定版本同一digest：`sha256:4649205b292a89dee5073614408bc7fdbbe01886a597beb38d24e906ddba20f6`。成功发布证明run为 `40284240063`，复用首次构建的原平台镜像，没有重建或移动tag；阿里云精确digest回拉HTTP冒烟通过。旧工程名 `1.5.0-anxi.3` 仅保留历史说明。
- `upstream-release.json` 以审阅版本/SHA固定来源，预览tag被上游清理后仍可复验，并保留真实祖先检查。ACR不支持的空配置证明附件默认禁用；恢复流程用预装Skopeo保留原manifest digest。国内连接/认证重试及纯health/readiness保持。
- 本次仅发布Auth仓库/镜像，Panel继续不发布。后续073升级中心与080运行栈对接需要使用以上正式身份并更新验证，不复用旧工程digest作为正式证明。

## 2026-10-15 本地 .140 配套适配

本轮只在本地将 `tools/steam-service` 适配到固定上游 `f318717ac06a780b6b21080b0263c16278d8e6e1`，保留国内网络连接等待/重试和现有纯 health/readiness 契约，并接入 session 枚举、token 维护、固定已安装 manifest 的内容校验、非 root entrypoint 及辅助类。没有同步本仓 server Mod，也没有改动已有发布 workflow 草稿；当前 Git HEAD/分支不变，未提交、推送、打 tag 或发布镜像。

新增 `AUTO_DOWNLOAD_ON_BOOT=false`，与 `VALIDATE_ON_BOOT=false` 配合阻止 Panel 管理卷的开机隐式写入。显式安装、共享组停写、固定 build/完成 marker、patched SMAPI 和完整回滚仍由 Panel 后续事务接线，不能据这两个开关认定迁移完成。当前 Panel 推荐仍是 `.125 + anxi.2`；用户本轮明确跳过 Steam Guard，已停止登录；隔离容器和 session/game 卷已回收。最终本地工程镜像与脱敏证据、通过范围和真实客户端边界见本文同目录 `ANXI_STEAM_SERVICE_PATCH.md` 的 2026-10-15 记录。

以下章节保留已发布旧补丁的原始范围与同步方案。

这个 fork 的目标不是维护一个完整的 JunimoServer 分支，而是发布一个更适合慢 Steam 网络环境的 `steam-service` 镜像。

## 当前补丁范围

我们只修改 `steam-service` 的 SteamClient 连接等待逻辑：

```text
tools/steam-service/SteamAuthService.cs
```

当前补丁解决的问题：

```text
SteamClient.Connect()
固定等待 2 秒
SteamClient 还没 connected
QR / 账号密码 / refresh token 认证提前开始
报错：The SteamClient instance must be connected
```

现在的行为：

```text
SteamClient.Connect()
等待 SteamKit2 ConnectedCallback
默认最长等 60 秒
默认最多重试 5 次
connected 后再继续 QR / 账号密码 / refresh token 登录
如果 QR / Steam Guard / 账号密码认证过程中出现 TryAnotherCM，会重连后重新发起认证会话
```

可配置环境变量：

```text
STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60
STEAM_CLIENT_CONNECT_RETRIES=5
STEAM_AUTH_SESSION_RETRIES=3
STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS=5
```

## 2026-07 自动同步与发布契约

- `.github/workflows/sync-upstream-tag.yml` 每 6 小时分别按数字版本选择最新
  stable（`sdvd-server-vX.Y.Z`）和 preview（`preview-X.Y.Z.N`）；手动运行只接受
  已存在的精确 tag。
- 上游 tag 只 fetch 到 `refs/upstream-tags/<tag>`。同步分支固定为
  `sync/upstream-<normalized-tag>`，从 `origin/master` 创建并以 `--no-ff` merge
  保留上游祖先关系。冲突直接失败，不自动选择 ours/theirs，也不自动合并 PR。
- PR 会列出上游范围、fork 专有提交和文件、重叠文件、推荐 fork tag 与验证命令。
  上游若同时修改 fork 涉及的 `tools/steam-service/**`，添加
  `needs-anxi-patch-review`；重复运行更新已有 PR。
- 同步 PR 使用只读权限验证：编译与测试 steam-service、检查格式和 Anxi 补丁、
  本地构建 Docker 镜像但不推送。此流程不取得 Steam、VPS 或 registry secrets。
- 上游 VPS E2E 所需的 `SDVD_DOCKER_HOSTS` 不属于 fork。secret 不存在或格式无效时，
  workflow 在 checkout/keyscan 前明确跳过，不运行测试，也不上传空 artifact。
- 没有补丁重叠时，PR 会添加 `auto-upstream-sync`；无凭据验证通过后，受信任
  workflow 会再次核对相同 head SHA、同仓库来源和标签，然后自动用 merge commit 合并。
- 带 `needs-anxi-patch-review` 的 PR 永不自动合并；人工检查后必须使用
  **Create a merge commit**。不要使用 squash 或 rebase，否则会丢失上游祖先关系。
- 合并后 workflow 会在 `master` 上重新执行无凭据测试和 Docker build；通过后自动、
  幂等地创建 `sdvd-server-v1.5.0-preview.125-anxi.1`，并直接调用受信任发布流程，
  发布 Docker tag `1.5.0-preview.125-anxi.1` 到 Docker Hub、ACR 和 GHCR，再创建
  GitHub Release。已有 tag 指向不同提交时拒绝覆盖。
- 真实 Steam 账号和私有 VPS E2E 在本 fork 中为可选验收，不阻止自动 tag 和发布。
- 本阶段不自动修改 Panel 仓库的推荐版本对；跨仓库联动保留给后续阶段。

## 同步上游的原则

同步上游时，目标是：

```text
上游其他功能全部跟进
保留我们对 steam-service 连接等待的补丁
尽量不扩大 fork 差异
```

不要为了同步上游去改这些目录，除非上游改动导致 steam-service 构建失败：

```text
mod/
docker/
tools/discord-bot/
tests/
docs/
```

我们发布时也只发布 patched `steam-service` 镜像，不发布完整 Junimo server 镜像。

## 推荐同步流程

在本地仓库执行：

```powershell
cd E:\junimo-server-steam-service-cn
git fetch upstream
git checkout master
git status
```

确认工作区干净后，合并上游：

```powershell
git merge upstream/master
```

如果没有冲突，直接测试：

```powershell
docker build --progress=plain `
  -f tools/steam-service/Dockerfile `
  -t junimo-steam-service-cn:upstream-sync-test `
  .
```

如果构建通过，再做 QR 短测：

```powershell
"2`n" | docker run --rm -i `
  -e GAME_DIR=/data/game `
  -e SESSION_DIR=/data/steam-session `
  -e STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60 `
  -e STEAM_CLIENT_CONNECT_RETRIES=5 `
  -v junimo-test-game:/data/game `
  -v junimo-test-session:/data/steam-session `
  junimo-steam-service-cn:upstream-sync-test setup
```

只要能看到类似输出，就说明补丁仍然生效：

```text
[SteamAuth:A0] Connecting... (1/5)
[SteamAuth:A0] Connected to Steam
Scan this QR code with the Steam Mobile App:
Or open: https://s.team/q/...
```

## 如果合并时有冲突

最可能冲突的文件：

```text
tools/steam-service/SteamAuthService.cs
```

处理原则：

1. 优先保留上游新增功能和 bugfix。
2. 找到所有类似逻辑：

```csharp
_steamClient.Connect();
await Task.Delay(...);
```

3. 确保认证前仍然调用：

```csharp
await ConnectAndWaitAsync();
```

4. 确保 `OnConnected` 会完成连接等待：

```csharp
_connectedTcs?.TrySetResult(true);
```

5. 确保 `OnDisconnected` 会失败当前连接等待：

```csharp
_connectedTcs?.TrySetResult(false);
```

6. 保留环境变量：

```text
STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS
STEAM_CLIENT_CONNECT_RETRIES
STEAM_AUTH_SESSION_RETRIES
STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS
```

冲突解决后检查：

```powershell
rg -n "ConnectionEstablishmentDelay|Task.Delay\\(ConnectionEstablishmentDelay\\)|ConnectAndWaitAsync|STEAM_CLIENT_CONNECT" tools\steam-service\SteamAuthService.cs
```

期望：

```text
不再有 ConnectionEstablishmentDelay
不再有 Task.Delay(ConnectionEstablishmentDelay)
仍然有 ConnectAndWaitAsync
仍然有 STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS
仍然有 STEAM_CLIENT_CONNECT_RETRIES
仍然有 STEAM_AUTH_SESSION_RETRIES
仍然有 STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS
```

## 同步后的提交

同步上游后建议单独提交：

```powershell
git add .
git commit -m "chore: sync upstream JunimoServer"
git push origin master
```

如果同步时顺手修了补丁冲突，提交信息可以写：

```powershell
git commit -m "chore: sync upstream and reapply steam connect wait patch"
```

## 发布新镜像

同步并验证后，用新的补丁版本号发布：

```powershell
docker login

docker buildx build `
  --platform linux/amd64 `
  -f tools/steam-service/Dockerfile `
  -t <dockerhub-namespace>/junimo-steam-service-cn:1.5.0-anxi.2 `
  --push `
  .
```

不要直接覆盖已经在用户环境使用的旧版本号。推荐每次发布递增：

```text
1.5.0-anxi.1
1.5.0-anxi.2
1.5.0-anxi.3
```

确认新版可用后，再决定是否更新 `latest`：

```powershell
docker buildx build `
  --platform linux/amd64 `
  -f tools/steam-service/Dockerfile `
  -t <dockerhub-namespace>/junimo-steam-service-cn:1.5.0-anxi.2 `
  -t <dockerhub-namespace>/junimo-steam-service-cn:latest `
  --push `
  .
```

## 面板侧升级

面板里不要硬编码 `latest`，推荐写固定版本：

```text
STEAM_SERVICE_IMAGE=<dockerhub-namespace>/junimo-steam-service-cn:1.5.0-anxi.2
STEAM_CLIENT_CONNECT_TIMEOUT_SECONDS=60
STEAM_CLIENT_CONNECT_RETRIES=5
STEAM_AUTH_SESSION_RETRIES=3
STEAM_AUTH_SESSION_RETRY_DELAY_SECONDS=5
```

这样用户环境可复现，也方便回滚。

## 2026-07-14 统一发布列车接手说明

上游同步与精确 fork tag 仍遵循：发现 tag -> 同步 PR -> anxi 补丁人工确认 -> 合并后重新验证 -> 创建精确 fork tag -> 调用 `publish-steam-service.yml`。发布工作流现在只推精确版本 tag，并以 buildx 输出记录跨 registry 镜像 digest；不再更新 `latest`。

发布成功后可用 `PANEL_REPOSITORY_DISPATCH_TOKEN` 向 `PANEL_REPOSITORY` 发送 `steam-auth-cn-published`。payload 只包含 `refs/tags/<upstream-tag>`、精确 imageTag、digest、完整 source revision。Panel 只生成 discovered PR，重复 payload 使用相同身份，不直接推荐。缺少 token/变量时通知跳过，不把 GitHub/registry/Steam 凭据写入日志或 payload。

验证：`python -m unittest discover -s tests/workflows -p 'test_*.py' -v` 覆盖 exact tag、provenance、最小公开 payload 和无 `pull_request_target`；`npm test` 覆盖已有工作流脚本。首次联动发布前仍需管理员创建最小权限 token、配置目标仓库变量，并在两个仓库的受保护环境/分支规则中启用人工 review。
