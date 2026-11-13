$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtime = Join-Path $root 'artifacts/browser-prototype-20261113/pyodide'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Save-PublicAsset($Url, $Destination, $ExpectedSha256) {
    curl.exe --fail --silent --show-error --max-time 60 $Url -o $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed for $Url"
    }
    if ($ExpectedSha256 -and (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash -ne $ExpectedSha256) {
        throw "SHA-256 mismatch for $Destination"
    }
}

$cdn = 'https://cdn.jsdelivr.net/pyodide/v0.29.5/full'
foreach ($asset in 'pyodide.mjs','pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json') {
    Save-PublicAsset "$cdn/$asset" (Join-Path $runtime $asset)
}
$runtimeLock = Get-Content -Raw (Join-Path $runtime 'pyodide-lock.json') | ConvertFrom-Json
$required = [Collections.Generic.Queue[string]]::new()
foreach ($key in 'numpy','pillow') {
    $required.Enqueue($key)
}
$seen = [Collections.Generic.HashSet[string]]::new()
while ($required.Count) {
    $key = $required.Dequeue()
    if (!$seen.Add($key)) {
        continue
    }
    $package = $runtimeLock.packages.$key
    if (!$package) {
        throw "Missing package $key in the Pyodide lock"
    }
    $asset = $package.file_name
    Save-PublicAsset "$cdn/$asset" (Join-Path $runtime $asset) $package.sha256
    foreach ($dependency in $package.depends) {
        $required.Enqueue($dependency)
    }
}

foreach ($spec in @(@('rmscene','0.8.0'), @('packaging','23.2'))) {
    $name, $version = $spec
    $metadata = curl.exe --fail --silent --show-error --max-time 30 "https://pypi.org/pypi/$name/$version/json"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read PyPI metadata for $name==$version"
    }
    $wheel = ($metadata | ConvertFrom-Json).urls |
        Where-Object { $_.filename -like '*-py3-none-any.whl' } |
        Select-Object -First 1
    if (!$wheel -or ([uri]$wheel.url).Host -ne 'files.pythonhosted.org') {
        throw "Missing official universal wheel for $name==$version"
    }
    Save-PublicAsset $wheel.url (Join-Path $runtime $wheel.filename) $wheel.digests.sha256
}
