# 上游同步与补丁保留说明

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
