$PromUrl = "http://127.0.0.1:61279"
$OutDir = ".\prometheus-container-data"
New-Item -ItemType Directory -Force $OutDir | Out-Null

# 导出最近 2 小时，避免手动填写 UTC 时间出错
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

# ========== A. 新版标签：namespace / pod / container ==========

Export-PromQuery "01_frontend_cpu_newlabel" 'sum by (pod, container) (rate(container_cpu_usage_seconds_total{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*", container!="", container!="POD"}[1m]))'

Export-PromQuery "02_all_pods_cpu_newlabel" 'sum by (pod, container) (rate(container_cpu_usage_seconds_total{job="kubernetes-cadvisor", namespace="online-boutique", container!="", container!="POD"}[1m]))'

Export-PromQuery "03_frontend_memory_newlabel" 'sum by (pod, container) (container_memory_working_set_bytes{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*", container!="", container!="POD"})'

Export-PromQuery "04_all_pods_memory_newlabel" 'sum by (pod, container) (container_memory_working_set_bytes{job="kubernetes-cadvisor", namespace="online-boutique", container!="", container!="POD"})'

Export-PromQuery "05_frontend_network_receive_newlabel" 'sum by (pod) (rate(container_network_receive_bytes_total{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*"}[1m]))'

Export-PromQuery "06_frontend_network_transmit_newlabel" 'sum by (pod) (rate(container_network_transmit_bytes_total{job="kubernetes-cadvisor", namespace="online-boutique", pod=~"frontend-.*"}[1m]))'


# ========== B. 旧版标签：kubernetes_namespace / kubernetes_pod_name / container_name ==========

Export-PromQuery "11_frontend_cpu_oldlabel" 'sum by (kubernetes_pod_name, container_name) (rate(container_cpu_usage_seconds_total{job="kubernetes-cadvisor", kubernetes_namespace="online-boutique", kubernetes_pod_name=~"frontend-.*", container_name!="", container_name!="POD"}[1m]))'

Export-PromQuery "12_all_pods_cpu_oldlabel" 'sum by (kubernetes_pod_name, container_name) (rate(container_cpu_usage_seconds_total{job="kubernetes-cadvisor", kubernetes_namespace="online-boutique", container_name!="", container_name!="POD"}[1m]))'

Export-PromQuery "13_frontend_memory_oldlabel" 'sum by (kubernetes_pod_name, container_name) (container_memory_working_set_bytes{job="kubernetes-cadvisor", kubernetes_namespace="online-boutique", kubernetes_pod_name=~"frontend-.*", container_name!="", container_name!="POD"})'

Export-PromQuery "14_all_pods_memory_oldlabel" 'sum by (kubernetes_pod_name, container_name) (container_memory_working_set_bytes{job="kubernetes-cadvisor", kubernetes_namespace="online-boutique", container_name!="", container_name!="POD"})'

Export-PromQuery "15_frontend_network_receive_oldlabel" 'sum by (kubernetes_pod_name) (rate(container_network_receive_bytes_total{job="kubernetes-cadvisor", kubernetes_namespace="online-boutique", kubernetes_pod_name=~"frontend-.*"}[1m]))'

Export-PromQuery "16_frontend_network_transmit_oldlabel" 'sum by (kubernetes_pod_name) (rate(container_network_transmit_bytes_total{job="kubernetes-cadvisor", kubernetes_namespace="online-boutique", kubernetes_pod_name=~"frontend-.*"}[1m]))'


# ========== C. kube-state-metrics：Pod 状态，作为辅助判断 ==========

Export-PromQuery "21_frontend_ready" 'kube_pod_status_ready{namespace="online-boutique", pod=~"frontend-.*", condition="true"}'

Export-PromQuery "22_all_pods_ready" 'kube_pod_status_ready{namespace="online-boutique", condition="true"}'

Export-PromQuery "23_pod_restarts" 'kube_pod_container_status_restarts_total{namespace="online-boutique"}'


# ========== D. 节点 CPU：兜底，用于判断 CPU Stress 是否影响整机 ==========

Export-PromQuery "31_node_cpu_total_usage" '(1 - avg(irate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100'

Export-PromQuery "32_node_cpu_user_usage" 'avg(irate(node_cpu_seconds_total{mode="user"}[5m])) * 100'

Export-PromQuery "33_node_cpu_system_usage" 'avg(irate(node_cpu_seconds_total{mode="system"}[5m])) * 100'