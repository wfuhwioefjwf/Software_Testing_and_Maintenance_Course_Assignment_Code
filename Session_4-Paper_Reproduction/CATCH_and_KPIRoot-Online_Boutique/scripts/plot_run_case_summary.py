import argparse
import os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot a single experiment case summary figure.")
    parser.add_argument("--wide-file", required=True)
    parser.add_argument("--fault-file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--catch-report", required=True)
    parser.add_argument("--kpiroot-result", required=True)
    parser.add_argument("--output-file", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wide = pd.read_csv(args.wide_file)
    faults = pd.read_csv(args.fault_file)
    catch_report = pd.read_csv(args.catch_report)
    kpiroot_result = pd.read_csv(args.kpiroot_result)

    wide["timestamp"] = pd.to_datetime(wide["timestamp"], utc=True)
    faults = faults[faults["run_id"] == args.run_id].copy()
    faults["start_time"] = pd.to_datetime(faults["start_time"], utc=True)
    faults["end_time"] = pd.to_datetime(faults["end_time"], utc=True)

    cpu_norm = wide["cpu_total"] / max(wide["cpu_total"].max(), 1e-9)
    memory_norm = wide["memory_total"] / max(wide["memory_total"].max(), 1e-9)
    network_norm = wide["network_rx_total"] / max(wide["network_rx_total"].max(), 1e-9)
    latency_norm = wide["jmeter_avg_latency_ms"] / max(wide["jmeter_avg_latency_ms"].max(), 1.0)

    catch_auc = float(catch_report.iloc[0, 2])
    kpiroot_f1 = float((2 * ((kpiroot_result["predicts_f1"] == 1) & (kpiroot_result["labels"] == 1)).sum()) /
                       max(1, ((kpiroot_result["predicts_f1"] == 1).sum() + (kpiroot_result["labels"] == 1).sum())))
    kpiroot_hit = float(((kpiroot_result["predicts"] == 1) & (kpiroot_result["labels"] == 1)).sum() / max(1, (kpiroot_result["labels"] == 1).sum()))

    figure, axes = plt.subplots(3, 1, figsize=(14, 12), constrained_layout=True)

    axes[0].plot(wide["timestamp"], cpu_norm, label="cpu_total_norm", linewidth=2.0, color="#0f4c5c")
    axes[0].plot(wide["timestamp"], memory_norm, label="memory_total_norm", linewidth=2.0, color="#e36414")
    axes[0].plot(wide["timestamp"], network_norm, label="network_rx_total_norm", linewidth=2.0, color="#6a994e")
    axes[0].plot(wide["timestamp"], latency_norm, label="jmeter_avg_latency_norm", linewidth=2.0, color="#7b2cbf")

    for _, fault in faults.iterrows():
        axes[0].axvspan(fault["start_time"], fault["end_time"], color="#d62828", alpha=0.18)
        axes[0].text(
            fault["start_time"],
            1.02,
            f"{fault['target_service']} {fault['fault_type']}",
            color="#9d0208",
            fontsize=10,
            ha="left",
            va="bottom",
        )

    axes[0].set_title(f"{args.run_id} KPI timeline")
    axes[0].set_ylabel("normalized value")
    axes[0].legend(loc="upper right", ncol=2)
    axes[0].grid(alpha=0.2)
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    metric_names = ["CATCH auc_roc", "KPIRoot f1", "KPIRoot hit@10"]
    metric_values = [catch_auc, kpiroot_f1, kpiroot_hit]
    metric_colors = ["#0f4c5c", "#e36414", "#6a994e"]
    axes[1].bar(metric_names, metric_values, color=metric_colors, width=0.55)
    axes[1].set_ylim(0, 1.05)
    axes[1].set_title("Algorithm summary")
    axes[1].set_ylabel("score")
    axes[1].grid(axis="y", alpha=0.2)
    for index, value in enumerate(metric_values):
        axes[1].text(index, value + 0.03, f"{value:.3f}", ha="center", va="bottom", fontsize=10)

    top_rows = kpiroot_result.sort_values(["labels", "names"], ascending=[False, True]).copy()
    top_rows["display_score"] = top_rows["scores"].where(top_rows["scores"] > 0, 0.02)
    colors = ["#d62828" if label == 1 else "#adb5bd" for label in top_rows["labels"]]
    axes[2].barh(top_rows["names"], top_rows["display_score"], color=colors)
    axes[2].set_title("KPIRoot candidate labels and smoke scores")
    axes[2].set_xlabel("score (0-valued bars lifted to 0.02 for visibility)")
    axes[2].grid(axis="x", alpha=0.2)
    axes[2].invert_yaxis()

    figure.suptitle(f"Online Boutique {args.run_id} case summary", fontsize=16)
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    figure.savefig(args.output_file, dpi=160, bbox_inches="tight")
    plt.close(figure)
    print(f"figure -> {args.output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())