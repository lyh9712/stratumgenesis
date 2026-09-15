# tools/push_via_api.ps1
# Purpose: publish file changes to GitHub when `git push` fails because
#          github.com:443 is unreachable (common behind certain networks),
#          while api.github.com is still reachable.
#
# It reuses the credential already stored by Git Credential Manager
# (`git credential fill`); the token is never printed and never written to disk.
#
# Usage (PowerShell 7 or Windows PowerShell 5.1):
#   pwsh -File tools/push_via_api.ps1 -Message "feat: something" -Files index.html,README.md
#   pwsh -File tools/push_via_api.ps1 -Message "feat: something"        # auto-detect changed files
#
# Auto-detection picks up: files reported by `git status --porcelain`
# plus files touched by the current HEAD commit.

param(
  [string]$Message = "chore: update files via GitHub API",
  [string]$Branch  = "main",
  [string[]]$Files
)

$ErrorActionPreference = "Stop"

function Get-RepoSlug {
  $url = (git remote get-url origin).Trim()
  if ($url -match 'github\.com[:/](?<owner>[^/]+)/(?<repo>[^/]+?)(\.git)?$') {
    return "$($Matches.owner)/$($Matches.repo)"
  }
  throw "Cannot parse owner/repo from origin url: $url"
}

function Get-Token {
  $payload = "protocol=https`nhost=github.com`n`n"
  $lines = ($payload | git credential fill 2>&1) -split "`r?`n"
  $pass = ($lines | Where-Object { $_ -match '^password=' }) -replace '^password=',''
  if (-not $pass) { throw "No stored GitHub credential found (run a successful git push once, or set up GCM)." }
  return $pass
}

function Get-ChangedFiles {
  $set = New-Object System.Collections.Generic.HashSet[string]
  (git status --porcelain) | ForEach-Object {
    $line = $_.Trim()
    if ($line.Length -gt 3) {
      $p = $line.Substring(3).Trim()
      if ($p -notmatch ' -> ') { [void]$set.Add($p) }
      else { [void]$set.Add(($p -split ' -> ')[-1]) }
    }
  }
  (git show --name-only --format= HEAD) | ForEach-Object {
    $p = $_.Trim()
    if ($p) { [void]$set.Add($p) }
  }
  return @($set)
}

$slug  = Get-RepoSlug
$token = Get-Token
$hdr   = @{ Authorization = "token $token"; "User-Agent" = "stratumgenesis-push"; Accept = "application/vnd.github+json" }
$list  = if ($Files -and $Files.Count -gt 0) { $Files } else { Get-ChangedFiles }

if (-not $list -or $list.Count -eq 0) { Write-Host "[info] nothing to publish."; exit 0 }

Write-Host "[info] repo: $slug  branch: $Branch  message: $Message"
$okCount = 0
foreach ($rel in $list) {
  $rel = $rel -replace '\\','/'
  if (-not (Test-Path $rel)) { Write-Host "[skip] $rel (missing locally)"; continue }
  $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path $rel))
  $b64   = [Convert]::ToBase64String($bytes)
  $sha   = $null
  try {
    $cur = Invoke-RestMethod -Uri "https://api.github.com/repos/$slug/contents/$rel`?ref=$Branch" -Headers $hdr -TimeoutSec 30
    $sha = $cur.sha
  } catch { $sha = $null }
  $body = @{ message = $Message; content = $b64; branch = $Branch }
  if ($sha) { $body.sha = $sha }
  try {
    $r = Invoke-RestMethod -Uri "https://api.github.com/repos/$slug/contents/$rel" -Method Put -Headers $hdr `
         -Body ($body | ConvertTo-Json -Compress) -ContentType "application/json" -TimeoutSec 120
    Write-Host ("[ok]   {0} -> {1}" -f $rel, $r.commit.sha.Substring(0,7))
    $okCount++
  } catch {
    Write-Host ("[fail] {0} : {1}" -f $rel, $_.Exception.Message.Split("`n")[0])
  }
}
Write-Host "[info] published $okCount file(s). GitHub Pages will rebuild in ~1 minute."
Write-Host "[warn] When github.com is reachable again, run: git fetch origin; git reset --hard origin/$Branch"
