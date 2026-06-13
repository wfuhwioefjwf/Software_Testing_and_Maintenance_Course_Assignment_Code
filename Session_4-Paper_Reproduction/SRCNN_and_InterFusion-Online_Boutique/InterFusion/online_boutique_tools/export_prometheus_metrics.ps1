param(
    [string]$PromUrl = "http://127.0.0.1:59012",
    [string]$Namespace = "online-boutique",
    [string]$RunType = "train",
    [int]$LookbackSeconds = 7200,
    [string]$Step = "15s",
    [string]$MetaPath = "",
    [string]$OutRoot = "E:\0AI\Online-Boutique\InterFusion\online_boutique_data"
)

$RunName = "prom_${RunType}_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$OutDir = Join-Path $OutRoot $RunName
$RawDir = Join-Path $OutDir "raw_metrics"
New-Item -ItemType Directory -Force $RawDir | Out-Null

Write-Host "Prometheus URL: $PromUrl"
Write-Host "Namespace: $Namespace"
Write-Host "RunType: $RunType"
Write-Host "Output dir: $OutDir"

# ========== 时间范围 ==========
if ($MetaPath -ne "") {
    Write-Host "Using meta file: $MetaPath"
    $Meta = Get-Content $MetaPath -Raw | ConvertFrom-Json

    $Start = [int64]$Meta.experiment_start_unix
    $End = [int64]$Meta.experiment_end_unix
    $LabelStart = [int64]$Meta.label_start_unix
    $LabelEnd = [int64]$Meta.label_end_unix
} else {
    $End = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $Start = $End - $LookbackSeconds
    $LabelStart = -1
    $LabelEnd = -1
}

Write-Host "Start unix: $Start"
Write-Host "End unix:   $End"
Write-Host "Step:       $Step"

# ========== 查询列表：模型第一版只用 CPU + Memory ==========
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

# ========== 宽表容器 ==========
$WideRows = @{}

function Ensure-WideRow($UnixTime) {
    if (-not $WideRows.ContainsKey($UnixTime)) {
        $LocalTime = [DateTimeOffset]::FromUnixTimeSeconds($UnixTime).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
        $UtcTime = [DateTimeOffset]::FromUnixTimeSeconds($UnixTime).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")

        if ($RunType -eq "train") {
            $Label = 0
        } elseif ($LabelStart -ge 0 -and $UnixTime -ge $LabelStart -and $UnixTime -le $LabelEnd) {
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

# ========== 导出函数 ==========
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

# ========== 执行导出 ==========
foreach ($Q in $Queries) {
    Export-PromQuery $Q.Name $Q.Query
}

# ========== 保存宽表 ==========
$WidePath = Join-Path $OutDir "wide_${RunType}.csv"

$WideObjects = $WideRows.Keys |
    Sort-Object |
    ForEach-Object {
        [pscustomobject]$WideRows[$_]
    }

$WideObjects | Export-Csv $WidePath -NoTypeInformation -Encoding UTF8

# ========== 保存本次导出信息 ==========
$ExportMeta = [pscustomobject]@{
    prom_url = $PromUrl
    namespace = $Namespace
    run_type = $RunType
    start_unix = $Start
    end_unix = $End
    step = $Step
    lookback_seconds = $LookbackSeconds
    meta_path = $MetaPath
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