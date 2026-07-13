using System.Text.Json;
using Xunit;

namespace SteamService.Tests;

public sealed class SteamSessionStoreTests : IDisposable
{
    private readonly string _root = Path.Combine(
        Path.GetTempPath(),
        $"steam-session-{Guid.NewGuid():N}"
    );

    [Fact]
    public void SaveAndLoadPreservesRefreshToken()
    {
        var store = new SteamSessionStore(_root, "alice", "[test]");
        store.Save("alice", "secret-refresh-token");

        Assert.Equal(new SteamSession("alice", "secret-refresh-token"), store.Load());
        Assert.True(File.Exists(Path.Combine(_root, "alice", "session.json")));
    }

    [Fact]
    public void LegacyFlatSessionIsMigratedWithoutChangingContent()
    {
        Directory.CreateDirectory(_root);
        var legacy = Path.Combine(_root, "session-alice.json");
        File.WriteAllText(
            legacy,
            JsonSerializer.Serialize(new { username = "alice", refreshToken = "legacy-token" })
        );

        var store = new SteamSessionStore(_root, "alice", "[test]");

        Assert.Equal(new SteamSession("alice", "legacy-token"), store.Load());
        Assert.False(File.Exists(legacy));
    }

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }
}
