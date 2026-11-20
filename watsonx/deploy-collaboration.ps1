param([string]$Orchestrate = 'orchestrate', [switch]$WithNifs)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$stageRoot = Join-Path $repoRoot ('output/watsonx-package/' + [Guid]::NewGuid().ToString('N'))
$toolFile = if ($WithNifs) { 'watsonx/gamak_passage_tool_nifs.py' } else { 'watsonx/gamak_passage_tool.py' }
$allowed = @(
  'gamak_demo/__init__.py', 'gamak_demo/contract.py', 'gamak_demo/evidence.py',
  'gamak_demo/rag.py', 'gamak_demo/collaboration_contract.py', 'gamak_demo/nifs.py',
  'data/gamak-archive.json', $toolFile
)
foreach ($item in $allowed) {
  $dest = Join-Path $stageRoot $item
  New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $repoRoot $item) -Destination $dest
}
$requirements = Join-Path $stageRoot 'requirements.txt'
Set-Content -LiteralPath $requirements -Value @('pydantic>=2.11,<3', 'httpx2[http2,brotli,zstd]>=2,<3') -Encoding utf8NoBOM
$connections = @()
if ($WithNifs) { $connections = @('-a', 'kiw_nifs_red_tide') }
& $Orchestrate tools import -k python -f (Join-Path $stageRoot $toolFile) -p $stageRoot -r $requirements @connections
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
foreach ($name in @('gamak_research', 'gamak_supervisor')) {
  & $Orchestrate agents import -f (Join-Path $PSScriptRoot "$name.yaml")
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $Orchestrate agents deploy -n "kiw_$name"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
