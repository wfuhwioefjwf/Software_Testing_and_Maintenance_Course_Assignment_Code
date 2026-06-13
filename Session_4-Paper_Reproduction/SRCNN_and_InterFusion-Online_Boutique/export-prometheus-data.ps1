$PromUrl = "http://127.0.0.1:61279"
$OutDir = ".\prometheus-data"
New-Item -ItemType Directory -Force $OutDir | Out-Null

# 这里是本轮故障的大致时间范围，使用 UTC 时间
# CPU Stress：2026-06-11T16:39:08Z 开始，但你很快删除了
# Network Delay：2026-06-11T16:40:28Z 开始，持续 5 分钟
$Start = [DateTimeOffset]::Parse("2026-06-11T16:35:00Z").ToUnixTimeSeconds()
$End   = [DateTimeOffset]::Parse("2026-06-11T16:50:00Z").ToUnixTimeSeconds()
$Step = "15s"

function Export-PromQuery($Name, $Query) {
    Write-Host "Exporting $Name ..."

    $EncodedQuery = [uri]::EscapeDataString($Query)
    $Api = "$PromUrl/api/v1/query_range?query=$EncodedQuery&start=$Start&end=$End&step=$Step"

    $Resp = Invoke-RestMethod -Uri $Api -Method Get

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

Export-PromQuery "01_frontend_cpu" 'sum(rate(container_cpu_usage_seconds_total{namespace="online-boutique", pod=~"frontend-.*", container!="", container!="POD"}[1m]))'

Export-PromQuery "02_all_pods_cpu" 'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="online-boutique", container!="", container!="POD"}[1m]))'

Export-PromQuery "03_frontend_memory" 'sum(container_memory_working_set_bytes{namespace="online-boutique", pod=~"frontend-.*", container!="", container!="POD"})'

Export-PromQuery "04_all_pods_memory" 'sum by (pod) (container_memory_working_set_bytes{namespace="online-boutique", container!="", container!="POD"})'

Export-PromQuery "05_frontend_ready" 'kube_pod_status_ready{namespace="online-boutique", pod=~"frontend-.*", condition="true"}'

Export-PromQuery "06_frontend_network_receive" 'sum(rate(container_network_receive_bytes_total{namespace="online-boutique", pod=~"frontend-.*"}[1m]))'

Export-PromQuery "07_frontend_network_transmit" 'sum(rate(container_network_transmit_bytes_total{namespace="online-boutique", pod=~"frontend-.*"}[1m]))'