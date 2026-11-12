# Registers this project and one of its environments in the local Hop
# installation (hop-config.json), from config/env/<env>.list, for local
# development with Hop GUI on Windows (Windows PowerShell 5.1 or PowerShell 7).
# Lines /run/secrets/<name> of the manifest are mapped to <secrets-dir>\<name>,
# or <secrets-dir>\<name>.json. Safe to re-run: an existing environment gets
# the current file list. Close Hop GUI before running it.
# Same behaviour, checks and exit codes as tools/serasoft-register-env.sh.
# See README.md (src/template/README.md in projects), "Registering a local
# environment on Windows". This file must stay ASCII (Windows PowerShell 5.1).
#
# Usage: tools\serasoft-register-env.ps1 -Env <env> [-Project <name>] [-HopEnv <name>] [-SecretsDir <dir>] [-HopHome <dir>]

$UsageText = 'usage: tools\serasoft-register-env.ps1 -Env <env> [-Project <name>] [-HopEnv <name>] [-SecretsDir <dir>] [-HopHome <dir>]'

function Exit-Usage { [Console]::Error.WriteLine($UsageText); exit 64 }
function Exit-Error([string]$Message) { [Console]::Error.WriteLine("ERROR: $Message"); exit 1 }
function Write-Warn([string]$Message) { [Console]::Error.WriteLine("WARNING: $Message") }

# Parameters parsed by hand: an unknown or incomplete parameter exits with 64,
# like the Bash script (a param() block would fail with a PowerShell error).
$opt = @{ Env = ''; Project = ''; HopEnv = ''; SecretsDir = ''; HopHome = '' }
$i = 0
while ($i -lt $args.Count) {
  $key = [string]$args[$i]
  if (-not $key.StartsWith('-') -or ($i + 1) -ge $args.Count) { Exit-Usage }
  $name = @($opt.Keys | Where-Object { $_ -eq $key.Substring(1) })
  if ($name.Count -ne 1) { Exit-Usage }
  $opt[$name[0]] = [string]$args[$i + 1]
  $i += 2
}
if (-not $opt.Env) { Exit-Usage }

$OnWindows = ($env:OS -eq 'Windows_NT')
$ProjectHome = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
if (-not $opt.Project) { $opt.Project = Split-Path -Leaf $ProjectHome }
if (-not $opt.HopEnv) { $opt.HopEnv = $opt.Project + '-' + $opt.Env }
foreach ($n in @($opt.Env, $opt.Project, $opt.HopEnv)) {
  if ($n -cnotmatch '^[A-Za-z0-9_.-]+$') {
    [Console]::Error.WriteLine("ERROR: invalid name '$n' (letters, digits, '_', '.', '-' only)")
    exit 64
  }
}

$SecretsDir = $opt.SecretsDir
if (-not $SecretsDir) {
  if (-not $env:USERPROFILE) { Exit-Error 'USERPROFILE is not set: use -SecretsDir' }
  $SecretsDir = [IO.Path]::Combine($env:USERPROFILE, '.serasoft', 'secrets')
}
# hop-conf runs from the Hop folder: every path must be absolute
if (-not [IO.Path]::IsPathRooted($SecretsDir)) { $SecretsDir = Join-Path (Get-Location).ProviderPath $SecretsDir }

$HopHome = $opt.HopHome
if (-not $HopHome) { $HopHome = $env:HOP_HOME }
if (-not $HopHome) { Exit-Error 'HOP_HOME environment variable is not set (or use -HopHome)' }
if ($OnWindows) { $HopConf = Join-Path $HopHome 'hop-conf.bat' } else { $HopConf = Join-Path $HopHome 'hop-conf.sh' }
if (-not (Test-Path -LiteralPath $HopConf -PathType Leaf)) { Exit-Error "$HopConf not found" }
# hop-conf.bat forwards %* unquoted: cmd.exe would interpret these characters in a path
$CmdChars = '[&^%]'
if ($OnWindows -and $ProjectHome -match $CmdChars) { Exit-Error "project folder $ProjectHome contains a character that cmd.exe would interpret (& ^ %)" }

function Invoke-HopConf([string[]]$HopArgs) {
  # a caller (profile, session) with 'Stop' must not turn stderr lines of hop-conf into terminating errors
  $ErrorActionPreference = 'Continue'
  $PSNativeCommandUseErrorActionPreference = $false
  $out = & $HopConf @HopArgs 2>&1 | ForEach-Object { "$_" }
  return @{ Code = $LASTEXITCODE; Out = ($out -join "`n") }
}

