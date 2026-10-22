param(
    [string]$Output = "$env:TEMP\travel-agent-deploy.tar.gz"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
if (-not $resolvedOutput.StartsWith([System.IO.Path]::GetFullPath($env:TEMP), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output must stay inside the Windows temporary directory: $env:TEMP"
}

if (Test-Path -LiteralPath $resolvedOutput) {
    Remove-Item -LiteralPath $resolvedOutput -Force
}

Push-Location $projectRoot
try {
    tar -czf $resolvedOutput `
        --exclude=.env `
        --exclude=miniprogram/config.private.js `
        --exclude=miniprogram/project.private.config.json `
        --exclude=.git `
        --exclude=.claude `
        --exclude=.venv `
        --exclude=.pytest_cache `
        --exclude=__pycache__ `
        --exclude='*/__pycache__' `
        --exclude='*.pyc' `
        --exclude=frontend/node_modules `
        --exclude=frontend/dist `
        --exclude=runtime `
        --exclude=backups `
        --exclude=output `
        --exclude=logs `
        --exclude='*.docx' `
        --exclude=scripts/.xhs_bali_cache.jsonl `
        --exclude=bali_xhs_notes_batch2.md `
        --exclude=command `
        .
    if ($LASTEXITCODE -ne 0) { throw "tar failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$entryList = tar -tzf $resolvedOutput
$forbidden = $entryList | Where-Object {
    $_ -match '(^|/)\.env$' -or $_ -match '(^|/)config\.private\.js$' -or
    $_ -match '(^|/)project\.private\.config\.json$' -or $_ -match '(^|/)backups/' -or
    $_ -match '(^|/)(node_modules|\.venv|runtime)/'
}
if ($forbidden) {
    Remove-Item -LiteralPath $resolvedOutput -Force
    throw "Bundle contained forbidden entries: $($forbidden -join ', ')"
}

$hash = Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256
[PSCustomObject]@{
    Path = $resolvedOutput
    SizeMB = [math]::Round((Get-Item -LiteralPath $resolvedOutput).Length / 1MB, 2)
    SHA256 = $hash.Hash
    Entries = $entryList.Count
}
