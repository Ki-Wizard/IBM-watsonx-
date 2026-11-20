param(
    [string]$ProjectName = 'gamak-red-tide',
    [string]$AppName = 'gamak-red-tide-app',
    [string]$Region = 'us-south',
    [string]$ResourceGroup = 'Default',
    [string]$EnvFile = '.env'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Target IBM Cloud region=$Region resource-group=$ResourceGroup project=$ProjectName"
ibmcloud target -r $Region -g $ResourceGroup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

ibmcloud ce project select -n $ProjectName
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating Code Engine project $ProjectName..."
    ibmcloud ce project create -n $ProjectName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$envArgs = @()
if (Test-Path (Join-Path $repoRoot $EnvFile)) {
    Get-Content (Join-Path $repoRoot $EnvFile) | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $envArgs += @('--env', $line)
        }
    }
}

$exists = ibmcloud ce app get -n $AppName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Updating existing Code Engine app $AppName from source..."
    ibmcloud ce app update -n $AppName --build-source $repoRoot --port 8080 --min-scale 0 --max-scale 2 @envArgs
} else {
    Write-Host "Creating Code Engine app $AppName from source..."
    ibmcloud ce app create -n $AppName --build-source $repoRoot --port 8080 --min-scale 0 --max-scale 2 @envArgs
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

ibmcloud ce app get -n $AppName --output url
