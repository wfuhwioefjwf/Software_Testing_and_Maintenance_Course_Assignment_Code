import argparse
from pathlib import Path

import pandas as pd


META_COLUMNS = {"timestamp", "label", "is_fault", "target_service", "fault_type"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an offline KPIRoot v2 case from an existing wide table."
    )
    parser.add_argument("--wide-file", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--target-service", required=True)
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--origin-column", default="jmeter_p95_latency_ms")
    parser.add_argument(
        "--old-case-dir",
        default=None,
        help="Optional previous KPIRoot case dir. Used only to carry repaired target memory if present.",
    )
    parser.add_argument(
        "--drop-constant",
        action="store_true",
        help="Drop non-positive candidate columns whose values are constant.",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        help="Exclude candidate columns with this prefix. Can be passed multiple times.",
    )
    return parser.parse_args()


def time_index_from_wide(wide: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(wide["timestamp"], utc=True).astype("int64") // 10**6


def to_metric(time_index: pd.Series, values: pd.Series) -> pd.DataFrame:
    output = pd.DataFrame()
    output["time_index"] = time_index.astype("int64")
    output["value"] = pd.to_numeric(values, errors="coerce").fillna(0.0)
    return output


def is_numeric_candidate(
    wide: pd.DataFrame, column: str, origin_column: str, exclude_prefixes: list[str]
) -> bool:
    if column in META_COLUMNS or column == origin_column:
        return False
    if any(column.startswith(prefix) for prefix in exclude_prefixes):
        return False
    return pd.api.types.is_numeric_dtype(pd.to_numeric(wide[column], errors="coerce"))


def is_positive_name(name: str, target_service: str) -> bool:
    return target_service in name


def write_metric(path: Path, metric: pd.DataFrame) -> None:
    metric.to_csv(path, index=False)


def carry_repaired_target_memory(
    old_case_dir: Path | None,
    time_index: pd.Series,
    target_service: str,
    case_dir: Path,
) -> tuple[str, bool] | None:
    if old_case_dir is None:
        return None

    source = old_case_dir / f"{target_service}_memory.csv"
    if not source.exists():
        return None

    old = pd.read_csv(source)
    if len(old) != len(time_index):
        return None

    name = f"{target_service}_memory_repaired.csv"
    metric = to_metric(time_index, old["value"])
    write_metric(case_dir / name, metric)
    return name, True


def main() -> int:
    args = parse_args()
    wide = pd.read_csv(args.wide_file)
    if args.origin_column not in wide.columns:
        raise KeyError(f"origin column not found: {args.origin_column}")

    dataset_root = Path(args.dataset_root)
    case_dir = dataset_root / args.case_name
    label_dir = dataset_root / "label"
    case_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)

    time_index = time_index_from_wide(wide)
    if time_index.nunique() != len(time_index):
        raise ValueError("wide timestamps are not unique after conversion to milliseconds")

    origin = to_metric(time_index, wide[args.origin_column])
    write_metric(case_dir / "origin_data.csv", origin)

    labels: list[dict[str, object]] = []
    skipped_constants: list[str] = []
    candidate_columns = [
        column
        for column in wide.columns
        if is_numeric_candidate(wide, column, args.origin_column, args.exclude_prefix)
    ]

    for column in candidate_columns:
        values = pd.to_numeric(wide[column], errors="coerce").fillna(0.0)
        is_positive = is_positive_name(column, args.target_service)
        if args.drop_constant and not is_positive and values.nunique(dropna=False) <= 1:
            skipped_constants.append(column)
            continue
        name = f"{column}.csv"
        write_metric(case_dir / name, to_metric(time_index, values))
        labels.append({"names": name, "labels": int(is_positive)})

    old_case_dir = Path(args.old_case_dir) if args.old_case_dir else None
    carried = carry_repaired_target_memory(old_case_dir, time_index, args.target_service, case_dir)
    if carried is not None:
        name, is_positive = carried
        labels.append({"names": name, "labels": int(is_positive)})

    positives = sum(int(item["labels"]) for item in labels)
    if positives == 0:
        raise RuntimeError("no positive KPIRoot candidates were generated")

    label_path = label_dir / f"{args.case_name}_label.csv"
    pd.DataFrame(labels).to_csv(label_path, index=False)

    print(f"kpiroot v2 case -> {case_dir}")
    print(f"target_service={args.target_service}")
    print(f"origin_column={args.origin_column}")
    print(f"origin_points={len(origin)} candidates={len(labels)} positives={positives}")
    if skipped_constants:
        print(f"skipped_constant_non_positive={len(skipped_constants)}")
    print(f"label -> {label_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
