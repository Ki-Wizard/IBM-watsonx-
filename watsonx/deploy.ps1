$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$stageRoot = Join-Path $repoRoot ('output/watsonx-package/' + [Guid]::NewGuid().ToString('N'))
$allowed = @(
  'gamak_demo/__init__.py', 'gamak_demo/agent_contract.py', 'gamak_demo/contract.py',
  'gamak_demo/evidence.py', 'gamak_demo/ledger.py', 'gamak_demo/service.py',
  'data/gamak-archive.json', 'watsonx/gamak_evidence_tool.py'
)
foreach ($item in $allowed) {
  $dest = Join-Path $stageRoot $item
  New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $repoRoot $item) -Destination $dest
}
$requirements = Join-Path $stageRoot 'requirements.txt'
Set-Content -LiteralPath $requirements -Value 'pydantic>=2.11,<3' -Encoding utf8NoBOM
orchestrate tools import -k python -f (Join-Path $stageRoot 'watsonx/gamak_evidence_tool.py') -p $stageRoot -r $requirements
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
orchestrate agents import -f (Join-Path $PSScriptRoot 'gamak_agent.yaml')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
orchestrate agents deploy -n kiw_gamak_red_tide
exit $LASTEXITCODE
