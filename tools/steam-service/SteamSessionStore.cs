using System.Text.Json;

namespace SteamService;

public sealed record SteamSession(string Username, string RefreshToken);

/// <summary>
/// Owns the on-disk refresh-token session format. It never logs or returns raw file
/// contents; callers receive only the typed values they explicitly request.
/// </summary>
public sealed class SteamSessionStore
{
    private readonly string _logPrefix;

    public SteamSessionStore(string parentDirectory, string username, string logPrefix)
    {
        _logPrefix = logPrefix;
        AccountDirectory = Path.Combine(parentDirectory, username);
        Directory.CreateDirectory(AccountDirectory);
        MigrateLegacySession(parentDirectory, username);
    }

    public string AccountDirectory { get; }

    private string SessionFilePath => Path.Combine(AccountDirectory, "session.json");

    public bool Exists() => File.Exists(SessionFilePath);

    public void Save(string username, string refreshToken)
    {
        Directory.CreateDirectory(AccountDirectory);
        var tempPath = SessionFilePath + ".tmp";
        var json = JsonSerializer.Serialize(new { username, refreshToken });
        File.WriteAllText(tempPath, json);
        File.Move(tempPath, SessionFilePath, overwrite: true);
        Logger.Log($"{_logPrefix} Session saved for {username}");
    }

    public SteamSession? Load()
    {
        if (!File.Exists(SessionFilePath))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(SessionFilePath));
            var username = document.RootElement.GetProperty("username").GetString();
            var token = document.RootElement.GetProperty("refreshToken").GetString();
            return string.IsNullOrEmpty(username) || string.IsNullOrEmpty(token)
                ? null
                : new SteamSession(username, token);
        }
        catch (Exception ex) when (ex is IOException or JsonException or KeyNotFoundException)
        {
            Logger.Log($"{_logPrefix} Failed to load session metadata: {ex.GetType().Name}");
            return null;
        }
    }

    private void MigrateLegacySession(string parentDirectory, string username)
    {
        if (File.Exists(SessionFilePath))
        {
            return;
        }

        var legacyPath = Path.Combine(parentDirectory, $"session-{username}.json");
        if (!File.Exists(legacyPath))
        {
            return;
        }

        try
        {
            File.Move(legacyPath, SessionFilePath);
            Logger.Log($"{_logPrefix} Migrated session from old format");
        }
        catch (IOException ex)
        {
            Logger.Log($"{_logPrefix} Session migration failed: {ex.GetType().Name}");
        }
    }
}
