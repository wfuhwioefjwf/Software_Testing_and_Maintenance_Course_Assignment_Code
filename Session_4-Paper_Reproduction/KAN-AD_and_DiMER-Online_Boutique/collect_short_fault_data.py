#!/usr/bin/env python3
"""
短时故障数据采集脚本 - 更贴近真实场景
- 故障持续时间：2 分钟
- 采样间隔：5 秒
- 基线采集：15 分钟
- 3 轮实验
"""
import subprocess
import time
import json
import os
import urllib.parse
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chaos_data_short")
PROM_POD = None
SAMPLE_INTERVAL = 5

METRICS = {
    'cpu': 'container_cpu_usage_seconds_total{namespace="default",pod!=""}',
    'memory': 'container_memory_working_set_bytes{namespace="default",pod!=""}',
    'net_rx': 'container_network_receive_bytes_total{namespace="default",pod!=""}',
    'net_tx': 'container_network_transmit_bytes_total{namespace="default",pod!=""}',
}

# 短时故障实验配置
CHAOS_EXPERIMENTS = [
    # 第一轮
    {"name": "network-delay-frontend", "type": "NetworkChaos", "duration": 120, "label": "nd_frontend_r1", "round": 1},
    {"name": "network-loss-cart", "type": "NetworkChaos", "duration": 120, "label": "nl_cart_r1", "round": 1},
    {"name": "cpu-stress-checkout", "type": "StressChaos", "duration": 120, "label": "cs_checkout_r1", "round": 1},
    {"name": "mem-stress-recommend", "type": "StressChaos", "duration": 120, "label": "ms_recommend_r1", "round": 1},
    {"name": "pod-kill-ad", "type": "PodChaos", "duration": 60, "label": "pk_ad_r1", "round": 1},
    {"name": "network-delay-product", "type": "NetworkChaos", "duration": 120, "label": "nd_product_r1", "round": 1},
    {"name": "cpu-stress-currency", "type": "StressChaos", "duration": 120, "label": "cs_currency_r1", "round": 1},
    {"name": "network-loss-payment", "type": "NetworkChaos", "duration": 120, "label": "nl_payment_r1", "round": 1},
    # 第二轮
    {"name": "network-delay-frontend", "type": "NetworkChaos", "duration": 120, "label": "nd_frontend_r2", "round": 2},
    {"name": "network-loss-cart", "type": "NetworkChaos", "duration": 120, "label": "nl_cart_r2", "round": 2},
    {"name": "cpu-stress-checkout", "type": "StressChaos", "duration": 120, "label": "cs_checkout_r2", "round": 2},
    {"name": "mem-stress-recommend", "type": "StressChaos", "duration": 120, "label": "ms_recommend_r2", "round": 2},
    {"name": "pod-kill-ad", "type": "PodChaos", "duration": 60, "label": "pk_ad_r2", "round": 2},
    {"name": "network-delay-product", "type": "NetworkChaos", "duration": 120, "label": "nd_product_r2", "round": 2},
    {"name": "cpu-stress-currency", "type": "StressChaos", "duration": 120, "label": "cs_currency_r2", "round": 2},
    {"name": "network-loss-payment", "type": "NetworkChaos", "duration": 120, "label": "nl_payment_r2", "round": 2},
    # 第三轮
    {"name": "network-delay-frontend", "type": "NetworkChaos", "duration": 120, "label": "nd_frontend_r3", "round": 3},
    {"name": "network-loss-cart", "type": "NetworkChaos", "duration": 120, "label": "nl_cart_r3", "round": 3},
    {"name": "cpu-stress-checkout", "type": "StressChaos", "duration": 120, "label": "cs_checkout_r3", "round": 3},
    {"name": "mem-stress-recommend", "type": "StressChaos", "duration": 120, "label": "ms_recommend_r3", "round": 3},
    {"name": "pod-kill-ad", "type": "PodChaos", "duration": 60, "label": "pk_ad_r3", "round": 3},
    {"name": "network-delay-product", "type": "NetworkChaos", "duration": 120, "label": "nd_product_r3", "round": 3},
    {"name": "cpu-stress-currency", "type": "StressChaos", "duration": 120, "label": "cs_currency_r3", "round": 3},
    {"name": "network-loss-payment", "type": "NetworkChaos", "duration": 120, "label": "nl_payment_r3", "round": 3},
]


def get_prom_pod():
    global PROM_POD
    if PROM_POD is None:
        result = subprocess.run(
            'kubectl get pods -n monitoring -l app=prometheus -o jsonpath="{.items[0].metadata.name}"',
            shell=True, capture_output=True, text=True, timeout=15
        )
        PROM_POD = result.stdout.strip().strip('"')
    return PROM_POD


