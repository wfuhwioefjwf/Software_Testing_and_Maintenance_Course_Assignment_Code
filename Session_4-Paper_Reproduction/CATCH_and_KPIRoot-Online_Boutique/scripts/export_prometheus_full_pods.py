import argparse
import csv
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone


QUERIES = {
    "cpu_by_pod": 'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="default",pod!=""}[1m]))',
    "memory_by_pod": 'sum by (pod) (container_memory_working_set_bytes{namespace="default",pod!=""})',
    "restarts_by_pod": 'sum by (pod) (kube_pod_container_status_restarts_total{namespace="default",pod!=""})',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export full pod-level Online Boutique metrics.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step", default="30s")
    parser.add_argument("--output-root", default=os.path.join("data", "raw", "prometheus_full"))
    return parser.parse_args()


def parse_iso8601(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


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
    payload = http_get_json(f"{base_url.rstrip('/')}/api/v1/query_range?{query_string}")
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


def main() -> int:
    args = parse_args()
    start = parse_iso8601(args.start)
    end = parse_iso8601(args.end)
    run_dir = os.path.join(args.output_root, args.run_id)
    os.makedirs(run_dir, exist_ok=True)

    manifest = {
        "run_id": args.run_id,
        "base_url": args.base_url,
        "start": args.start,
        "end": args.end,
        "step": args.step,
        "queries": QUERIES,
        "files": {},
    }
    for name, promql in QUERIES.items():
        series = fetch_query_range(args.base_url, promql, start, end, args.step)
        output_file = os.path.join(run_dir, f"{name}.csv")
        row_count = write_csv(output_file, series)
        manifest["files"][name] = {"path": output_file, "row_count": row_count}
        print(f"exported {name}: {row_count} rows -> {output_file}")

    manifest_path = os.path.join(run_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(f"manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
