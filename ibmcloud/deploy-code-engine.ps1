param(
    [string]$ProjectName = 'gamak-red-tide',
    [string]$AppName = 'gamak-red-tide-app',
    [string]$Region = 'us-south',
    [string]$ResourceGroup = 'Default',
    [string]$EnvFile = '.env'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

$ibmcloudCmd = Get-Command ibmcloud -ErrorAction SilentlyContinue
if ($ibmcloudCmd -and $ibmcloudCmd.Source -notmatch '\\WinGet\\Links\\') {
    $ibmcloud = $ibmcloudCmd.Source
} else {
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\IBM.Cloud.CLI*" -Recurse -Filter ibmcloud.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        $ibmcloud = $found.FullName
    } else {
        $ibmcloud = 'ibmcloud'
    }
}

Write-Host "Using IBM Cloud CLI: $ibmcloud"
Write-Host "Target IBM Cloud region=$Region resource-group=$ResourceGroup project=$ProjectName"
& $ibmcloud target -r $Region -g $ResourceGroup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ErrorActionPreference = 'Continue'
& $ibmcloud ce project select -n $ProjectName
if ($LASTEXITCODE -ne 0) {
    $ErrorActionPreference = 'Stop'
    Write-Host "Creating Code Engine project $ProjectName..."
    & $ibmcloud ce project create -n $ProjectName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$ErrorActionPreference = 'Stop'

$envArgs = @()
if (Test-Path (Join-Path $repoRoot $EnvFile)) {
    Get-Content (Join-Path $repoRoot $EnvFile) | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $envArgs += @('--env', $line)
        }
    }
}

$ErrorActionPreference = 'Continue'
$exists = & $ibmcloud ce app get -n $AppName 2>&1
$appExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'

if ($appExists) {
    Write-Host "Updating existing Code Engine app $AppName from source..."
    & $ibmcloud ce app update -n $AppName --build-source $repoRoot --port 8080 --min-scale 0 --max-scale 2 @envArgs
} else {
    Write-Host "Creating Code Engine app $AppName from source..."
    & $ibmcloud ce app create -n $AppName --build-source $repoRoot --port 8080 --min-scale 0 --max-scale 2 @envArgs
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $ibmcloud ce app get -n $AppName --output url
