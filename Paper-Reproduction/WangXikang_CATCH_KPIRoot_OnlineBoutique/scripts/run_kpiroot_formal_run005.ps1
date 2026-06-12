$ErrorActionPreference = 'Stop'

$python = 'E:\SEFinalWork\.conda\python.exe'
$runId = 'run_005'
$caseName = 'recommendationservice_cpustress_formal_001'
$targetService = 'recommendationservice'
$jmeterBat = 'D:\apache-jmeter-5.6.3\bin\jmeter.bat'
$jmx = 'E:\SEFinalWork\jmeter\online-boutique-productpage-recommendation-formal.jmx'
$jmeterDir = "E:\SEFinalWork\data\raw\jmeter\$runId"
$promRoot = 'E:\SEFinalWork\data\raw\prometheus_full'
$promDir = Join-Path $promRoot $runId
$chaosYaml = 'E:\SEFinalWork\chaos\stress-recommendationservice-cpu-formal.yaml'
$faultMeta = 'E:\SEFinalWork\work\run_005_fault_meta.json'

New-Item -ItemType Directory -Force -Path $jmeterDir, $promDir, 'E:\SEFinalWork\work' | Out-Null
Remove-Item -LiteralPath (Join-Path $jmeterDir 'result.csv'), (Join-Path $jmeterDir 'jmeter.log'), $faultMeta -Force -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'apache-jmeter' -or $_.CommandLine -match 'ApacheJMeter' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

kubectl delete -f $chaosYaml --ignore-not-found | Out-Null

$frontJob = Start-Job -ScriptBlock { kubectl port-forward deployment/frontend 8080:8080 }
$promJob = Start-Job -ScriptBlock { kubectl port-forward -n monitoring svc/prometheus 9090:9090 }

