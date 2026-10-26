using System.Text.Json;
using Xunit;

namespace SteamService.Tests;

public sealed class Junimo140ProtocolContractsTests
{
    [Fact]
    public async Task FailedContentValidationReleasesStartupGate()
    {
        var validator = new GameContentValidator();
        Assert.False(validator.Current.IsTerminal);
        await validator.RunAsync(() =>
            Task.FromException<string?>(new IOException("fixture corruption"))
        );
        Assert.True(validator.Current.IsTerminal);
        Assert.Equal(GameContentValidator.State.Failed, validator.Current.State);
        Assert.NotNull(validator.Current.StartedAt);
        Assert.NotNull(validator.Current.FinishedAt);
        var wire = JsonSerializer.Serialize(validator.Current.ToJson());
        Assert.Contains("\"status\":\"failed\"", wire);
        await validator.RunAsync(() => Task.FromResult<string?>("repaired"));
        Assert.Equal(GameContentValidator.State.Completed, validator.Current.State);
    }

    [Fact]
    public void DisabledValidationIsTerminalAndCannotHoldServerBoot()
    {
        var validator = new GameContentValidator();
        validator.MarkDisabled("Panel owns shared-volume maintenance");
        Assert.True(validator.Current.IsTerminal);
        Assert.Equal(GameContentValidator.State.Disabled, validator.Current.State);
    }

    [Fact]
    public void SessionPickerSelectsExplicitAccountOrFreshLogin()
    {
        var sessions = new List<(string username, string path, DateTime writtenUtc)>
        {
            ("newer", "/test/newer/session.json", DateTime.UtcNow),
            ("older", "/test/older/session.json", DateTime.UtcNow.AddDays(-1)),
        };
        Assert.True(SteamAuthService.TryResolveSessionChoice(sessions, "2", out var chosen));
        Assert.Equal("older", chosen);
        Assert.True(SteamAuthService.TryResolveSessionChoice(sessions, "n", out chosen));
        Assert.Null(chosen);
        Assert.False(SteamAuthService.TryResolveSessionChoice(sessions, "3", out chosen));
    }

    [Fact]
    public void MissingAndCorruptSessionsDoNotCountAsUsableSessions()
    {
        var directory = Path.Combine(
            Path.GetTempPath(),
            "steam-session-fixture-" + Guid.NewGuid().ToString("N")
        );
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "session.json");
            Assert.Null(SteamAuthService.TryLoadSession(path));
            File.WriteAllText(path, "{broken");
            Assert.Null(SteamAuthService.TryLoadSession(path));
            File.WriteAllText(path, "{\"username\":\"fixture\",\"refreshToken\":\"\"}");
            Assert.Null(SteamAuthService.TryLoadSession(path));
        }
        finally
        {
            Directory.Delete(directory, true);
        }
    }
}
