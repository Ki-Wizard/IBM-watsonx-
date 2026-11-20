$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$stageRoot = Join-Path $repoRoot ('output/watsonx-package/' + [Guid]::NewGuid().ToString('N'))
$allowed = @(
  'gamak_demo/__init__.py', 'gamak_demo/agent_contract.py', 'gamak_demo/contract.py',
  'gamak_demo/evidence.py', 'gamak_demo/ledger.py', 'gamak_demo/service.py', 'gamak_demo/rag.py', 'gamak_demo/nifs.py',
  'data/gamak-archive.json', 'watsonx/gamak_evidence_tool.py'
)
foreach ($item in $allowed) {
  $dest = Join-Path $stageRoot $item
  New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $repoRoot $item) -Destination $dest
}
$requirements = Join-Path $stageRoot 'requirements.txt'
Set-Content -LiteralPath $requirements -Value @('pydantic>=2.11,<3', 'httpx2[http2,brotli,zstd]>=2,<3') -Encoding utf8NoBOM
$teamPrompt = Get-Content -LiteralPath (Join-Path $repoRoot 'prompts/agent-system-prompt.md') -Raw
$principles = [regex]::Match($teamPrompt, '(?ms)^## 1\.[^\r\n]*\r?\n(.*?)^## 2\.')
if (!$principles.Success) { throw 'Cannot locate the team prompt principles' }
$promptLines = $principles.Groups[1].Value.Trim() -split '\r?\n'
$indented = ($promptLines | ForEach-Object { '  ' + $_ }) -join "`n"
$template = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'gamak_agent.yaml') -Raw
$agentFile = Join-Path $stageRoot 'gamak_agent.yaml'
$template.Replace('instructions: |', "instructions: |`n$indented") |
  Set-Content -LiteralPath $agentFile -Encoding utf8NoBOM
orchestrate tools import -k python -f (Join-Path $stageRoot 'watsonx/gamak_evidence_tool.py') -p $stageRoot -r $requirements
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
orchestrate agents import -f $agentFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
orchestrate agents deploy -n kiw_gamak_red_tide
exit $LASTEXITCODE