try {
    Start-Sleep -Seconds 8
    $front = (Invoke-WebRequest -Uri 'http://127.0.0.1:8080/product/OLJCESPC7Z' -UseBasicParsing -TimeoutSec 20).StatusCode
    $prom = (Invoke-WebRequest -Uri 'http://127.0.0.1:9090/-/ready' -UseBasicParsing -TimeoutSec 20).StatusCode
    "PORTS_READY product=$front prometheus=$prom"

    $runStart = (Get-Date).ToUniversalTime()
    $faultJob = Start-Job -ArgumentList $chaosYaml, $faultMeta -ScriptBlock {
        param($chaosYaml, $faultMeta)
        Start-Sleep -Seconds 300
        $faultStart = (Get-Date).ToUniversalTime()
        kubectl apply -f $chaosYaml | Out-String | Write-Output
        Start-Sleep -Seconds 310
        $faultEnd = (Get-Date).ToUniversalTime()
        kubectl delete -f $chaosYaml --ignore-not-found | Out-String | Write-Output
        [PSCustomObject]@{
            fault_start = $faultStart.ToString('yyyy-MM-ddTHH:mm:ssZ')
            fault_end = $faultEnd.ToString('yyyy-MM-ddTHH:mm:ssZ')
        } | ConvertTo-Json | Set-Content -LiteralPath $faultMeta -Encoding UTF8
    }

    $resultFile = Join-Path $jmeterDir 'result.csv'
    $logFile = Join-Path $jmeterDir 'jmeter.log'
    "JMETER_FOREGROUND_START run_start=$($runStart.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    & $jmeterBat -n -t $jmx -l $resultFile -j $logFile '-Jjmeter.save.saveservice.output_format=csv'
    $runEnd = (Get-Date).ToUniversalTime()
    "JMETER_FOREGROUND_END run_end=$($runEnd.ToString('yyyy-MM-ddTHH:mm:ssZ'))"

    Wait-Job $faultJob -Timeout 60 | Out-Null
    Receive-Job $faultJob | Out-String
    if (-not (Test-Path -LiteralPath $faultMeta)) {
        throw 'fault metadata was not written'
    }
    $fault = Get-Content -LiteralPath $faultMeta -Raw | ConvertFrom-Json
    "FAULT_WINDOW start=$($fault.fault_start) end=$($fault.fault_end)"

    $faultFile = 'E:\SEFinalWork\data\labels\fault_events.csv'
    $existing = Import-Csv -LiteralPath $faultFile
    $filtered = $existing | Where-Object { $_.run_id -ne $runId }
    $newRow = [PSCustomObject]@{
        run_id = $runId
        fault_id = 'recommendationservice_cpustress_001'
        start_time = $fault.fault_start
        end_time = $fault.fault_end
        target_service = $targetService
        fault_type = 'cpu-stress'
        chaos_namespace = 'chaos-testing'
        chaos_resource = 'recommendationservice-cpu-stress-formal'
        expected_root_cause = $targetService
        status = 'completed'
        notes = 'cpu workers=2; load=80; duration=300s; product_path=/product/OLJCESPC7Z; total_window=900s'
    }
    @($filtered) + $newRow | Export-Csv -LiteralPath $faultFile -NoTypeInformation -Encoding UTF8
    "FAULT_EVENT_RECORDED $faultFile"

    $exportStart = $runStart.AddSeconds(-30).ToString('yyyy-MM-ddTHH:mm:ssZ')
    $exportEnd = $runEnd.AddSeconds(30).ToString('yyyy-MM-ddTHH:mm:ssZ')
    & $python 'E:\SEFinalWork\scripts\export_prometheus.py' `
        --base-url 'http://127.0.0.1:9090' `
        --run-id $runId `
        --start $exportStart `
        --end $exportEnd `
        --step '30s' `
        --output-root $promRoot `
        --query 'cpu_by_pod=sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="default",pod!=""}[1m]))' `
        --query 'memory_by_pod=sum by (pod) (container_memory_working_set_bytes{namespace="default",pod!=""})' `
        --query 'restarts_by_pod=sum by (pod) (kube_pod_container_status_restarts_total{namespace="default",pod!=""})'

    & $python -c "import csv, pathlib, math; p=pathlib.Path(r'$resultFile'); rows=list(csv.DictReader(p.open(newline='', encoding='utf-8'))); elapsed=sorted(float(r['elapsed']) for r in rows); count=len(rows); success=sum(1 for r in rows if r['success'].lower()=='true'); stamps=sorted(float(r['timeStamp']) for r in rows); avg=round(sum(elapsed)/count,2) if count else 0; p95=int(elapsed[max(math.ceil(count*0.95)-1,0)]) if count else 0; p99=int(elapsed[max(math.ceil(count*0.99)-1,0)]) if count else 0; duration=max(round((stamps[-1]-stamps[0])/1000),1) if count else 0; qps=round(count/duration,4) if duration else 0; err=round(((count-success)/count)*100,4) if count else 0; out=pathlib.Path(r'$jmeterDir')/'summary.csv'; f=out.open('w', newline='', encoding='utf-8'); w=csv.writer(f); w.writerow(['run_id','sample_count','success_count','error_rate_percent','avg_latency_ms','p95_latency_ms','p99_latency_ms','duration_sec','qps']); w.writerow([r'$runId',count,success,err,avg,p95,p99,int(duration),qps]); f.close(); print('JMETER_SUMMARY', out, count, success, err, avg, p95, p99, duration, qps)"

    & $python 'E:\SEFinalWork\scripts\build_kpiroot_full_service_case.py' `
        --prom-dir $promDir `
        --jmeter-file $resultFile `
        --dataset-root 'E:\SEFinalWork\KPIRoot\dataset1' `
        --case-name $caseName `
        --target-service $targetService `
        --origin-column 'jmeter_p95_latency_ms'
}
finally {
    kubectl delete -f $chaosYaml --ignore-not-found | Out-Null
    Stop-Job $frontJob, $promJob -ErrorAction SilentlyContinue
    Remove-Job $frontJob, $promJob -Force -ErrorAction SilentlyContinue
}
