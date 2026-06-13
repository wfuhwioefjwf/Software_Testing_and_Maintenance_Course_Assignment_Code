#!/usr/bin/env python3
"""将短时故障数据转换为 KAN-AD 格式"""
import json
import os
import numpy as np

CHAOS_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chaos_data_short")
KANAD_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "KAN-AD", "datasets", "UTS", "ChaosBoutiqueShort")

def load_json(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def process_scenario(baseline_data, fault_data, fault_label, output_dir):
    metrics = sorted(set(s['metric_name'] for s in fault_data.values()))
    pods = sorted(set(s['pod'] for s in fault_data.values()))

    count = 0
    for metric in metrics:
        for pod in pods:
            if pod in ('', 'POD', 'unknown'):
                continue
            baseline_values = []
            for key, series in baseline_data.items():
                if series['pod'] == pod and series['metric_name'] == metric:
                    baseline_values = series['values']
                    break
            fault_values = []
            for key, series in fault_data.items():
                if series['pod'] == pod and series['metric_name'] == metric:
                    fault_values = series['values']
                    break
            if len(baseline_values) < 20 or len(fault_values) < 5:
                continue
            curve_name = f"{fault_label}_{metric}_{pod}"
            curve_dir = os.path.join(output_dir, curve_name)
            os.makedirs(curve_dir, exist_ok=True)
            train = np.array(baseline_values)
            test = np.array(fault_values)
            train_label = np.zeros(len(train))
            mean = np.mean(train)
            std = np.std(train)
            if std > 0:
                z_scores = np.abs((test - mean) / std)
                test_label = (z_scores > 2.0).astype(int)
            else:
                test_label = np.zeros(len(test))
            np.save(os.path.join(curve_dir, "train.npy"), train)
            np.save(os.path.join(curve_dir, "test.npy"), test)
            np.save(os.path.join(curve_dir, "train_label.npy"), train_label)
            np.save(os.path.join(curve_dir, "test_label.npy"), test_label)
            info = {"dataset": "ChaosBoutiqueShort", "curve_name": curve_name, "metric_name": metric, "pod": pod, "fault_type": fault_label, "train_length": len(train), "test_length": len(test), "anomaly_ratio": float(np.sum(test_label) / max(len(test_label), 1))}
            with open(os.path.join(curve_dir, "info.json"), 'w') as f:
                json.dump(info, f, indent=2)
            count += 1
    return count

def main():
    print("="*60)
    print("短时故障数据转换为 KAN-AD 格式")
    print("="*60)
    os.makedirs(KANAD_DATA_DIR, exist_ok=True)
    baseline_file = os.path.join(CHAOS_DATA_DIR, "baseline_normal.json")
    baseline_data = load_json(baseline_file)
    fault_files = sorted([f for f in os.listdir(CHAOS_DATA_DIR) if f.endswith("_fault.json")])
    print(f"Found {len(fault_files)} fault scenarios")

    total_curves = 0
    for f in fault_files:
        label = f.replace("_fault.json", "")
        fault_data = load_json(os.path.join(CHAOS_DATA_DIR, f))
        count = process_scenario(baseline_data, fault_data, label, KANAD_DATA_DIR)
        total_curves += count
        print(f"  {label}: {count} curves")

    print(f"\nTotal curves: {total_curves}")
    print(f"Output: {KANAD_DATA_DIR}")

if __name__ == '__main__':
    main()
