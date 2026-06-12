import argparse
import os

import pandas as pd


META_COLUMNS = [
    "file_name",
    "freq",
    "if_univariate",
    "size",
    "length",
    "trend",
    "seasonal",
    "stationary",
    "transition",
    "shifting",
    "correlation",
    "train_lens",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a CATCH anomaly-detection dataset from a wide table.")
    parser.add_argument("--wide-file", required=True)
    parser.add_argument("--catch-root", required=True)
    parser.add_argument("--output-name", required=True, help="Target CSV file name inside CATCH dataset, e.g. online_boutique_run_001.csv")
    return parser.parse_args()


def ensure_metadata_file(metadata_path: str) -> pd.DataFrame:
    if os.path.exists(metadata_path):
        metadata = pd.read_csv(metadata_path)
        for column in META_COLUMNS:
            if column not in metadata.columns:
                metadata[column] = ""
        return metadata[META_COLUMNS]
    return pd.DataFrame(columns=META_COLUMNS)


def build_long_table(wide: pd.DataFrame) -> pd.DataFrame:
    numeric_columns = wide.select_dtypes(include=["number", "bool"]).columns.tolist()
    feature_columns = [column for column in numeric_columns if column != "label"]
    feature_columns = [column for column in feature_columns if wide[column].nunique(dropna=False) > 1]

    rows = []
    timestamps = pd.to_datetime(wide["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    for column in feature_columns:
        values = pd.to_numeric(wide[column], errors="coerce").fillna(0)
        rows.append(pd.DataFrame({"date": timestamps, "value": values, "cols": column}))

    label_values = pd.to_numeric(wide["label"], errors="coerce").fillna(0).astype(int)
    rows.append(pd.DataFrame({"date": timestamps, "value": label_values, "cols": "label"}))
    return pd.concat(rows, ignore_index=True), feature_columns


def main() -> int:
    args = parse_args()
    wide = pd.read_csv(args.wide_file)
    long_table, feature_columns = build_long_table(wide)

    dataset_root = os.path.join(args.catch_root, "dataset", "anomaly_detect")
    data_dir = os.path.join(dataset_root, "data")
    os.makedirs(data_dir, exist_ok=True)

    output_path = os.path.join(data_dir, args.output_name)
    long_table.to_csv(output_path, index=False)

    metadata_path = os.path.join(dataset_root, "DETECT_META.csv")
    metadata = ensure_metadata_file(metadata_path)
    metadata = metadata[metadata["file_name"] != args.output_name].copy()
    metadata = pd.concat(
        [
            metadata,
            pd.DataFrame(
                [
                    {
                        "file_name": args.output_name,
                        "freq": "other",
                        "if_univariate": False,
                        "size": "user",
                        "length": len(wide),
                        "trend": "",
                        "seasonal": "",
                        "stationary": "",
                        "transition": "",
                        "shifting": "",
                        "correlation": "",
                        "train_lens": max(1, len(wide) - 3),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    metadata.to_csv(metadata_path, index=False)

    print(f"catch dataset -> {output_path}")
    print(f"metadata -> {metadata_path}")
    print(f"timestamps={len(wide)} features={len(feature_columns)} total_rows={len(long_table)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())