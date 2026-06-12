$ErrorActionPreference = "Stop"

$ProjectDir = "E:\0AI\Online-Boutique"
$ChaosDir = Join-Path $ProjectDir "chaos-yamls"
$YamlPath = Join-Path $ChaosDir "frontend-random-cpu-stress.yaml"
$LogPath = Join-Path $ChaosDir "fault_windows.csv"

$Rounds = 8
$MinStressSeconds = 60
$MaxStressSeconds = 90
$MinRestSeconds = 60
$MaxRestSeconds = 90

$ChaosName = "frontend-random-cpu-stress"
$Namespace = "online-boutique"
$Target = "frontend"

if (-not (Test-Path $YamlPath)) {
    throw "YAML file not found: $YamlPath"
}

$frontendPods = kubectl get pods -n $Namespace -l app=frontend --no-headers
if ([string]::IsNullOrWhiteSpace($frontendPods)) {
    throw "No frontend pod found. Please check: kubectl get pods -n online-boutique --show-labels"
}

Write-Host "Found frontend pod:"
Write-Host $frontendPods

New-Item -ItemType Directory -Force $ChaosDir | Out-Null

"round,start_local,end_local,start_utc,end_utc,duration_seconds,rest_seconds,chaos_name,namespace,target" | Out-File $LogPath -Encoding utf8

Write-Host "Start random CPU stress injection..."
Write-Host "YAML file: $YamlPath"
Write-Host "Log file : $LogPath"

for ($i = 1; $i -le $Rounds; $i++) {
    $duration = Get-Random -Minimum $MinStressSeconds -Maximum ($MaxStressSeconds + 1)
    $rest = Get-Random -Minimum $MinRestSeconds -Maximum ($MaxRestSeconds + 1)

    Write-Host ""
    Write-Host "==============================="
    Write-Host "Round $i / $Rounds"
    Write-Host "Stress duration: $duration seconds"
    Write-Host "Rest duration: $rest seconds"
    Write-Host "==============================="

    kubectl delete stresschaos $ChaosName -n $Namespace --ignore-not-found=true | Out-Null
    Start-Sleep -Seconds 2

    Write-Host "Applying CPU stress..."
    kubectl apply -f $YamlPath
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl apply failed."
    }

    Start-Sleep -Seconds 5

    $startLocal = Get-Date
    $startUtc = $startLocal.ToUniversalTime()

    Write-Host "CPU stress started at $($startLocal.ToString('yyyy-MM-dd HH:mm:ss'))"

    Start-Sleep -Seconds $duration

    $endLocal = Get-Date
    $endUtc = $endLocal.ToUniversalTime()

    Write-Host "Deleting CPU stress..."
    kubectl delete stresschaos $ChaosName -n $Namespace --ignore-not-found=true

    $fields = @(
        $i,
        $startLocal.ToString("yyyy-MM-dd HH:mm:ss"),
        $endLocal.ToString("yyyy-MM-dd HH:mm:ss"),
        $startUtc.ToString("yyyy-MM-dd HH:mm:ss"),
        $endUtc.ToString("yyyy-MM-dd HH:mm:ss"),
        $duration,
        $rest,
        $ChaosName,
        $Namespace,
        $Target
    )

    $line = $fields -join ","
    Add-Content -Path $LogPath -Value $line -Encoding utf8

    Write-Host "Logged:"
    Write-Host $line

    Write-Host "Resting..."
    Start-Sleep -Seconds $rest
}

Write-Host ""
Write-Host "Random CPU stress injection finished."
Write-Host "Fault windows saved to: $LogPath"
Get-Content $LogPath