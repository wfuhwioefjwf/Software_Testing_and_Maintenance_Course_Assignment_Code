import argparse
import os
import time

import numpy as np
import pandas as pd
import statsmodels.tools.sm_exceptions
from sklearn.metrics import f1_score, jaccard_score
from sklearn.preprocessing import MinMaxScaler
from statsmodels.tsa.stattools import grangercausalitytests

from features import RFeatures, SAXFeatures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a KPIRoot smoke case on Online Boutique metrics.")
    parser.add_argument("--dataset-root", default="./dataset1")
    parser.add_argument("--case-name", default="paymentservice_cpu_001")
    parser.add_argument("--r-window", type=int, default=2)
    parser.add_argument("--output-dir", default="./result")
    return parser.parse_args()


def exact_align(target: pd.DataFrame, suspect: pd.DataFrame) -> pd.DataFrame:
    target = target.copy()
    suspect = suspect.copy()
    target["time_index"] = pd.to_datetime(target["time_index"], unit="ms", utc=True)
    suspect["time_index"] = pd.to_datetime(suspect["time_index"], unit="ms", utc=True)
    aligned = pd.merge(target, suspect, how="inner", on="time_index")
    if not aligned.empty:
        aligned.set_index("time_index", inplace=True)
    return aligned.dropna()


def build_intervals(aligned: pd.DataFrame, r_window: int) -> np.ndarray:
    if aligned.shape[0] <= r_window * 2:
        return np.array([[0, aligned.shape[0]]])
    intervals = RFeatures(r_window, 1.5, 0).get_rSegments(aligned.iloc[:, 0].tolist())
    if intervals.size == 0:
        return np.array([[0, aligned.shape[0]]])
    return intervals


def score_interval(alarm_segment: pd.Series, correlation_segment: pd.Series) -> tuple[float, float] | None:
    if len(alarm_segment) < 2 or len(correlation_segment) < 2:
        return None

    sax_alarm = SAXFeatures(8).sax_transform(alarm_segment).flatten()
    sax_kpi = SAXFeatures(8).sax_transform(correlation_segment).flatten()
    sax_alarm = [ord(element) - ord("a") for element in sax_alarm]
    sax_kpi = [ord(element) - ord("a") for element in sax_kpi]

    similarity_score = jaccard_score(sax_alarm, sax_kpi, average="weighted")
    causality_score = 0.0
    try:
        granger_data = pd.concat([alarm_segment, correlation_segment], axis=1)
        MinMaxScaler().fit_transform(granger_data)
        granger = grangercausalitytests(pd.DataFrame(granger_data), maxlag=1, verbose=False)
        causality_score = granger[1][0]["lrtest"][0]
    except statsmodels.tools.sm_exceptions.InfeasibleTestError:
        pass
    except ValueError:
        pass

    return similarity_score, causality_score


def main() -> int:
    args = parse_args()
    start = time.time()
    case_dir = os.path.join(args.dataset_root, args.case_name)
    label_path = os.path.join(args.dataset_root, "label", f"{args.case_name}_label.csv")

    label = pd.read_csv(label_path)
    correlated = list(label["names"])
    k = min(10, len(correlated))
    n = max(1, int(label["labels"][label["labels"] == 1].count()))
    correlation_scores = {}

    for kpi in correlated:
        alarm_kpi = pd.read_csv(os.path.join(case_dir, "origin_data.csv"))
        correlation_kpi = pd.read_csv(os.path.join(case_dir, kpi))
        aligned = exact_align(alarm_kpi, correlation_kpi)
        if aligned.empty:
            correlation_scores[kpi] = 0.0
            continue

        intervals = build_intervals(aligned, args.r_window)
        similarity_score = 0.0
        causality_score = 0.0
        effective_intervals = 0

        for interval in intervals:
            start_idx = int(interval[0])
            end_idx = int(interval[1])
            if end_idx - start_idx < 2:
                continue

            alarm_segment = aligned.iloc[start_idx:end_idx, 0]
            correlation_segment = aligned.iloc[start_idx:end_idx, 1]
            scored = score_interval(alarm_segment, correlation_segment)
            if scored is None:
                continue

            interval_similarity, interval_causality = scored
            similarity_score += interval_similarity
            causality_score += interval_causality

            effective_intervals += 1

        if effective_intervals == 0:
            fallback = score_interval(aligned.iloc[:, 0], aligned.iloc[:, 1])
            if fallback is None:
                correlation_scores[kpi] = 0.0
                continue
            interval_similarity, interval_causality = fallback
            correlation_scores[kpi] = interval_similarity + 0.1 * interval_causality
            continue

        similarity_score /= effective_intervals
        causality_score /= effective_intervals
        correlation_scores[kpi] = similarity_score + 0.1 * causality_score

    end = time.time()

    threshold = sorted(correlation_scores.values())[-k]
    threshold_f1 = sorted(correlation_scores.values())[-n]

    predict = pd.DataFrame(columns=["names", "predicts", "predicts_f1", "scores"])
    predict["names"] = list(correlation_scores.keys())
    predict["scores"] = list(correlation_scores.values())
    predict["predicts"] = (predict["scores"] >= threshold).astype(int)
    predict["predicts_f1"] = (predict["scores"] >= threshold_f1).astype(int)

    result = pd.merge(label, predict, on="names")
    f1 = f1_score(result["predicts_f1"], result["labels"])
    hit = result[(result["predicts"] == 1) & (result["labels"] == 1)].shape[0] / n

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, f"{args.case_name}_smoke_result.csv")
    result.to_csv(output_path, index=False)

    print(f"case={args.case_name}")
    print(f"elapsed_sec={round(end - start, 4)}")
    print(f"f1={round(float(f1), 6)} hit={round(float(hit), 6)}")
    print(f"result -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())