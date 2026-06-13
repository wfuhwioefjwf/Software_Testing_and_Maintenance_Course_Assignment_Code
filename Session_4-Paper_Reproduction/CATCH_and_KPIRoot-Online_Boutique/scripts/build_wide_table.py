import argparse
import json
import os
import re
from datetime import timedelta

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a run-level wide table from Prometheus, JMeter and fault labels.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prom-dir", required=True)
    parser.add_argument("--jmeter-file", required=True)
    parser.add_argument("--fault-file", required=True)
    parser.add_argument("--output-file", required=True)
    return parser.parse_args()


def sanitize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]+", "_", value.strip("_"))


def load_manifest(prom_dir: str) -> dict:
    manifest_path = os.path.join(prom_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_time_index(manifest: dict) -> pd.DataFrame:
    start = pd.to_datetime(manifest["start"], utc=True)
    end = pd.to_datetime(manifest["end"], utc=True)
    step = pd.to_timedelta(manifest["step"])
    timestamps = pd.date_range(start=start, end=end, freq=step)
    return pd.DataFrame({"timestamp": timestamps})


def add_single_metric(df: pd.DataFrame, file_path: str, column_name: str) -> pd.DataFrame:
    metric = pd.read_csv(file_path)
    metric["timestamp"] = pd.to_datetime(metric["timestamp"], utc=True)
    metric["value"] = pd.to_numeric(metric["value"], errors="coerce")
    metric = metric[["timestamp", "value"]].groupby("timestamp", as_index=False).mean()
    metric.rename(columns={"value": column_name}, inplace=True)
    return df.merge(metric, on="timestamp", how="left")


def add_global_from_id(df: pd.DataFrame, file_path: str, id_value: str, column_name: str) -> pd.DataFrame:
    metric = pd.read_csv(file_path)
    if "id" not in metric.columns:
        return df
    metric = metric[metric["id"] == id_value].copy()
    if metric.empty:
        return df
    metric["timestamp"] = pd.to_datetime(metric["timestamp"], utc=True)
    metric["value"] = pd.to_numeric(metric["value"], errors="coerce")
    metric = metric[["timestamp", "value"]].groupby("timestamp", as_index=False).mean()
    metric.rename(columns={"value": column_name}, inplace=True)
    return df.merge(metric, on="timestamp", how="left")


def add_pod_metric(df: pd.DataFrame, file_path: str, prefix: str) -> pd.DataFrame:
    metric = pd.read_csv(file_path)
    if "pod" not in metric.columns:
        return df
    metric = metric[metric["pod"].fillna("") != ""].copy()
    if metric.empty:
        return df
    metric["timestamp"] = pd.to_datetime(metric["timestamp"], utc=True)
    metric["value"] = pd.to_numeric(metric["value"], errors="coerce")
    metric["column_name"] = metric["pod"].apply(lambda pod: f"{prefix}_{sanitize(str(pod))}")
    pivot = metric.pivot_table(index="timestamp", columns="column_name", values="value", aggfunc="mean")
    pivot.reset_index(inplace=True)
    return df.merge(pivot, on="timestamp", how="left")


def add_jmeter_metrics(df: pd.DataFrame, jmeter_file: str, bucket_size: pd.Timedelta, floor_freq: str) -> pd.DataFrame:
    result = pd.read_csv(jmeter_file)
    result["timestamp"] = pd.to_datetime(result["timeStamp"], unit="ms", utc=True).dt.floor(floor_freq)
    result["elapsed"] = pd.to_numeric(result["elapsed"], errors="coerce")
    result["success"] = result["success"].astype(str).str.lower() == "true"

    rows = []
    for timestamp, group in result.groupby("timestamp"):
        elapsed_sorted = sorted(group["elapsed"].dropna().tolist())
        if not elapsed_sorted:
            continue
        p95 = float(pd.Series(elapsed_sorted).quantile(0.95, interpolation="higher"))
        p99 = float(pd.Series(elapsed_sorted).quantile(0.99, interpolation="higher"))
        sample_count = int(len(group))
        success_count = int(group["success"].sum())
        error_rate = round((1 - success_count / sample_count) * 100, 4)
        rows.append(
            {
                "timestamp": timestamp,
                "jmeter_sample_count": sample_count,
                "jmeter_success_count": success_count,
                "jmeter_error_rate_percent": error_rate,
                "jmeter_avg_latency_ms": round(float(group["elapsed"].mean()), 4),
                "jmeter_p95_latency_ms": p95,
                "jmeter_p99_latency_ms": p99,
            }
        )

    if not rows:
        return df

    jmeter_df = pd.DataFrame(rows)
    return df.merge(jmeter_df, on="timestamp", how="left")


def add_fault_labels(df: pd.DataFrame, fault_file: str, run_id: str, bucket_size: pd.Timedelta) -> pd.DataFrame:
    faults = pd.read_csv(fault_file)
    faults = faults[faults["run_id"] == run_id].copy()
    df["label"] = 0
    df["is_fault"] = False
    df["target_service"] = ""
    df["fault_type"] = ""

    if faults.empty:
        return df

    faults["start_time"] = pd.to_datetime(faults["start_time"], utc=True)
    faults["end_time"] = pd.to_datetime(faults["end_time"], utc=True)
    bucket_end_delta = bucket_size

    for index, row in df.iterrows():
        bucket_start = row["timestamp"]
        bucket_end = bucket_start + bucket_end_delta
        overlapping = faults[(faults["start_time"] < bucket_end) & (faults["end_time"] >= bucket_start)]
        if overlapping.empty:
            continue
        first = overlapping.iloc[0]
        df.at[index, "label"] = 1
        df.at[index, "is_fault"] = True
        df.at[index, "target_service"] = first["target_service"]
        df.at[index, "fault_type"] = first["fault_type"]
    return df


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.prom_dir)
    wide = build_time_index(manifest)
    bucket_size = pd.to_timedelta(manifest["step"])
    floor_freq = manifest["step"]

    wide = add_global_from_id(wide, os.path.join(args.prom_dir, "cpu_topk.csv"), "/", "cpu_total")
    wide = add_global_from_id(wide, os.path.join(args.prom_dir, "memory_topk.csv"), "/", "memory_total")
    wide = add_single_metric(wide, os.path.join(args.prom_dir, "network_rx_total.csv"), "network_rx_total")
    wide = add_pod_metric(wide, os.path.join(args.prom_dir, "restarts_by_pod.csv"), "restarts")
    wide = add_jmeter_metrics(wide, args.jmeter_file, bucket_size, floor_freq)
    wide = add_fault_labels(wide, args.fault_file, args.run_id, bucket_size)

    wide = wide.sort_values("timestamp")
    wide["timestamp"] = wide["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    numeric_columns = [column for column in wide.columns if column not in {"timestamp", "target_service", "fault_type"}]
    for column in numeric_columns:
        if wide[column].dtype == bool:
            continue
        wide[column] = pd.to_numeric(wide[column], errors="coerce")
        wide[column] = wide[column].fillna(0)

    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    wide.to_csv(args.output_file, index=False)
    print(f"wide table -> {args.output_file}")
    print(f"rows={len(wide)} cols={len(wide.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())