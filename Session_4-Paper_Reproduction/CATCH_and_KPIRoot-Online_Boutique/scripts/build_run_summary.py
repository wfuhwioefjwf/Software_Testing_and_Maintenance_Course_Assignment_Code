import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a cross-run experiment summary CSV and figure.")
    parser.add_argument("--fault-file", required=True)
    parser.add_argument("--jmeter-root", default="data/raw/jmeter")
    parser.add_argument("--wide-root", default="data/processed/wide")
    parser.add_argument("--catch-root", default="CATCH/result/score")
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument(
        "--kpiroot-result",
        action="append",
        required=True,
        help="Mapping in the form run_id=path/to/kpiroot_result.csv",
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-figure", required=True)
    return parser.parse_args()


def parse_result_mapping(values: list[str]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid --kpiroot-result value: {value}")
        run_id, path = value.split("=", 1)
        mapping[run_id] = Path(path)
    return mapping


def load_latest_catch_report(catch_root: Path, run_id: str) -> Path:
    directory = catch_root / f"online_boutique_{run_id}_catch_smoke"
    matches = sorted(directory.glob("test_report*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"no CATCH report found under {directory}")
    return matches[0]


def to_fault_bucket_count(series: pd.Series) -> int:
    return int(series.astype(str).str.lower().isin(["1", "true", "yes"]).sum())


def compute_kpiroot_metrics(result: pd.DataFrame) -> tuple[float, float, int]:
    positive_predictions = (result["predicts_f1"] == 1).sum()
    positive_labels = (result["labels"] == 1).sum()
    true_positives = ((result["predicts_f1"] == 1) & (result["labels"] == 1)).sum()
    f1 = float((2 * true_positives) / max(1, positive_predictions + positive_labels))
    hit = float(((result["predicts"] == 1) & (result["labels"] == 1)).sum() / max(1, positive_labels))
    return f1, hit, int(positive_labels)


def build_summary_rows(args: argparse.Namespace) -> pd.DataFrame:
    faults = pd.read_csv(args.fault_file)
    faults["start_time"] = pd.to_datetime(faults["start_time"], utc=True, format="ISO8601")
    faults["end_time"] = pd.to_datetime(faults["end_time"], utc=True, format="ISO8601")

    jmeter_root = Path(args.jmeter_root)
    wide_root = Path(args.wide_root)
    catch_root = Path(args.catch_root)
    kpiroot_mapping = parse_result_mapping(args.kpiroot_result)

    rows: list[dict[str, object]] = []

    for run_id in args.run_id:
        jmeter_summary = pd.read_csv(jmeter_root / run_id / "summary.csv")
        wide = pd.read_csv(wide_root / f"{run_id}.csv")
        catch_report_path = load_latest_catch_report(catch_root, run_id)
        catch_report = pd.read_csv(catch_report_path)
        kpiroot_result_path = kpiroot_mapping[run_id]
        kpiroot_result = pd.read_csv(kpiroot_result_path)
        run_faults = faults[faults["run_id"] == run_id].copy()
        if run_faults.empty:
            raise ValueError(f"no fault rows found for {run_id}")

        run_faults = run_faults.sort_values("start_time")
        start_time = run_faults["start_time"].iloc[0]
        end_time = run_faults["end_time"].iloc[-1]
        fault_window_sec = int((end_time - start_time).total_seconds())
        target_service = ";".join(run_faults["target_service"].dropna().astype(str).unique())
        fault_type = ";".join(run_faults["fault_type"].dropna().astype(str).unique())

        catch_auc = float(catch_report.iloc[0, 2])
        kpiroot_f1, kpiroot_hit, positive_candidates = compute_kpiroot_metrics(kpiroot_result)
        fault_bucket_count = to_fault_bucket_count(wide["is_fault"])

        summary_row = jmeter_summary.iloc[0].to_dict()
        summary_row.update(
            {
                "run_id": run_id,
                "target_service": target_service,
                "fault_type": fault_type,
                "fault_start_time": start_time.isoformat(),
                "fault_end_time": end_time.isoformat(),
                "fault_window_sec": fault_window_sec,
                "wide_row_count": int(len(wide)),
                "fault_bucket_count": fault_bucket_count,
                "catch_auc_roc": catch_auc,
                "kpiroot_f1": kpiroot_f1,
                "kpiroot_hit": kpiroot_hit,
                "kpiroot_positive_candidates": positive_candidates,
                "catch_report": str(catch_report_path).replace("\\", "/"),
                "kpiroot_result": str(kpiroot_result_path).replace("\\", "/"),
                "case_summary_figure": f"figures/{run_id}_case_summary.png",
            }
        )
        rows.append(summary_row)

    summary = pd.DataFrame(rows)
    numeric_columns = [
        "sample_count",
        "success_count",
        "error_rate_percent",
        "avg_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "duration_sec",
        "qps",
        "fault_window_sec",
        "wide_row_count",
        "fault_bucket_count",
        "catch_auc_roc",
        "kpiroot_f1",
        "kpiroot_hit",
        "kpiroot_positive_candidates",
    ]
    for column in numeric_columns:
        summary[column] = pd.to_numeric(summary[column])
    return summary


def build_summary_figure(summary: pd.DataFrame, output_path: Path) -> None:
    runs = summary["run_id"].tolist()
    x = np.arange(len(runs))
    width = 0.24

    figure, axes = plt.subplots(3, 1, figsize=(16, 13), constrained_layout=True)

    axes[0].bar(x - width, summary["catch_auc_roc"], width=width, label="CATCH auc_roc", color="#0f4c5c")
    axes[0].bar(x, summary["kpiroot_f1"], width=width, label="KPIRoot f1", color="#e36414")
    axes[0].bar(x + width, summary["kpiroot_hit"], width=width, label="KPIRoot hit@10", color="#6a994e")
    axes[0].set_ylim(0, 1.05)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(runs)
    axes[0].set_title("Algorithm metrics across runs")
    axes[0].set_ylabel("score")
    axes[0].grid(axis="y", alpha=0.2)
    axes[0].legend(loc="upper right")

    axes[1].bar(x - width, summary["avg_latency_ms"], width=width, label="avg latency ms", color="#7b2cbf")
    axes[1].bar(x, summary["p95_latency_ms"], width=width, label="p95 latency ms", color="#d62828")
    axes[1].bar(x + width, summary["qps"], width=width, label="qps", color="#577590")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(runs)
    axes[1].set_title("Traffic metrics across runs")
    axes[1].set_ylabel("value")
    axes[1].grid(axis="y", alpha=0.2)
    axes[1].legend(loc="upper right")

    axes[2].axis("off")
    table_columns = [
        "run_id",
        "target_service",
        "fault_type",
        "duration_sec",
        "fault_window_sec",
        "wide_row_count",
        "fault_bucket_count",
    ]
    table_data = summary[table_columns].copy()
    table = axes[2].table(
        cellText=table_data.values,
        colLabels=[
            "run",
            "service",
            "fault",
            "duration_s",
            "fault_s",
            "wide_rows",
            "fault_buckets",
        ],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.6)
    axes[2].set_title("Experiment coverage summary")

    figure.suptitle("Online Boutique multi-run experiment summary", fontsize=16)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=170, bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    args = parse_args()
    summary = build_summary_rows(args)

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_csv, index=False)

    output_figure = Path(args.output_figure)
    build_summary_figure(summary, output_figure)

    print(f"summary csv -> {output_csv}")
    print(f"summary figure -> {output_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())