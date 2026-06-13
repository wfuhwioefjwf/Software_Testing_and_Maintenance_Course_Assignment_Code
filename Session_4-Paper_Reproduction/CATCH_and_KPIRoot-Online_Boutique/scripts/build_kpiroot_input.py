import argparse
import json
import os
import urllib.parse
import urllib.request

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a KPIRoot case from Prometheus and wide-table data.")
    parser.add_argument("--wide-file", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step", default="30s")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--target-service", required=True)
    parser.add_argument("--case-name", default=None)
    return parser.parse_args()


def http_get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_query_range(base_url: str, promql: str, start: str, end: str, step: str) -> pd.DataFrame:
    query_string = urllib.parse.urlencode(
        {
            "query": promql,
            "start": start,
            "end": end,
            "step": step,
        }
    )
    payload = http_get_json(f"{base_url.rstrip('/')}/api/v1/query_range?{query_string}")
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    series_list = payload["data"]["result"]
    rows = []
    for item in series_list:
        for epoch_seconds, value in item.get("values", []):
            rows.append({"timestamp": float(epoch_seconds), "value": float(value)})
    if not rows:
        raise RuntimeError(f"Prometheus query returned no rows: {promql}")
    df = pd.DataFrame(rows)
    df = df.groupby("timestamp", as_index=False)["value"].sum()
    df["time_index"] = (df["timestamp"] * 1000).astype(int)
    return df[["time_index", "value"]]


def to_kpi_file(df: pd.DataFrame, value_column: str) -> pd.DataFrame:
    output = pd.DataFrame()
    output["time_index"] = pd.to_datetime(df["timestamp"], utc=True).astype("int64") // 10**6
    output["value"] = pd.to_numeric(df[value_column], errors="coerce").fillna(0)
    return output


def find_first_column(columns, prefix: str) -> str:
    for column in columns:
        if column.startswith(prefix):
            return column
    raise KeyError(f"No column starts with {prefix}")


def find_all_columns(columns, prefix: str) -> list[str]:
    return sorted([column for column in columns if column.startswith(prefix)])


def write_metric(file_path: str, metric_df: pd.DataFrame) -> None:
    metric_df.to_csv(file_path, index=False)


def write_labels(file_path: str, labels: list[dict]) -> None:
    pd.DataFrame(labels).to_csv(file_path, index=False)


def main() -> int:
    args = parse_args()
    wide = pd.read_csv(args.wide_file)
    case_name = args.case_name or f"{args.target_service}_cpu_001"

    dataset_root = args.dataset_root
    case_dir = os.path.join(dataset_root, case_name)
    label_dir = os.path.join(dataset_root, "label")
    os.makedirs(case_dir, exist_ok=True)
    os.makedirs(label_dir, exist_ok=True)

    origin_cpu = fetch_query_range(
        args.base_url,
        f'sum(rate(container_cpu_usage_seconds_total{{pod=~"{args.target_service}-.*"}}[1m]))',
        args.start,
        args.end,
        args.step,
    )
    target_memory = fetch_query_range(
        args.base_url,
        f'sum(container_memory_working_set_bytes{{pod=~"{args.target_service}-.*"}})',
        args.start,
        args.end,
        args.step,
    )

    write_metric(os.path.join(case_dir, "origin_data.csv"), origin_cpu)

    restart_columns = [column for column in wide.columns if column.startswith("restarts_")]
    target_restart_columns = find_all_columns(restart_columns, f"restarts_{args.target_service}_")
    other_restart_columns = [
        column for column in sorted(restart_columns) if not column.startswith(f"restarts_{args.target_service}_")
    ]

    candidate_specs = [
        (f"{args.target_service}_memory.csv", target_memory, True),
        ("cpu_total.csv", to_kpi_file(wide, "cpu_total"), False),
        ("memory_total.csv", to_kpi_file(wide, "memory_total"), False),
        ("network_rx_total.csv", to_kpi_file(wide, "network_rx_total"), False),
        ("jmeter_avg_latency_ms.csv", to_kpi_file(wide, "jmeter_avg_latency_ms"), False),
        ("jmeter_p95_latency_ms.csv", to_kpi_file(wide, "jmeter_p95_latency_ms"), False),
        ("jmeter_p99_latency_ms.csv", to_kpi_file(wide, "jmeter_p99_latency_ms"), False),
    ]

    for column in target_restart_columns:
        candidate_specs.append((f"{column}.csv", to_kpi_file(wide, column), True))

    for column in other_restart_columns[:6]:
        candidate_specs.append((f"{column}.csv", to_kpi_file(wide, column), False))

    if not target_restart_columns:
        raise RuntimeError(f"No restart columns found for target service: {args.target_service}")

    labels = []
    for file_name, metric_df, is_positive in candidate_specs:
        write_metric(os.path.join(case_dir, file_name), metric_df)
        labels.append({"names": file_name, "labels": int(is_positive)})

    label_path = os.path.join(label_dir, f"{case_name}_label.csv")
    write_labels(label_path, labels)

    print(f"kpiroot case -> {case_dir}")
    print(f"target_service={args.target_service}")
    print(f"origin_points={len(origin_cpu)} candidates={len(candidate_specs)} positives={sum(item['labels'] for item in labels)}")
    print(f"label -> {label_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())