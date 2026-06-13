import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone


DEFAULT_QUERIES = {
    "cpu_topk": 'topk(20, rate(container_cpu_usage_seconds_total[1m]))',
    "memory_topk": 'topk(20, container_memory_working_set_bytes)',
    "restarts_by_pod": 'sum by (pod) (kube_pod_container_status_restarts_total{namespace="default"})',
    "network_rx_total": 'sum(rate(container_network_receive_bytes_total[1m]))',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Prometheus query_range results to CSV files.")
    parser.add_argument("--base-url", required=True, help="Prometheus base URL, e.g. http://127.0.0.1:9090")
    parser.add_argument("--run-id", required=True, help="Experiment run identifier, e.g. run_001")
    parser.add_argument("--start", required=True, help="UTC start time in ISO format, e.g. 2026-05-29T12:40:00Z")
    parser.add_argument("--end", required=True, help="UTC end time in ISO format, e.g. 2026-05-29T12:45:00Z")
    parser.add_argument("--step", default="30s", help="Prometheus query_range step, default 30s")
    parser.add_argument(
        "--output-root",
        default=os.path.join("data", "raw", "prometheus"),
        help="Output root directory, default data/raw/prometheus",
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Custom query in name=promql form. May be repeated. If omitted, built-in defaults are used.",
    )
    return parser.parse_args()


def parse_iso8601(value: str) -> float:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).timestamp()


def build_query_map(query_args):
    if not query_args:
        return DEFAULT_QUERIES.copy()

    query_map = {}
    for item in query_args:
        if "=" not in item:
            raise ValueError(f"Invalid --query value: {item}")
        name, promql = item.split("=", 1)
        name = name.strip()
        promql = promql.strip()
        if not name or not promql:
            raise ValueError(f"Invalid --query value: {item}")
        query_map[name] = promql
    return query_map


def http_get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_query_range(base_url: str, promql: str, start: float, end: float, step: str) -> list:
    query_string = urllib.parse.urlencode(
        {
            "query": promql,
            "start": start,
            "end": end,
            "step": step,
        }
    )
    url = f"{base_url.rstrip('/')}/api/v1/query_range?{query_string}"
    payload = http_get_json(url)
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    return payload["data"]["result"]


def format_utc(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(file_path: str, series: list) -> int:
    label_keys = sorted({key for item in series for key in item.get("metric", {}).keys() if key != "__name__"})
    fieldnames = ["timestamp", "epoch_seconds", *label_keys, "value"]

    row_count = 0
    with open(file_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in series:
            metric = item.get("metric", {})
            for epoch_seconds, value in item.get("values", []):
                row = {
                    "timestamp": format_utc(float(epoch_seconds)),
                    "epoch_seconds": epoch_seconds,
                    "value": value,
                }
                for label_key in label_keys:
                    row[label_key] = metric.get(label_key, "")
                writer.writerow(row)
                row_count += 1
    return row_count


def write_manifest(file_path: str, manifest: dict) -> None:
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


def main() -> int:
    args = parse_args()
    start = parse_iso8601(args.start)
    end = parse_iso8601(args.end)
    query_map = build_query_map(args.query)

    run_dir = os.path.join(args.output_root, args.run_id)
    os.makedirs(run_dir, exist_ok=True)

    manifest = {
        "run_id": args.run_id,
        "base_url": args.base_url,
        "start": args.start,
        "end": args.end,
        "step": args.step,
        "queries": query_map,
        "files": {},
    }

    for name, promql in query_map.items():
        series = fetch_query_range(args.base_url, promql, start, end, args.step)
        output_file = os.path.join(run_dir, f"{name}.csv")
        row_count = write_csv(output_file, series)
        manifest["files"][name] = {
            "path": output_file,
            "row_count": row_count,
        }
        print(f"exported {name}: {row_count} rows -> {output_file}")

    manifest_path = os.path.join(run_dir, "manifest.json")
    write_manifest(manifest_path, manifest)
    print(f"manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise