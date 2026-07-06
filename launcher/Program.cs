using System.Diagnostics;

var rootDirectory = ResolveRepositoryRoot(AppContext.BaseDirectory);
var backendDirectory = Path.Combine(rootDirectory, "backend");
var packagedBackend = Path.Combine(backendDirectory, "dist", "server", "server.exe");
var venvPython = Path.Combine(backendDirectory, "venv", "Scripts", "python.exe");
var serverScript = Path.Combine(backendDirectory, "server.py");

var launchTarget = ResolveLaunchTarget(args, packagedBackend, venvPython, serverScript);
if (launchTarget is null)
{
    Console.Error.WriteLine("Unable to locate a packaged backend executable or Python backend entrypoint.");
    Environment.Exit(1);
    return;
}

Console.WriteLine($"Launching backend from: {launchTarget.FileName} {launchTarget.Arguments}".Trim());

using var process = new Process
{
    StartInfo = new ProcessStartInfo
    {
        FileName = launchTarget.FileName,
        Arguments = launchTarget.Arguments,
        WorkingDirectory = backendDirectory,
        UseShellExecute = false,
    },
    EnableRaisingEvents = true,
};

Console.CancelKeyPress += (_, eventArgs) =>
{
    eventArgs.Cancel = true;
    if (!process.HasExited)
    {
        process.Kill(entireProcessTree: true);
    }
};

process.Start();
process.WaitForExit();
Environment.ExitCode = process.ExitCode;

static LaunchTarget? ResolveLaunchTarget(string[] args, string packagedBackend, string venvPython, string serverScript)
{
    if (args.Length > 0)
    {
        var explicitTarget = args[0];
        if (File.Exists(explicitTarget))
        {
            if (explicitTarget.EndsWith(".py", StringComparison.OrdinalIgnoreCase))
            {
                var pythonExecutable = File.Exists(venvPython) ? venvPython : "python";
                return new LaunchTarget(pythonExecutable, Quote(explicitTarget));
            }

            return new LaunchTarget(explicitTarget, string.Join(" ", args.Skip(1).Select(Quote)));
        }
    }

    if (File.Exists(serverScript))
    {
        var pythonExecutable = File.Exists(venvPython) ? venvPython : "python";
        return new LaunchTarget(pythonExecutable, Quote(serverScript));
    }

    if (File.Exists(packagedBackend))
    {
        return new LaunchTarget(packagedBackend, string.Empty);
    }

    return null;
}

static string ResolveRepositoryRoot(string baseDirectory)
{
    var current = new DirectoryInfo(baseDirectory);
    while (current is not null)
    {
        if (Directory.Exists(Path.Combine(current.FullName, "backend")) && Directory.Exists(Path.Combine(current.FullName, "frontend")))
        {
            return current.FullName;
        }

        current = current.Parent;
    }

    return Directory.GetCurrentDirectory();
}

static string Quote(string value)
{
    return value.Contains(' ') ? $"\"{value}\"" : value;
}

internal sealed record LaunchTarget(string FileName, string Arguments);