# --- manifest: every line is checked before hop-config.json is touched ---
$Manifest = [IO.Path]::Combine($ProjectHome, 'config', 'env', $opt.Env + '.list')
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) { Exit-Error "manifest $Manifest not found" }
$Files = @()
foreach ($raw in [IO.File]::ReadAllLines($Manifest)) {
  $line = $raw.Trim()
  $hint = ''
  if ($line -eq '' -or $line.StartsWith('#')) { continue }
  if ($line.StartsWith('/run/secrets/')) {
    $secret = $line.Substring('/run/secrets/'.Length)
    if ($secret -eq '' -or $secret.Contains('/') -or $secret.Contains('\')) { Exit-Error "${Manifest}: invalid secret path: $line" }
    $path = Join-Path $SecretsDir $secret
    $hint = " (looked for $path and $path.json; create it from config/secrets-example.json)"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -and (Test-Path -LiteralPath "$path.json" -PathType Leaf)) { $path = "$path.json" }
  } elseif ($line.StartsWith('/') -or $line.StartsWith('\') -or $line -match '^[A-Za-z]:') {
    Exit-Error "${Manifest}: absolute paths are allowed only under /run/secrets/: $line"
  } else {
    $path = Join-Path $ProjectHome ($line.Replace('/', [IO.Path]::DirectorySeparatorChar))
  }
  if ($path.Contains(',')) { Exit-Error "${Manifest}: the path of '$line' contains a comma: $path" }
  if ($OnWindows -and $path -match $CmdChars) { Exit-Error "${Manifest}: the path of '$line' contains a character that cmd.exe would interpret (& ^ %): $path" }
  $readable = $false
  if (Test-Path -LiteralPath $path -PathType Leaf) {
    try { [IO.File]::OpenRead($path).Dispose(); $readable = $true } catch { $readable = $false }
  }
  if (-not $readable) { Exit-Error "${Manifest}: $path (from '$line') is missing or not readable$hint" }
  $Files += $path
}
if ($Files.Count -eq 0) { Exit-Error "$Manifest lists no file" }

# --- project ---
$ProjectConfig = [IO.Path]::Combine($ProjectHome, 'config', 'project-config.json')
if (-not (Test-Path -LiteralPath $ProjectConfig -PathType Leaf)) { Exit-Error "$ProjectConfig not found" }
$r = Invoke-HopConf @('-pl')
if ($r.Code -ne 0) { Exit-Error ("hop-conf -pl failed`n" + $r.Out) }
$RegisteredHome = ''
foreach ($l in ($r.Out -split "`n")) {
  if ($l -match '^  (\S+) : (.*)$' -and $Matches[1] -ceq $opt.Project) { $RegisteredHome = $Matches[2].Trim(); break }
}
function Get-Normalized([string]$p) { return [IO.Path]::GetFullPath($p).TrimEnd('\', '/') }
if (-not $RegisteredHome) {
  $backup = [IO.File]::ReadAllBytes($ProjectConfig)
  $r = Invoke-HopConf @('-pc', '-p', $opt.Project, '-ph', $ProjectHome, '-pf', 'config/project-config.json')
  $after = [IO.File]::ReadAllBytes($ProjectConfig)
  if ([Convert]::ToBase64String($after) -ne [Convert]::ToBase64String($backup)) {
    [IO.File]::WriteAllBytes($ProjectConfig, $backup)
    Write-Warn 'hop-conf rewrote config/project-config.json: original content restored'
  }
  if ($r.Code -ne 0) { Exit-Error ("hop-conf: cannot register project " + $opt.Project + "`n" + $r.Out) }
} else {
  $same = if ($OnWindows) { (Get-Normalized $RegisteredHome) -eq (Get-Normalized $ProjectHome) } else { (Get-Normalized $RegisteredHome) -ceq (Get-Normalized $ProjectHome) }
  if (-not $same) { Exit-Error ("project " + $opt.Project + " is already registered with home $RegisteredHome, not $ProjectHome (use -Project <name>)") }
}

# --- environment ---
$r = Invoke-HopConf @('-el')
if ($r.Code -ne 0) { Exit-Error ("hop-conf -el failed`n" + $r.Out) }
$Action = '-ec'
foreach ($l in ($r.Out -split "`n")) {
  if ($l -match '^  (\S+)\s*$' -and $Matches[1] -ceq $opt.HopEnv) { $Action = '-em'; break }
}
$r = Invoke-HopConf @($Action, '-e', $opt.HopEnv, '-ep', $opt.Project, '-eu', $opt.Env, '-eg', ($Files -join ','))
if ($r.Code -ne 0) { Exit-Error ("hop-conf ${Action}: cannot register environment " + $opt.HopEnv + "`n" + $r.Out) }

Write-Output ("OK serasoft-register-env project=" + $opt.Project + " hop-env=" + $opt.HopEnv + " files=" + $Files.Count)
Write-Output ("  Hop GUI: select project " + $opt.Project + ", environment " + $opt.HopEnv)
exit 0
