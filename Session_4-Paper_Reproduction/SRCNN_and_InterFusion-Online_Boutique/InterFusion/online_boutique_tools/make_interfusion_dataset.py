import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train_csv", required=True)
    parser.add_argument("--test_csv", required=True)
    parser.add_argument("--out_dir", default=r"E:\0AI\Online-Boutique\InterFusion\data\processed")
    parser.add_argument("--dataset_name", default="online_boutique")
    args = parser.parse_args()

    train_csv = Path(args.train_csv)
    test_csv = Path(args.test_csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_csv(train_csv)
    test_df = pd.read_csv(test_csv)

    train_df = train_df.sort_values("unix_time").drop_duplicates("unix_time")
    test_df = test_df.sort_values("unix_time").drop_duplicates("unix_time")

    ignore_cols = {"unix_time", "time_utc", "time_local", "label"}
    feature_cols = [c for c in train_df.columns if c not in ignore_cols]

    missing_in_test = [c for c in feature_cols if c not in test_df.columns]
    if missing_in_test:
        raise ValueError(f"测试集缺少这些特征列: {missing_in_test}")

    test_extra = [c for c in test_df.columns if c not in ignore_cols and c not in feature_cols]
    if test_extra:
        print(f"警告：测试集有额外特征列，将忽略: {test_extra}")

    train_x = train_df[feature_cols].astype("float32").values
    test_x = test_df[feature_cols].astype("float32").values
    test_label = test_df["label"].astype("int32").values

    train_x = np.nan_to_num(train_x, nan=0.0, posinf=0.0, neginf=0.0)
    test_x = np.nan_to_num(test_x, nan=0.0, posinf=0.0, neginf=0.0)

    dataset = args.dataset_name

    with open(out_dir / f"{dataset}_train.pkl", "wb") as f:
        pickle.dump(train_x, f)

    with open(out_dir / f"{dataset}_test.pkl", "wb") as f:
        pickle.dump(test_x, f)

    with open(out_dir / f"{dataset}_test_label.pkl", "wb") as f:
        pickle.dump(test_label, f)

    with open(out_dir / f"{dataset}_features.txt", "w", encoding="utf-8") as f:
        for col in feature_cols:
            f.write(col + "\n")

    label_counts = {
        str(k): int(v)
        for k, v in zip(*np.unique(test_label, return_counts=True))
    }

    meta = {
        "dataset_name": dataset,
        "train_csv": str(train_csv),
        "test_csv": str(test_csv),
        "train_shape": list(train_x.shape),
        "test_shape": list(test_x.shape),
        "test_label_shape": list(test_label.shape),
        "feature_dim": len(feature_cols),
        "feature_cols": feature_cols,
        "test_label_counts": label_counts,
    }

    with open(out_dir / f"{dataset}_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print("InterFusion dataset generated.")
    print("train_x:", train_x.shape)
    print("test_x:", test_x.shape)
    print("test_label:", test_label.shape)
    print("feature_dim:", len(feature_cols))
    print("test label counts:", label_counts)
    print("out_dir:", out_dir)


if __name__ == "__main__":
    main()
