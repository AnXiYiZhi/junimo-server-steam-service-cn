using System.Text.Json.Serialization;

namespace SteamService;

public interface ISteamReadinessProbe
{
    int AccountIndex { get; }
    string Username { get; }
    bool IsLoggedIn { get; }
    string? SteamId { get; }
    Task<bool> EnsureTicketAsync(CancellationToken cancellationToken);
}

public sealed record SteamHealthAccount(
    [property: JsonPropertyName("index")] int Index,
    [property: JsonPropertyName("username")] string Username,
    [property: JsonPropertyName("logged_in")] bool LoggedIn,
    [property: JsonPropertyName("steam_id")] string? SteamId
);

public sealed record SteamHealthResponse(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("logged_in")] bool LoggedIn,
    [property: JsonPropertyName("timestamp")] string Timestamp,
    [property: JsonPropertyName("accounts")] IReadOnlyList<SteamHealthAccount> Accounts
);

public sealed record SteamReadyResponse(
    [property: JsonPropertyName("ready")] bool Ready,
    [property: JsonPropertyName("account")] int? Account = null,
    [property: JsonPropertyName("username")] string? Username = null,
    [property: JsonPropertyName("steam_id")] string? SteamId = null,
    [property: JsonPropertyName("has_ticket")] bool HasTicket = false,
    [property: JsonPropertyName("error")] string? Error = null
);

public static class SteamReadinessContracts
{
    public static SteamHealthResponse Health(IEnumerable<ISteamReadinessProbe> probes)
    {
        var accounts = probes
            .OrderBy(probe => probe.AccountIndex)
            .Select(probe => new SteamHealthAccount(
                probe.AccountIndex,
                probe.Username,
                probe.IsLoggedIn,
                probe.SteamId
            ))
            .ToArray();
        return new SteamHealthResponse(
            "ok",
            accounts.All(account => account.LoggedIn),
            DateTime.UtcNow.ToString("o"),
            accounts
        );
    }

    public static async Task<(int StatusCode, SteamReadyResponse Body)> ReadyAsync(
        ISteamReadinessProbe probe,
        CancellationToken cancellationToken
    )
    {
        try
        {
            var hasTicket = await probe.EnsureTicketAsync(cancellationToken);
            return (
                200,
                new SteamReadyResponse(
                    true,
                    probe.AccountIndex,
                    probe.Username,
                    probe.SteamId,
                    hasTicket
                )
            );
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            return (503, new SteamReadyResponse(false, Error: "Steam account is not ready"));
        }
    }
}

public sealed class SteamAuthReadinessProbe(
    SteamAuthService service,
    SteamAuthService.LoginConfig? loginConfig,
    uint appId
) : ISteamReadinessProbe
{
    public int AccountIndex => service.AccountIndex;
    public string Username => service.Username;
    public bool IsLoggedIn => service.IsLoggedIn;
    public string? SteamId => service.SteamId;

    public async Task<bool> EnsureTicketAsync(CancellationToken cancellationToken)
    {
        await service.EnsureLoggedInAsync(loginConfig, cancellationToken);
        var ticket = await service.GetAppTicketAsync(appId);
        return !string.IsNullOrEmpty(ticket.TicketBase64);
    }
}
