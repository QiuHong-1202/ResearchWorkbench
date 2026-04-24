[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..\..")).Path
$extractScript = Join-Path $scriptDir "extract_pdf.py"

$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"

$command = @(
    "run"
    "--project"
    $repoRoot
    "python"
    $extractScript
)

if ($RemainingArgs) {
    $command += $RemainingArgs
}

& uv @command
exit $LASTEXITCODE
