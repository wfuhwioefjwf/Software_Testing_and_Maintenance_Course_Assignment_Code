import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"

SCENARIOS = [
    ("light_load", 5, RESULTS_DIR / "light_load_report"),
    ("medium_load", 15, RESULTS_DIR / "medium_load_report"),
    ("high_load", 30, RESULTS_DIR / "high_load_report"),
]

RAW_FIELDS = [
    "scenario",
    "concurrent_users",
    "avg_response_time_ms",
    "p90_response_time_ms",
    "p95_response_time_ms",
    "throughput_per_sec",
    "received_kb_per_sec",
    "sent_kb_per_sec",
]

NORMALIZED_FIELDS = [
    "scenario",
    "concurrent_users",
    "avg_response_time_norm",
    "p90_response_time_norm",
    "p95_response_time_norm",
    "throughput_norm",
    "received_kb_norm",
    "sent_kb_norm",
]

METRICS = [
    ("avg_response_time_ms", "avg_response_time_norm", "Average Response Time", ["meanResTime", "meanResponseTime", "average", "avgResTime"]),
    ("p90_response_time_ms", "p90_response_time_norm", "90% Response Time", ["pct1ResTime", "p90", "90thPercentile", "percentile90"]),
    ("p95_response_time_ms", "p95_response_time_norm", "95% Response Time", ["pct2ResTime", "p95", "95thPercentile", "percentile95"]),
    ("throughput_per_sec", "throughput_norm", "Throughput", ["throughput", "throughputPerSec"]),
    ("received_kb_per_sec", "received_kb_norm", "Received KB/sec", ["receivedKBytesPerSec", "receivedKBPerSec", "received_kb_per_sec"]),
    ("sent_kb_per_sec", "sent_kb_norm", "Sent KB/sec", ["sentKBytesPerSec", "sentKBPerSec", "sent_kb_per_sec"]),
]


def find_statistics_json(report_dir):
    if not report_dir.exists():
        raise FileNotFoundError(f"Report directory not found: {report_dir}")
    matches = list(report_dir.rglob("statistics.json"))
    if not matches:
        raise FileNotFoundError(f"statistics.json not found under report directory: {report_dir}")
    return matches[0]


def load_total_row(statistics_path):
    with statistics_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        for key in ("Total", "total", "TOTAL"):
            if key in data and isinstance(data[key], dict):
                return data[key]
        for value in data.values():
            if isinstance(value, dict) and str(value.get("transaction", "")).lower() == "total":
                return value

    raise KeyError(f"Total row not found in statistics file: {statistics_path}")


def get_number(row, candidate_names, metric_label, statistics_path):
    for name in candidate_names:
        if name in row:
            value = row[name]
            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Field {name!r} for metric {metric_label!r} is not numeric in {statistics_path}: {value!r}"
                ) from error

    available = ", ".join(sorted(row.keys()))
    expected = ", ".join(candidate_names)
    raise KeyError(
        f"Cannot find metric {metric_label!r} in {statistics_path}. "
        f"Expected one of: {expected}. Available fields: {available}"
    )


def read_raw_metrics():
    rows = []
    for scenario, users, report_dir in SCENARIOS:
        statistics_path = find_statistics_json(report_dir)
        total = load_total_row(statistics_path)
        row = {
            "scenario": scenario,
            "concurrent_users": users,
        }
        for raw_key, _, label, candidates in METRICS:
            row[raw_key] = get_number(total, candidates, label, statistics_path)
        rows.append(row)
    return rows


def normalize_metrics(raw_rows):
    baseline = raw_rows[0]
    normalized_rows = []

    for row in raw_rows:
        normalized = {
            "scenario": row["scenario"],
            "concurrent_users": row["concurrent_users"],
        }
        for raw_key, norm_key, label, _ in METRICS:
            baseline_value = baseline[raw_key]
            if baseline_value == 0:
                print(f"Warning: light_load baseline for {label} is 0; {norm_key} cannot be normalized.")
                normalized[norm_key] = ""
            else:
                normalized[norm_key] = row[raw_key] / baseline_value
        normalized_rows.append(normalized)

    return normalized_rows


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def print_table(title, rows, fields):
    print()
    print(title)
    print("-" * len(title))
    print(",".join(fields))
    for row in rows:
        values = []
        for field in fields:
            value = row[field]
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        print(",".join(values))


def plot_normalized_trends(normalized_rows):
    users = [row["concurrent_users"] for row in normalized_rows]

    plt.figure(figsize=(10, 6))
    for _, norm_key, label, _ in METRICS:
        values = [row[norm_key] for row in normalized_rows]
        if any(value == "" for value in values):
            print(f"Warning: skip plotting {label} because it has non-normalized values.")
            continue
        plt.plot(users, values, marker="o", linewidth=2, label=label)

    plt.title("Normalized Performance Trends under Different Loads")
    plt.xlabel("Concurrent Users")
    plt.ylabel("Normalized Value (Light Load = 1.0)")
    plt.xticks(users)
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "normalized_performance_trend.png", dpi=300)
    plt.close()


def main():
    raw_rows = read_raw_metrics()
    normalized_rows = normalize_metrics(raw_rows)

    raw_csv = RESULTS_DIR / "performance_summary.csv"
    normalized_csv = RESULTS_DIR / "normalized_performance_summary.csv"

    write_csv(raw_csv, raw_rows, RAW_FIELDS)
    write_csv(normalized_csv, normalized_rows, NORMALIZED_FIELDS)
    plot_normalized_trends(normalized_rows)

    print_table("Raw Performance Metrics", raw_rows, RAW_FIELDS)
    print_table("Normalized Performance Metrics", normalized_rows, NORMALIZED_FIELDS)
    print()
    print(f"Wrote: {raw_csv}")
    print(f"Wrote: {normalized_csv}")
    print(f"Wrote: {RESULTS_DIR / 'normalized_performance_trend.png'}")


if __name__ == "__main__":
    main()