def query_prom(query):
    pod = get_prom_pod()
    encoded = urllib.parse.quote(query)
    url = f'http://localhost:9090/api/v1/query?query={encoded}'
    try:
        result = subprocess.run(
            f'kubectl exec -n monitoring {pod} -- wget -qO- "{url}"',
            shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except:
        pass
    return None


def collect_snapshot():
    snapshot = {}
    for name, query in METRICS.items():
        data = query_prom(query)
        if data and data.get('status') == 'success':
            for series in data['data']['result']:
                m = series['metric']
                pod = m.get('pod', 'unknown')
                if not pod or pod == 'unknown':
                    continue
                key = f"{name}_{pod}"
                snapshot[key] = {
                    'metric': name,
                    'pod': pod,
                    'value': float(series['value'][1]),
                    'timestamp': series['value'][0],
                }
    return snapshot


def collect_series(duration, interval, label):
    print(f"\n  Collecting {label} for {duration}s (every {interval}s)...")
    start = time.time()
    all_snapshots = []
    count = 0

    while time.time() - start < duration:
        snap = collect_snapshot()
        all_snapshots.append(snap)
        count += 1
        elapsed = time.time() - start
        remaining = duration - elapsed
        if count % 12 == 0:
            print(f"    [{count}] {elapsed:.0f}s / {remaining:.0f}s remaining, {len(snap)} series")
        if remaining > interval:
            time.sleep(interval)
        else:
            break

    merged = {}
    for snap in all_snapshots:
        for key, info in snap.items():
            if key not in merged:
                merged[key] = {
                    'metric_name': info['metric'],
                    'pod': info['pod'],
                    'timestamps': [],
                    'values': [],
                }
            merged[key]['timestamps'].append(info['timestamp'])
            merged[key]['values'].append(info['value'])

    print(f"  Done: {count} snapshots, {len(merged)} series")
    return merged


def apply_chaos(exp):
    print(f"\n{'='*50}")
    print(f"APPLYING: {exp['name']} (Round {exp['round']})")
    print(f"{'='*50}")

    manifest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chaos_experiments.yaml")
    with open(manifest, 'r') as f:
        content = f.read()

    for doc in content.split('---'):
        if f"name: {exp['name']}" in doc:
            tmp = os.path.join(DATA_DIR, "tmp.yaml")
            with open(tmp, 'w') as f:
                f.write(doc.strip())
            r = subprocess.run(f"kubectl apply -f {tmp}", shell=True, capture_output=True, text=True, timeout=30)
            print(f"  {r.stdout.strip()}")
            os.remove(tmp)
            return True
    return False


def delete_chaos(exp):
    subprocess.run(
        f"kubectl delete {exp['type']} {exp['name']} -n default",
        shell=True, capture_output=True, text=True, timeout=30
    )


def save(data, label, phase):
    path = os.path.join(DATA_DIR, f"{label}_{phase}.json")
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {path} ({len(data)} series)")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("="*60)
    print("短时故障数据采集")
    print(f"故障持续时间: 2 分钟 | 采样间隔: 5 秒")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    pod = get_prom_pod()
    print(f"Prometheus Pod: {pod}")

    test = query_prom('up')
    if not test or test.get('status') != 'success':
        print("ERROR: Cannot connect to Prometheus!")
        return
    print(f"Prometheus 连接正常\n")

    # 计算预计时间
    baseline_time = 900  # 15 分钟
    fault_time = sum(exp['duration'] + 30 for exp in CHAOS_EXPERIMENTS)
    total_time = baseline_time + fault_time
    print(f"预计总时长: {total_time/60:.0f} 分钟")
    print(f"  - 基线: {baseline_time/60:.0f} 分钟")
    print(f"  - 故障: {len(CHAOS_EXPERIMENTS)} 个实验\n")

    # 阶段 1: 基线
    print("="*60)
    print("PHASE 1: 基线采集 (15 分钟)")
    print("="*60)
    baseline = collect_series(duration=baseline_time, interval=SAMPLE_INTERVAL, label="baseline")
    save(baseline, "baseline", "normal")

    # 阶段 2: 故障实验
    print("\n" + "="*60)
    print(f"PHASE 2: 故障实验 ({len(CHAOS_EXPERIMENTS)} 个)")
    print("="*60)

    for i, exp in enumerate(CHAOS_EXPERIMENTS):
        print(f"\n--- [{i+1}/{len(CHAOS_EXPERIMENTS)}] {exp['label']} ---")

        if not apply_chaos(exp):
            print("  Skipped!")
            continue

        time.sleep(10)
        fault = collect_series(duration=exp['duration'], interval=SAMPLE_INTERVAL, label=exp['label'])
        save(fault, exp['label'], "fault")

        delete_chaos(exp)
        print(f"  Cooling down 30s...")
        time.sleep(30)

    print("\n" + "="*60)
    print("数据采集完成！")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据目录: {DATA_DIR}")
    print("="*60)


if __name__ == '__main__':
    main()
