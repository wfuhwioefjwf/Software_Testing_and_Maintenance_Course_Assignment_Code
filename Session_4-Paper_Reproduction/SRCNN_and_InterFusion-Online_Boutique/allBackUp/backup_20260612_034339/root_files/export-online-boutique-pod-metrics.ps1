$PromUrl = "http://127.0.0.1:61279"
$OutDir = ".\prometheus-online-boutique-pod-data"
New-Item -ItemType Directory -Force $OutDir | Out-Null

# 导出最近 2 小时数据
$End = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$Start = $End - 7200
$Step = "15s"

function Export-PromQuery($Name, $Query) {
    Write-Host "Exporting $Name ..."

    $EncodedQuery = [uri]::EscapeDataString($Query)
    $Api = "$PromUrl/api/v1/query_range?query=$EncodedQuery&start=$Start&end=$End&step=$Step"

    try {
        $Resp = Invoke-RestMethod -Uri $Api -Method Get
    } catch {
        Write-Host "ERROR: $Name"
        Write-Host $_
        return
    }

    if ($Resp.status -ne "success" -or $Resp.data.result.Count -eq 0) {
        Write-Host "EMPTY: $Name"
        return
    }

    $Rows = foreach ($Series in $Resp.data.result) {
        $MetricText = ($Series.metric.PSObject.Properties | ForEach-Object {
            "$($_.Name)=$($_.Value)"
        }) -join ";"

        foreach ($V in $Series.values) {
            $Unix = [int64][double]$V[0]
            [pscustomobject]@{
                time_utc   = [DateTimeOffset]::FromUnixTimeSeconds($Unix).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")
                time_local = [DateTimeOffset]::FromUnixTimeSeconds($Unix).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
                value      = [double]$V[1]
                metric     = $MetricText
            }
        }
    }

    $Path = Join-Path $OutDir "$Name.csv"
    $Rows | Export-Csv $Path -NoTypeInformation -Encoding UTF8
    Write-Host "Saved: $Path"
}

# ========== frontend Pod 级 CPU ==========
Export-PromQuery "01_frontend_pod_cpu" 'sum by (pod) (rate(container_cpu_usage_seconds_total{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*"}[1m]))'

# ========== 所有 Online Boutique Pod CPU ==========
Export-PromQuery "02_all_online_boutique_pods_cpu" 'sum by (pod) (rate(container_cpu_usage_seconds_total{job="kubernetes-cadvisor", namespace="online-boutique"}[1m]))'

# ========== frontend Pod 级内存 ==========
Export-PromQuery "03_frontend_pod_memory" 'sum by (pod) (container_memory_working_set_bytes{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*"})'

# ========== 所有 Online Boutique Pod 内存 ==========
Export-PromQuery "04_all_online_boutique_pods_memory" 'sum by (pod) (container_memory_working_set_bytes{job="kubernetes-cadvisor", namespace="online-boutique"})'

# ========== frontend 网络接收 ==========
Export-PromQuery "05_frontend_network_receive" 'sum by (pod) (rate(container_network_receive_bytes_total{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*"}[1m]))'

# ========== frontend 网络发送 ==========
Export-PromQuery "06_frontend_network_transmit" 'sum by (pod) (rate(container_network_transmit_bytes_total{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*"}[1m]))'

# ========== Pod Ready 状态 ==========
Export-PromQuery "07_frontend_ready" 'kube_pod_status_ready{namespace="online-boutique", pod=~"frontend-.*", condition="true"}'

Export-PromQuery "08_all_online_boutique_ready" 'kube_pod_status_ready{namespace="online-boutique", condition="true"}'

# ========== Pod 重启次数 ==========
Export-PromQuery "09_online_boutique_pod_restarts" 'kube_pod_container_status_restarts_total{namespace="online-boutique"}'

# ========== 节点 CPU，作为辅助对照 ==========
Export-PromQuery "10_node_cpu_total_usage" '(1 - avg(irate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100'

Export-PromQuery "11_node_cpu_user_usage" 'avg(irate(node_cpu_seconds_total{mode="user"}[5m])) * 100'

Export-PromQuery "12_node_cpu_system_usage" 'avg(irate(node_cpu_seconds_total{mode="system"}[5m])) * 100'