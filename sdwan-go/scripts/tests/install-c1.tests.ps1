# Run from Windows PowerShell as Administrator:
#   powershell -ExecutionPolicy Bypass -File .\scripts\tests\install-c1.tests.ps1
# This is deliberately Pester-free and uses -SkipStaging, so it does not download
# or modify the live installation. ACL read-back is not exercised because the
# policy is intentionally not applied until C2.

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "..\install.ps1"
. $scriptPath -SkipStaging

function Assert-Throws {
    param([scriptblock]$Action, [string]$Message)
    try { & $Action } catch { return }
    throw $Message
}

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sdwan-c1-test-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
try {
    $artifact = Join-Path $tempDir "panel.exe"
    [System.IO.File]::WriteAllBytes($artifact, [byte[]](1, 2, 3, 4))
    $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = Join-Path $tempDir "SHA256SUMS"
    Set-Content -LiteralPath $manifest -NoNewline -Value "$hash  *panel.exe"

    Test-StagedArtifactHash -ManifestPath $manifest -ArtifactPath $artifact -ArtifactName "panel.exe"
    Set-Content -LiteralPath $manifest -NoNewline -Value ((("0" * 64) -join "") + "  *panel.exe")
    Assert-Throws { Test-StagedArtifactHash -ManifestPath $manifest -ArtifactPath $artifact -ArtifactName "panel.exe" } "Expected a checksum mismatch to fail."
    Set-Content -LiteralPath $manifest -NoNewline -Value "not-a-sha256  *panel.exe"
    Assert-Throws { Get-ManifestSha256 -ManifestPath $manifest -ArtifactName "panel.exe" } "Expected an invalid manifest entry to fail."
    Set-Content -LiteralPath $manifest -NoNewline -Value "$hash panel.exe"
    Assert-Throws { Get-ManifestSha256 -ManifestPath $manifest -ArtifactName "panel.exe" } "Expected a single-space separator to fail."
    Set-Content -LiteralPath $manifest -NoNewline -Value "$hash`t *panel.exe"
    Assert-Throws { Get-ManifestSha256 -ManifestPath $manifest -ArtifactName "panel.exe" } "Expected a tab separator to fail."
    Set-Content -LiteralPath $manifest -Value @("$hash  *panel.exe", "$hash  panel.exe")
    Assert-Throws { Get-ManifestSha256 -ManifestPath $manifest -ArtifactName "panel.exe" } "Expected duplicate required entries to fail."
    Set-Content -LiteralPath $manifest -NoNewline -Value "$hash  *sdwan-windows-amd64.exe"
    Assert-Throws { Get-ManifestSha256 -ManifestPath $manifest -ArtifactName "panel.exe" } "Expected a missing required entry to fail."
    Assert-Throws { Test-StagedArtifactHash -ManifestPath $manifest -ArtifactPath (Join-Path $tempDir "missing-panel.exe") -ArtifactName "panel.exe" } "Expected a missing required artifact to fail."
    Set-Content -LiteralPath $manifest -NoNewline -Value "invalid  *panel.exe"
    Assert-Throws { Get-ManifestSha256 -ManifestPath $manifest -ArtifactName "panel.exe" } "Expected malformed required artifact record to fail."

    if ((Redact-ConfigLine -Line "password=secret") -ne "password=REDACTED") { throw "Password was not redacted." }
    if ((Redact-ConfigLine -Line "username=alice") -ne "username=alice") { throw "Non-password line changed." }

    $executablePolicy = Get-ExecutableAclPolicy
    $secretPolicy = Get-SecretAclPolicy
    if ($executablePolicy["S-1-5-32-545"] -ne "RX" -or $executablePolicy.ContainsKey((Get-CurrentUserIdentity))) { throw "Executable ACL policy is too permissive." }
    if ($secretPolicy[(Get-CurrentUserIdentity)] -ne "M") { throw "Secret ACL policy is missing current-user modify access." }
    if ((ConvertFrom-IcaclsRights -Rights "F") -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { throw "F rights mapping is incorrect." }
    if ((ConvertFrom-IcaclsRights -Rights "M") -ne [System.Security.AccessControl.FileSystemRights]::Modify) { throw "M rights mapping is incorrect." }
    if ((ConvertFrom-IcaclsRights -Rights "RX") -ne [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) { throw "RX rights mapping is incorrect." }
    Assert-Throws { ConvertFrom-IcaclsRights -Rights "W" } "Expected unsupported icacls rights to fail."

    Invoke-NativeChecked -FilePath "$env:ComSpec" -Arguments @("/c", "exit 0")
    Assert-Throws { Invoke-NativeChecked -FilePath "$env:ComSpec" -Arguments @("/c", "exit 7") } "Expected non-zero native exit code to fail."

    $source = Get-Content -LiteralPath $scriptPath -Raw
    if ($source -match 'wintun\.net|Expand-Archive|wintun\.zip') { throw "Unverified Wintun ZIP fallback remains." }
    if ($source -notmatch 'Invoke-NativeChecked.*icacls\.exe') { throw "ACL application does not check native command results." }
    if ($source -notmatch 'Test-AclPolicyApplied') { throw "ACL application has no read-back verification helper." }
    if ($source -notmatch 'S-1-5-32-544' -or $source -notmatch 'S-1-5-18') { throw "ACL policies do not use well-known SIDs." }
    if ($source -notmatch 'Remove-Item -LiteralPath \$stagedRelease') { throw "Successful staging directory cleanup is missing." }
    Write-Host "C1 installer tests passed." -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
