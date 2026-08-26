Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Get-WinType([string]$name, [string]$assembly) {
    [Type]::GetType("$name, $assembly, ContentType=WindowsRuntime")
}

function Await-Win($operation, [Type]$resultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.IsGenericMethodDefinition -and
            $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1
    $method.MakeGenericMethod($resultType).Invoke($null, @($operation)).GetAwaiter().GetResult()
}

function Read-OcrImage([string]$path) {
    $storageType = Get-WinType 'Windows.Storage.StorageFile' 'Windows.Storage'
    $accessType = Get-WinType 'Windows.Storage.FileAccessMode' 'Windows.Storage'
    $decoderType = Get-WinType 'Windows.Graphics.Imaging.BitmapDecoder' 'Windows.Graphics.Imaging'
    $engineType = Get-WinType 'Windows.Media.Ocr.OcrEngine' 'Windows.Media.Ocr'
    $streamType = Get-WinType 'Windows.Storage.Streams.IRandomAccessStream' 'Windows.Storage.Streams'
    $bitmapType = Get-WinType 'Windows.Graphics.Imaging.SoftwareBitmap' 'Windows.Graphics.Imaging'
    $resultType = Get-WinType 'Windows.Media.Ocr.OcrResult' 'Windows.Media.Ocr'

    $storage = Await-Win ($storageType.GetMethod('GetFileFromPathAsync').Invoke($null, @($path))) $storageType
    $stream = Await-Win ($storage.OpenAsync([Enum]::Parse($accessType, 'Read'))) $streamType
    $createMethod = $decoderType.GetMethods() |
        Where-Object { $_.Name -eq 'CreateAsync' -and $_.GetParameters().Count -eq 1 } |
        Select-Object -First 1
    $decoder = Await-Win ($createMethod.Invoke($null, @($stream))) $decoderType
    $bitmap = Await-Win ($decoder.GetSoftwareBitmapAsync()) $bitmapType
    $engine = $engineType.GetMethod('TryCreateFromUserProfileLanguages').Invoke($null, @())
    if ($null -eq $engine) { throw "Windows OCR engine unavailable" }
    $result = Await-Win ($engine.RecognizeAsync($bitmap)) $resultType
    $result.Text
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$officialDir = Join-Path $repoRoot 'tmp\pdfs\official'
$outDir = Join-Path $repoRoot 'tmp\pdfs\official_ocr'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Get-ChildItem (Join-Path $officialDir '*.png') | Sort-Object Name | ForEach-Object {
    $outPath = Join-Path $outDir ($_.BaseName + '.txt')
    $text = Read-OcrImage $_.FullName
    [IO.File]::WriteAllText($outPath, $text, [Text.UTF8Encoding]::new($false))
    Write-Output "$($_.Name) -> $outPath"
}
