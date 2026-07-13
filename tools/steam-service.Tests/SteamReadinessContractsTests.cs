using Xunit;

namespace SteamService.Tests;

public sealed class SteamReadinessContractsTests
{
    [Fact]
    public void HealthDoesNotTriggerLoginAndReportsState()
    {
        var probe = new FakeProbe { IsLoggedIn = false };

        var health = SteamReadinessContracts.Health([probe]);

        Assert.Equal("ok", health.Status);
        Assert.False(health.LoggedIn);
        Assert.Equal(0, probe.Calls);
    }

    [Fact]
    public async Task ReadyRequiresARealTicketFromTheProbe()
    {
        var result = await SteamReadinessContracts.ReadyAsync(
            new FakeProbe { IsLoggedIn = true, HasTicket = true },
            CancellationToken.None
        );

        Assert.Equal(200, result.StatusCode);
        Assert.True(result.Body.Ready);
        Assert.True(result.Body.HasTicket);
    }

    [Fact]
    public async Task ReadyFailureIsGenericAndDoesNotLeakClientMessage()
    {
        var result = await SteamReadinessContracts.ReadyAsync(
            new FakeProbe { Failure = new InvalidOperationException("refresh-token-secret") },
            CancellationToken.None
        );

        Assert.Equal(503, result.StatusCode);
        Assert.False(result.Body.Ready);
        Assert.DoesNotContain("refresh-token-secret", result.Body.Error);
    }

    private sealed class FakeProbe : ISteamReadinessProbe
    {
        public int AccountIndex => 0;
        public string Username => "test-user";
        public bool IsLoggedIn { get; init; }
        public string? SteamId => IsLoggedIn ? "123" : null;
        public bool HasTicket { get; init; }
        public Exception? Failure { get; init; }
        public int Calls { get; private set; }

        public Task<bool> EnsureTicketAsync(CancellationToken cancellationToken)
        {
            Calls++;
            return Failure == null ? Task.FromResult(HasTicket) : Task.FromException<bool>(Failure);
        }
    }
}
