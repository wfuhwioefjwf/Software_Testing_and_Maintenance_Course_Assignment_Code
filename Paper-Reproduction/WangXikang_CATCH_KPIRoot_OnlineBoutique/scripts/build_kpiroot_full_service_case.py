import argparse
import json
import math
from pathlib import Path

import pandas as pd


METRIC_FILES = {
    "cpu": "cpu_by_pod.csv",
    "memory": "memory_by_pod.csv",
    "restarts": "restarts_by_pod.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a service-level KPIRoot case from full pod metrics.")
    parser.add_argument("--prom-dir", required=True)
    parser.add_argument("--jmeter-file", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--target-service", required=True)
    parser.add_argument("--origin-column", default="jmeter_p95_latency_ms")
    parser.add_argument(
        "--origin-prom-metric",
        choices=sorted(METRIC_FILES.keys()),
        default=None,
        help="Use the sum of one Prometheus metric across services as origin_data instead of JMeter.",
    )
    parser.add_argument("--drop-constant", action="store_true")
    return parser.parse_args()


def pod_to_service(pod: str) -> str | None:
    if not isinstance(pod, str) or not pod:
        return None
    parts = pod.split("-")
    if len(parts) < 3:
        return pod
    return "-".join(parts[:-2])


def load_metric(path: Path, metric_name: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"empty metric file: {path}")
    if "pod" not in df.columns:
        raise ValueError(f"metric file has no pod column: {path}")
    df = df[df["pod"].notna() & (df["pod"].astype(str) != "")].copy()
    df["service"] = df["pod"].map(pod_to_service)
    df = df[df["service"].notna()].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    grouped = df.groupby(["timestamp", "service"], as_index=False)["value"].sum()
    grouped["metric"] = metric_name
    return grouped


def load_all_metrics(prom_dir: Path) -> pd.DataFrame:
    frames = []
    for metric_name, file_name in METRIC_FILES.items():
        path = prom_dir / file_name
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(load_metric(path, metric_name))
    return pd.concat(frames, ignore_index=True)


def aggregate_jmeter(jmeter_file: Path, timeline: pd.Series) -> pd.DataFrame:
    raw = pd.read_csv(jmeter_file)
    if raw.empty:
        raise ValueError(f"empty JMeter file: {jmeter_file}")
    raw["timestamp"] = pd.to_datetime(pd.to_numeric(raw["timeStamp"], errors="coerce"), unit="ms", utc=True)
    raw["bucket"] = raw["timestamp"].dt.floor("30s")
    raw["elapsed"] = pd.to_numeric(raw["elapsed"], errors="coerce")
    raw["success_bool"] = raw["success"].astype(str).str.lower().eq("true")

    rows = []
    for bucket, group in raw.groupby("bucket"):
        elapsed = group["elapsed"].dropna().sort_values().tolist()
        count = len(group)
        success_count = int(group["success_bool"].sum())
        if elapsed:
            p95 = elapsed[max(math.ceil(len(elapsed) * 0.95) - 1, 0)]
            p99 = elapsed[max(math.ceil(len(elapsed) * 0.99) - 1, 0)]
            avg = sum(elapsed) / len(elapsed)
        else:
            p95 = p99 = avg = 0.0
        rows.append(
            {
                "timestamp": bucket,
                "jmeter_sample_count": count,
                "jmeter_success_count": success_count,
                "jmeter_error_rate_percent": 0.0 if count == 0 else ((count - success_count) / count) * 100,
                "jmeter_avg_latency_ms": avg,
                "jmeter_p95_latency_ms": p95,
                "jmeter_p99_latency_ms": p99,
            }
        )

    jmeter = pd.DataFrame(rows)
    timeline_df = pd.DataFrame({"timestamp": timeline})
    merged = timeline_df.merge(jmeter, on="timestamp", how="left")
    for column in merged.columns:
        if column != "timestamp":
            merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged = merged.ffill().bfill().fillna(0.0)
    return merged


def time_index(timestamps: pd.Series) -> pd.Series:
    return timestamps.astype("int64") // 10**6


def write_metric(path: Path, timestamps: pd.Series, values: pd.Series) -> None:
    output = pd.DataFrame(
        {
            "time_index": time_index(timestamps).astype("int64"),
            "value": pd.to_numeric(values, errors="coerce").fillna(0.0),
        }
    )
    output.to_csv(path, index=False)


def main() -> int:
    args = parse_args()
    prom_dir = Path(args.prom_dir)
    dataset_root = Path(args.dataset_root)
    case_dir = dataset_root / args.case_name
    label_dir = dataset_root / "label"
    case_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)

    metrics = load_all_metrics(prom_dir)
    timeline = pd.Series(sorted(metrics["timestamp"].drop_duplicates()))
    jmeter = aggregate_jmeter(Path(args.jmeter_file), timeline)
    if args.origin_prom_metric:
        origin_series = metrics[metrics["metric"] == args.origin_prom_metric]
        origin = origin_series.groupby("timestamp", as_index=False)["value"].sum()
        origin = pd.DataFrame({"timestamp": timeline}).merge(origin, on="timestamp", how="left")
        origin["value"] = pd.to_numeric(origin["value"], errors="coerce").ffill().bfill().fillna(0.0)
        origin_name = f"prometheus_sum_{args.origin_prom_metric}"
        write_metric(case_dir / "origin_data.csv", origin["timestamp"], origin["value"])
    else:
        if args.origin_column not in jmeter.columns:
            raise KeyError(f"origin column not found: {args.origin_column}")
        origin_name = args.origin_column
        write_metric(case_dir / "origin_data.csv", jmeter["timestamp"], jmeter[args.origin_column])

    labels = []
    skipped_constants = []
    services = sorted(metrics["service"].dropna().unique())
    for service in services:
        service_metrics = metrics[metrics["service"] == service]
        for metric_name in sorted(service_metrics["metric"].unique()):
            series = service_metrics[service_metrics["metric"] == metric_name][["timestamp", "value"]]
            aligned = pd.DataFrame({"timestamp": timeline}).merge(series, on="timestamp", how="left")
            aligned["value"] = pd.to_numeric(aligned["value"], errors="coerce").ffill().bfill().fillna(0.0)
            if args.drop_constant and aligned["value"].nunique(dropna=False) <= 1:
                skipped_constants.append(f"{service}_{metric_name}.csv")
                continue
            file_name = f"{service}_{metric_name}.csv"
            write_metric(case_dir / file_name, aligned["timestamp"], aligned["value"])
            labels.append({"names": file_name, "labels": int(service == args.target_service)})

    label_path = label_dir / f"{args.case_name}_label.csv"
    pd.DataFrame(labels).to_csv(label_path, index=False)

    metadata = {
        "case_name": args.case_name,
        "target_service": args.target_service,
        "origin_column": origin_name,
        "points": int(len(timeline)),
        "services": services,
        "candidates": int(len(labels)),
        "positives": int(sum(item["labels"] for item in labels)),
        "skipped_constants": skipped_constants,
    }
    with (case_dir / "case_meta.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    print(f"kpiroot full-service case -> {case_dir}")
    print(f"target_service={args.target_service}")
    print(f"origin_column={origin_name}")
    print(f"points={metadata['points']} services={len(services)} candidates={metadata['candidates']} positives={metadata['positives']}")
    if skipped_constants:
        print(f"skipped_constants={len(skipped_constants)}")
    print(f"label -> {label_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
