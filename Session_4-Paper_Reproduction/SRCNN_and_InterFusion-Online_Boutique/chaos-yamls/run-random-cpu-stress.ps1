# run-random-cpu-stress-fixed.ps1
#
# 作用：
# 1. 随机多次对 Online Boutique frontend 注入 CPU Stress。
# 2. 每次故障持续 15~30 秒。
# 3. 每次故障之间休息 10~20 秒。
# 4. 自动保存真实故障注入时间到 fault_windows.csv。
#
# 这个版本不依赖外部 YAML 文件，会自动生成临时 YAML，避免 YAML 和 ps1 混在一起。

$ErrorActionPreference = "Stop"

$ProjectDir = "E:\0AI\Online-Boutique"
$ChaosDir = Join-Path $ProjectDir "chaos-yamls"
$LogPath = Join-Path $ChaosDir "fault_windows.csv"
$TempYamlPath = Join-Path $ChaosDir "frontend-random-cpu-stress-temp.yaml"

$Rounds = 12

$MinStressSeconds = 15
$MaxStressSeconds = 30

$MinRestSeconds = 10
$MaxRestSeconds = 20

$ChaosName = "frontend-random-cpu-stress"
$Namespace = "online-boutique"
$Target = "frontend"

New-Item -ItemType Directory -Force $ChaosDir | Out-Null

function Run-Kubectl {
    param(
        [string[]]$Args
    )

    & kubectl @Args
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl command failed: kubectl $($Args -join ' ')"
    }
}

Write-Host "Checking frontend pod label..."
$frontendPods = kubectl get pods -n $Namespace -l app=frontend --no-headers 2>$null

if ([string]::IsNullOrWhiteSpace($frontendPods)) {
    throw "没有找到 app=frontend 的 Pod。请先运行：kubectl get pods -n online-boutique --show-labels，确认 frontend 的标签是不是 app=frontend。"
}

Write-Host "Found frontend pod:"
Write-Host $frontendPods

# 每次运行都重新生成日志文件，避免和旧数据混在一起
"round,start_local,end_local,start_utc,end_utc,duration_seconds,rest_seconds,chaos_name,namespace,target" | Out-File $LogPath -Encoding utf8

Write-Host "Start random CPU stress injection..."
Write-Host "Log file: $LogPath"

for ($i = 1; $i -le $Rounds; $i++) {
    $duration = Get-Random -Minimum $MinStressSeconds -Maximum ($MaxStressSeconds + 1)
    $rest = Get-Random -Minimum $MinRestSeconds -Maximum ($MaxRestSeconds + 1)

    # YAML 的 duration 稍微设长一点，防止脚本中断后故障无法自动恢复
    $yamlDuration = $duration + 20

    $YamlContent = @"
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: $ChaosName
  namespace: $Namespace
spec:
  mode: one
  selector:
    namespaces:
      - $Namespace
    labelSelectors:
      app: $Target
  stressors:
    cpu:
      workers: 1
      load: 80
  duration: "${yamlDuration}s"
"@

    $YamlContent | Out-File $TempYamlPath -Encoding utf8

    Write-Host ""
    Write-Host "==============================="
    Write-Host "Round $i / $Rounds"
    Write-Host "Stress duration: $duration seconds"
    Write-Host "Rest duration: $rest seconds"
    Write-Host "==============================="

    # 确保不存在旧的同名故障
    kubectl delete stresschaos $ChaosName -n $Namespace --ignore-not-found=true | Out-Null
    Start-Sleep -Seconds 2

    Write-Host "Applying CPU stress..."
    Run-Kubectl @("apply", "-f", $TempYamlPath)

    # 等待 ChaosMesh 确认注入成功
    Write-Host "Waiting for ChaosMesh injection..."
    Run-Kubectl @("wait", "--for=condition=AllInjected", "stresschaos/$ChaosName", "-n", $Namespace, "--timeout=30s")

    $startLocal = Get-Date
    $startUtc = $startLocal.ToUniversalTime()

    Write-Host "CPU stress injected at $($startLocal.ToString('yyyy-MM-dd HH:mm:ss'))"
    Start-Sleep -Seconds $duration

    $endLocal = Get-Date
    $endUtc = $endLocal.ToUniversalTime()

    Write-Host "Deleting CPU stress..."
    kubectl delete stresschaos $ChaosName -n $Namespace --ignore-not-found=true | Out-Host

    $line = "{0},{1},{2},{3},{4},{5},{6},{7},{8},{9}" -f `
        $i, `
        $startLocal.ToString("yyyy-MM-dd HH:mm:ss"), `
        $endLocal.ToString("yyyy-MM-dd HH:mm:ss"), `
        $startUtc.ToString("yyyy-MM-dd HH:mm:ss"), `
        $endUtc.ToString("yyyy-MM-dd HH:mm:ss"), `
        $duration, `
        $rest, `
        $ChaosName, `
        $Namespace, `
        $Target

    Add-Content -Path $LogPath -Value $line -Encoding utf8

    Write-Host "Logged fault window:"
    Write-Host $line

    Write-Host "Resting for $rest seconds..."
    Start-Sleep -Seconds $rest
}

Write-Host ""
Write-Host "Random CPU stress injection finished."
Write-Host "Fault windows saved to: $LogPath"

Write-Host ""
Write-Host "Preview fault_windows.csv:"
Get-Content $LogPath