param(
    [string]$PromUrl = "http://127.0.0.1:59012",
    [string]$Namespace = "online-boutique",
    [string]$KillMetaPath,
    [int]$PreSeconds = 1200,
    [int]$PostSeconds = 1800,
    [int]$LabelAfterKillSeconds = 600,
    [string]$Step = "15s",
    [string]$OutRoot = "E:\0AI\Online-Boutique\InterFusion\online_boutique_data"
)

if ($KillMetaPath -eq "") {
    throw "Please provide -KillMetaPath"
}

$KillMeta = Get-Content $KillMetaPath -Raw | ConvertFrom-Json

$KillUnix = [int64]$KillMeta.kill_unix
$Start = $KillUnix - $PreSeconds
$End = $KillUnix + $PostSeconds
$LabelStart = $KillUnix
$LabelEnd = $KillUnix + $LabelAfterKillSeconds

$RunName = "prom_test_from_kill_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$OutDir = Join-Path $OutRoot $RunName
$RawDir = Join-Path $OutDir "raw_metrics"
New-Item -ItemType Directory -Force $RawDir | Out-Null

Write-Host "Prometheus URL: $PromUrl"
Write-Host "Namespace: $Namespace"
Write-Host "Kill meta: $KillMetaPath"
Write-Host "Output dir: $OutDir"
Write-Host "Start unix: $Start"
Write-Host "Kill unix:  $KillUnix"
Write-Host "End unix:   $End"
Write-Host "Label:      $LabelStart ~ $LabelEnd"
Write-Host "Step:       $Step"

$Queries = @(
    @{
        Name = "frontend_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"frontend-.*`"}[1m]))"
    },
    @{
        Name = "frontend_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"frontend-.*`"})"
    },
    @{
        Name = "productcatalogservice_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"productcatalogservice-.*`"}[1m]))"
    },
    @{
        Name = "productcatalogservice_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"productcatalogservice-.*`"})"
    },
    @{
        Name = "cartservice_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"cartservice-.*`"}[1m]))"
    },
    @{
        Name = "cartservice_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"cartservice-.*`"})"
    },
    @{
        Name = "checkoutservice_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"checkoutservice-.*`"}[1m]))"
    },
    @{
        Name = "checkoutservice_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"checkoutservice-.*`"})"
    },
    @{
        Name = "redis_cart_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"redis-cart-.*`"}[1m]))"
    },
    @{
        Name = "redis_cart_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"redis-cart-.*`"})"
    },
    @{
        Name = "paymentservice_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"paymentservice-.*`"}[1m]))"
    },
    @{
        Name = "paymentservice_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"paymentservice-.*`"})"
    },
    @{
        Name = "currencyservice_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"currencyservice-.*`"}[1m]))"
    },
    @{
        Name = "currencyservice_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"currencyservice-.*`"})"
    },
    @{
        Name = "shippingservice_cpu"
        Query = "sum(rate(container_cpu_usage_seconds_total{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"shippingservice-.*`"}[1m]))"
    },
    @{
        Name = "shippingservice_memory"
        Query = "sum(container_memory_working_set_bytes{job=`"kubernetes-cadvisor`", namespace=`"$Namespace`", pod=~`"shippingservice-.*`"})"
    }
)

$WideRows = @{}

function Ensure-WideRow($UnixTime) {
    if (-not $WideRows.ContainsKey($UnixTime)) {
        $LocalTime = [DateTimeOffset]::FromUnixTimeSeconds($UnixTime).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
        $UtcTime = [DateTimeOffset]::FromUnixTimeSeconds($UnixTime).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")

        if ($UnixTime -ge $LabelStart -and $UnixTime -le $LabelEnd) {
            $Label = 1
        } else {
            $Label = 0
        }

        $Row = [ordered]@{
            unix_time = $UnixTime
            time_utc = $UtcTime
            time_local = $LocalTime
            label = $Label
        }

        foreach ($Q in $Queries) {
            $Row[$Q.Name] = 0.0
        }

        $WideRows[$UnixTime] = $Row
    }
}

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
            $Value = [double]$V[1]

            Ensure-WideRow $Unix
            $WideRows[$Unix][$Name] = $Value

            [pscustomobject]@{
                unix_time  = $Unix
                time_utc   = [DateTimeOffset]::FromUnixTimeSeconds($Unix).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")
                time_local = [DateTimeOffset]::FromUnixTimeSeconds($Unix).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
                value      = $Value
                metric     = $MetricText
            }
        }
    }

    $Path = Join-Path $RawDir "$Name.csv"
    $Rows | Export-Csv $Path -NoTypeInformation -Encoding UTF8
    Write-Host "Saved raw: $Path"
}

foreach ($Q in $Queries) {
    Export-PromQuery $Q.Name $Q.Query
}

$WidePath = Join-Path $OutDir "wide_test.csv"

$WideObjects = $WideRows.Keys |
    Sort-Object |
    ForEach-Object {
        [pscustomobject]$WideRows[$_]
    }

$WideObjects | Export-Csv $WidePath -NoTypeInformation -Encoding UTF8

$ExportMeta = [pscustomobject]@{
    prom_url = $PromUrl
    namespace = $Namespace
    kill_meta_path = $KillMetaPath
    start_unix = $Start
    kill_unix = $KillUnix
    end_unix = $End
    label_start_unix = $LabelStart
    label_end_unix = $LabelEnd
    step = $Step
    pre_seconds = $PreSeconds
    post_seconds = $PostSeconds
    label_after_kill_seconds = $LabelAfterKillSeconds
    out_dir = $OutDir
    wide_csv = $WidePath
    feature_count = $Queries.Count
    row_count = $WideObjects.Count
}

$ExportMetaPath = Join-Path $OutDir "export_meta.json"
$ExportMeta | ConvertTo-Json -Depth 5 | Out-File $ExportMetaPath -Encoding UTF8

Write-Host "=========================================="
Write-Host "Export finished."
Write-Host "Wide CSV: $WidePath"
Write-Host "Rows: $($WideObjects.Count)"
Write-Host "Feature count: $($Queries.Count)"
Write-Host "Meta: $ExportMetaPath"
Write-Host "=========================================="