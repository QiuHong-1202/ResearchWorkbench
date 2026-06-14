[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..\..")).Path
$archiveScript = Join-Path $scriptDir "archive_recommendations.py"

$command = @(
    "run"
    "--project"
    $repoRoot
    "python"
    $archiveScript
)

if ($RemainingArgs) {
    $command += $RemainingArgs
}

& uv @command
exit $LASTEXITCODE
