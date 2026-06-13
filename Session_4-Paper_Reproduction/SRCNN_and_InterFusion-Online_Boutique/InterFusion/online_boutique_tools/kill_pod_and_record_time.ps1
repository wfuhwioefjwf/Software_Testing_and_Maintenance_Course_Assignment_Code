param(
    [string]$Namespace = "online-boutique",
    [string]$TargetService = "frontend",
    [int]$LabelAfterKillSeconds = 600,
    [int]$WaitRecoverSeconds = 300,
    [string]$OutRoot = "E:\0AI\Online-Boutique\InterFusion\online_boutique_data",
    [switch]$ActuallyDelete
)

$RunName = "kill_${TargetService}_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$OutDir = Join-Path $OutRoot $RunName
New-Item -ItemType Directory -Force $OutDir | Out-Null

function Get-UnixNow {
    return [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
}

function Get-TargetPod($Namespace, $TargetService) {
    $Pods = kubectl get pods -n $Namespace --no-headers

    foreach ($Line in $Pods) {
        $Parts = $Line -split "\s+"
        if ($Parts.Count -lt 3) {
            continue
        }

        $PodName = $Parts[0]
        $Ready = $Parts[1]
        $Status = $Parts[2]

        if ($PodName -like "$TargetService-*" -and $Status -eq "Running") {
            return $PodName
        }
    }

    throw "No running pod found for service: $TargetService"
}

function Is-ReadyText($ReadyText) {
    if ($ReadyText -match "^(\d+)/(\d+)$") {
        return ([int]$Matches[1] -eq [int]$Matches[2])
    }
    return $false
}

function Wait-TargetServiceReady($Namespace, $TargetService, $OldPod, $TimeoutSeconds) {
    $Start = Get-Date

    while (((Get-Date) - $Start).TotalSeconds -lt $TimeoutSeconds) {
        $Pods = kubectl get pods -n $Namespace --no-headers

        foreach ($Line in $Pods) {
            $Parts = $Line -split "\s+"
            if ($Parts.Count -lt 3) {
                continue
            }

            $PodName = $Parts[0]
            $Ready = $Parts[1]
            $Status = $Parts[2]

            if ($PodName -like "$TargetService-*" -and $PodName -ne $OldPod -and $Status -eq "Running" -and (Is-ReadyText $Ready)) {
                return $PodName
            }
        }

        Start-Sleep -Seconds 5
    }

    return ""
}

$ExperimentStartUnix = Get-UnixNow
$ExperimentStartLocal = Get-Date

Write-Host "=========================================="
Write-Host "Kill pod time recorder"
Write-Host "Namespace: $Namespace"
Write-Host "Target service: $TargetService"
Write-Host "Out dir: $OutDir"
Write-Host "Actually delete: $ActuallyDelete"
Write-Host "=========================================="

$TargetPod = Get-TargetPod $Namespace $TargetService

Write-Host "Target pod found: $TargetPod"

$KillUnix = Get-UnixNow
$KillLocal = Get-Date

$LabelStartUnix = $KillUnix
$LabelEndUnix = $KillUnix + $LabelAfterKillSeconds
$LabelEndLocal = [DateTimeOffset]::FromUnixTimeSeconds($LabelEndUnix).ToLocalTime().DateTime

$RecoveredPod = ""
$RecoverUnix = -1
$RecoverLocal = ""

if ($ActuallyDelete) {
    Write-Host "Deleting pod at local time: $($KillLocal.ToString("yyyy-MM-dd HH:mm:ss"))"
    Write-Host "Deleting pod: $TargetPod"

    kubectl delete pod $TargetPod -n $Namespace

    Write-Host "Waiting for new $TargetService pod to become Ready ..."
    $RecoveredPod = Wait-TargetServiceReady $Namespace $TargetService $TargetPod $WaitRecoverSeconds

    if ($RecoveredPod -ne "") {
        $RecoverUnix = Get-UnixNow
        $RecoverLocal = Get-Date
        Write-Host "Recovered pod: $RecoveredPod"
        Write-Host "Recover local time: $($RecoverLocal.ToString("yyyy-MM-dd HH:mm:ss"))"
    } else {
        Write-Host "WARNING: New pod did not become Ready within $WaitRecoverSeconds seconds."
    }
} else {
    Write-Host "Dry run only. Pod will NOT be deleted."
    Write-Host "Use -ActuallyDelete to really delete the pod."
}

$ExperimentEndUnix = Get-UnixNow
$ExperimentEndLocal = Get-Date

$Meta = [pscustomobject]@{
    namespace = $Namespace
    target_service = $TargetService
    killed_pod = $TargetPod
    recovered_pod = $RecoveredPod
    actually_deleted = [bool]$ActuallyDelete

    experiment_start_unix = $ExperimentStartUnix
    experiment_end_unix = $ExperimentEndUnix

    kill_unix = $KillUnix
    label_start_unix = $LabelStartUnix
    label_end_unix = $LabelEndUnix
    recover_unix = $RecoverUnix

    experiment_start_local = $ExperimentStartLocal.ToString("yyyy-MM-dd HH:mm:ss")
    experiment_end_local = $ExperimentEndLocal.ToString("yyyy-MM-dd HH:mm:ss")
    kill_local = $KillLocal.ToString("yyyy-MM-dd HH:mm:ss")
    label_end_local = $LabelEndLocal.ToString("yyyy-MM-dd HH:mm:ss")
    recover_local = if ($RecoverLocal -eq "") { "" } else { $RecoverLocal.ToString("yyyy-MM-dd HH:mm:ss") }

    label_after_kill_seconds = $LabelAfterKillSeconds
    wait_recover_seconds = $WaitRecoverSeconds
}

$MetaPath = Join-Path $OutDir "experiment_meta.json"
$Meta | ConvertTo-Json -Depth 5 | Out-File $MetaPath -Encoding UTF8

Write-Host "=========================================="
Write-Host "Meta saved: $MetaPath"
Write-Host "Kill local: $($KillLocal.ToString("yyyy-MM-dd HH:mm:ss"))"
Write-Host "Label anomaly until: $($LabelEndLocal.ToString("yyyy-MM-dd HH:mm:ss"))"
Write-Host "=========================================="