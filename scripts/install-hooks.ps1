# Point git at the repo's hooks folder (scripts/git-hooks). Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1
# Undo with:  git config --unset core.hooksPath
$ErrorActionPreference = "Stop"
$root = git rev-parse --show-toplevel
if (-not $root) { throw "Not inside a git repository." }
Set-Location $root
git config core.hooksPath scripts/git-hooks
Write-Host "Installed: git now runs scripts/git-hooks/pre-commit before every commit."
Write-Host "It blocks .jpg/.jpeg/.png/.heic/.heif/.webp outside frontend/public/ and docs/design-reference.png."
