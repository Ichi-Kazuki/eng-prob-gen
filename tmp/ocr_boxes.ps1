Add-Type -AssemblyName System.Runtime.WindowsRuntime
function Get-WinType([string]$name, [string]$assembly) { [Type]::GetType("$name, $assembly, ContentType=WindowsRuntime") }
function Await-Win($operation, [Type]$resultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1
    } | Select-Object -First 1
    $method.MakeGenericMethod($resultType).Invoke($null, @($operation)).GetAwaiter().GetResult()
}
function Get-OcrResult([string]$path) {
    $st=Get-WinType 'Windows.Storage.StorageFile' 'Windows.Storage'; $ft=Get-WinType 'Windows.Storage.FileAccessMode' 'Windows.Storage'
    $dt=Get-WinType 'Windows.Graphics.Imaging.BitmapDecoder' 'Windows.Graphics.Imaging'; $ot=Get-WinType 'Windows.Media.Ocr.OcrEngine' 'Windows.Media.Ocr'
    $rst=Get-WinType 'Windows.Storage.Streams.IRandomAccessStream' 'Windows.Storage.Streams'; $sbt=Get-WinType 'Windows.Graphics.Imaging.SoftwareBitmap' 'Windows.Graphics.Imaging'; $ort=Get-WinType 'Windows.Media.Ocr.OcrResult' 'Windows.Media.Ocr'
    $storage=Await-Win ($st.GetMethod('GetFileFromPathAsync').Invoke($null,@($path))) $st
    $stream=Await-Win ($storage.OpenAsync([Enum]::Parse($ft,'Read'))) $rst
    $cm=$dt.GetMethods() | Where-Object {$_.Name -eq 'CreateAsync' -and $_.GetParameters().Count -eq 1} | Select-Object -First 1
    $decoder=Await-Win ($cm.Invoke($null,@($stream))) $dt; $sb=Await-Win ($decoder.GetSoftwareBitmapAsync()) $sbt
    $engine=$ot.GetMethod('TryCreateFromUserProfileLanguages').Invoke($null,@())
    Await-Win ($engine.RecognizeAsync($sb)) $ort
}
$outDir = Join-Path (Get-Location) 'tmp\pdfs\official_ocr_boxes'; New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Get-ChildItem 'tmp\pdfs\official\*.png' | Sort-Object Name | ForEach-Object {
    $result=Get-OcrResult $_.FullName
    $lines=@()
    foreach($line in $result.Lines) {
        $words=@()
        foreach($word in $line.Words) {
            $r=$word.BoundingRect
            $words += [pscustomobject]@{text=$word.Text; x=[double]$r.X; y=[double]$r.Y; width=[double]$r.Width; height=[double]$r.Height}
        }
        $lines += [pscustomobject]@{text=$line.Text; words=$words}
    }
    $payload=[pscustomobject]@{image=$_.Name; width=1684; height=1191; lines=$lines}
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $outDir ($_.BaseName+'.json'))
    Write-Output $_.Name
}
