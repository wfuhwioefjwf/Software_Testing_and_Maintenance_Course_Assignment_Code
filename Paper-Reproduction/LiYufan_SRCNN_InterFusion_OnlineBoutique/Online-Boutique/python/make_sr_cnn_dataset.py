
"""
make_sr_cnn_dataset.py

作用：
1. 读取 Prometheus 导出的 frontend Pod CPU CSV。
2. 读取 ChaosMesh 随机故障注入脚本保存的 fault_windows.csv。
3. 生成 SR-CNN 数据集：
   - synthetic_train：根据正常数据人工合成异常，作为训练集/验证集。
   - real_test：根据真实 ChaosMesh 故障时间窗口给真实 Prometheus 数据打标签，作为测试集。
4. 每个样本是一个长度为 WINDOW_SIZE 的 SR saliency window。
5. 标签 y=1 表示该窗口中心点处于异常/故障状态，y=0 表示正常。

说明：
论文 KDD19 SR-CNN 的核心思路是：
先对时间序列计算 Spectral Residual saliency map，
再把 saliency map 输入 CNN，用合成异常训练 CNN 判别器。
本脚本是课程实验规模下的工程化简化复现，不追求微软论文中的工业规模训练数据。
"""

import os
import json
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd


# =========================
# 1. 用户配置区
# =========================

# 项目结构默认：
# E:\0AI\Online-Boutique\
#   python\make_sr_cnn_dataset.py
#   prometheus-online-boutique-pod-data\01_frontend_pod_cpu.csv
#   chaos-yamls\fault_windows.csv
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

CSV_PATH = PROJECT_DIR / "prometheus-online-boutique-pod-data" / "01_frontend_pod_cpu.csv"
FAULT_WINDOWS_PATH = PROJECT_DIR / "chaos-yamls" / "fault_windows.csv"
OUT_DIR = PROJECT_DIR / "sr-cnn-dataset"

TIME_COLUMN = "time_local"
VALUE_COLUMN = "value"

WINDOW_SIZE = 32
Q = 3

# 合成训练集规模。你的真实数据较少，不建议设太大，否则重复样本过多。
N_SYNTHETIC_ANOMALY = 1200
N_SYNTHETIC_NORMAL = 1200

TRAIN_RATIO = 0.8
RANDOM_SEED = 42

# 真实测试集标签：窗口中心点落在 fault_windows.csv 任一故障区间内，则 label=1。
# 如果你暂时没有 fault_windows.csv，可以把 MANUAL_FAULT_WINDOWS 填上。
# 格式：[("2026-06-12 01:32:57", "2026-06-12 01:38:27")]
MANUAL_FAULT_WINDOWS = []

# 是否只保留真实故障附近的数据
FILTER_AROUND_FAULTS = True

# 故障开始前保留多少秒
PADDING_BEFORE_SECONDS = 600

# 故障结束后保留多少秒
PADDING_AFTER_SECONDS = 600

def filter_df_around_fault_windows(df: pd.DataFrame, fault_windows):
    """
    只保留故障注入窗口前后一定范围的数据。
    例如每个故障窗口保留：
    [start - PADDING_BEFORE_SECONDS, end + PADDING_AFTER_SECONDS]

    如果没有 fault_windows，则返回原始 df。
    """
    if not FILTER_AROUND_FAULTS:
        return df.copy()

    if len(fault_windows) == 0:
        print("警告：没有 fault_windows，无法按故障附近筛选，将使用完整 CSV。")
        return df.copy()

    keep_mask = pd.Series(False, index=df.index)

    for start, end in fault_windows:
        extended_start = start - pd.Timedelta(seconds=PADDING_BEFORE_SECONDS)
        extended_end = end + pd.Timedelta(seconds=PADDING_AFTER_SECONDS)

        keep_mask |= (df["time"] >= extended_start) & (df["time"] <= extended_end)

    filtered = df.loc[keep_mask].copy().reset_index(drop=True)

    if len(filtered) == 0:
        print("警告：按故障窗口筛选后数据为空，将使用完整 CSV。请检查 fault_windows.csv 的时间和 Prometheus CSV 的 time_local 是否一致。")
        return df.copy()

    print(f"原始 CSV 点数：{len(df)}")
    print(f"按故障附近筛选后点数：{len(filtered)}")

    return filtered


# =========================
# 2. SR 算法：和 SR 阈值法共用核心思想
# =========================

def moving_average_same(x: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return x.copy()
    kernel = np.ones(window, dtype=float) / window
    return np.convolve(x, kernel, mode="same")


def spectral_residual_transform(x: np.ndarray, q: int = 3) -> np.ndarray:
    """
    计算 SR saliency map：
    FFT -> log amplitude -> average log amplitude -> spectral residual -> inverse FFT.
    """
    x = np.asarray(x, dtype=float)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    fft_result = np.fft.fft(x)
    amplitude = np.abs(fft_result)
    phase = np.angle(fft_result)

    log_amplitude = np.log(amplitude + 1e-8)
    avg_log_amplitude = moving_average_same(log_amplitude, q)
    spectral_residual = log_amplitude - avg_log_amplitude

    saliency = np.abs(np.fft.ifft(np.exp(spectral_residual + 1j * phase)))
    return saliency


def normalize_window(x: np.ndarray) -> np.ndarray:
    """
    对每个 saliency window 单独标准化。
    CNN 训练时更稳定。
    """
    x = np.asarray(x, dtype=np.float32)
    mean = float(np.mean(x))
    std = float(np.std(x))
    if std < 1e-8:
        return x - mean
    return (x - mean) / std


# =========================
# 3. 数据读取与真实故障标签
# =========================

def load_prometheus_csv(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 Prometheus CSV：{csv_path}")

    df = pd.read_csv(csv_path)

    if TIME_COLUMN not in df.columns or VALUE_COLUMN not in df.columns:
        raise ValueError(
            f"CSV 必须包含 {TIME_COLUMN} 和 {VALUE_COLUMN} 两列，当前列为：{list(df.columns)}"
        )

    df = df[[TIME_COLUMN, VALUE_COLUMN]].copy()
    df.columns = ["time", "value"]
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["time", "value"])
    df = df.sort_values("time").reset_index(drop=True)

    # 同一时间重复值取平均
    df = df.groupby("time", as_index=False)["value"].mean()
    return df


def load_fault_windows(path: Path):
    """
    fault_windows.csv 由 run-random-cpu-stress.ps1 生成。
    期望列：
    start_local,end_local,start_utc,end_utc,duration_seconds,rest_seconds,chaos_name,target
    """
    windows = []

    for s, e in MANUAL_FAULT_WINDOWS:
        windows.append((pd.to_datetime(s), pd.to_datetime(e)))

    if path.exists():
        fw = pd.read_csv(path)
        if "start_local" in fw.columns and "end_local" in fw.columns:
            for _, row in fw.iterrows():
                s = pd.to_datetime(row["start_local"], errors="coerce")
                e = pd.to_datetime(row["end_local"], errors="coerce")
                if pd.notna(s) and pd.notna(e):
                    windows.append((s, e))

    # 去掉非法窗口
    windows = [(s, e) for s, e in windows if s <= e]
    return windows


def label_real_points(df: pd.DataFrame, fault_windows) -> pd.DataFrame:
    df = df.copy()
    df["label"] = 0

    for s, e in fault_windows:
        df.loc[(df["time"] >= s) & (df["time"] <= e), "label"] = 1

    return df


# =========================
# 4. 合成异常：用于训练 CNN
# =========================

def inject_synthetic_anomaly(raw_window: np.ndarray, center: int) -> np.ndarray:
    """
    在窗口中心附近注入一个合成异常。
    论文思路：随机选择点，根据局部均值、窗口均值、方差和随机数替换异常值。
    这里做工程化简化，让异常更贴近 CPU Stress/尖峰：
    - spike：单点尖峰
    - drop：单点下降
    - level_shift：中心附近一小段抬升
    """
    x = raw_window.astype(float).copy()
    n = len(x)

    left = max(0, center - 10)
    right = min(n, center + 11)
    local = x[left:right]

    local_mean = float(np.mean(local))
    local_std = float(np.std(local))
    global_mean = float(np.mean(x))
    global_std = float(np.std(x))

    # 防止正常 CPU 太平稳时幅度太小
    base_scale = max(local_std, global_std, abs(global_mean) * 0.3, 0.01)

    anomaly_type = random.choice(["spike", "drop", "level_shift"])

    if anomaly_type == "spike":
        magnitude = random.uniform(4.0, 10.0) * base_scale
        x[center] = max(0.0, x[center] + magnitude)

    elif anomaly_type == "drop":
        magnitude = random.uniform(2.0, 6.0) * base_scale
        x[center] = max(0.0, x[center] - magnitude)

    else:
        shift_len = random.randint(3, 8)
        start = max(0, center - shift_len // 2)
        end = min(n, start + shift_len)
        magnitude = random.uniform(3.0, 8.0) * base_scale
        x[start:end] = np.maximum(0.0, x[start:end] + magnitude)

    return x


def make_one_sample(raw_window: np.ndarray, label: int) -> np.ndarray:
    saliency = spectral_residual_transform(raw_window, q=Q)
    return normalize_window(saliency).astype(np.float32)


def build_synthetic_dataset(values: np.ndarray):
    """
    用真实正常数据作为底座，人工注入异常，生成训练/验证数据。
    """
    half = WINDOW_SIZE // 2
    valid_centers = list(range(half, len(values) - half))

    if len(valid_centers) < 10:
        raise ValueError(
            f"数据点太少，无法生成 WINDOW_SIZE={WINDOW_SIZE} 的窗口。"
            f"当前点数={len(values)}，建议至少采集 200 个以上点。"
        )

    X = []
    y = []

    for _ in range(N_SYNTHETIC_NORMAL):
        c = random.choice(valid_centers)
        raw = values[c - half:c + half].copy()
        X.append(make_one_sample(raw, 0))
        y.append(0)

    for _ in range(N_SYNTHETIC_ANOMALY):
        c = random.choice(valid_centers)
        raw = values[c - half:c + half].copy()
        raw_anom = inject_synthetic_anomaly(raw, center=half)
        X.append(make_one_sample(raw_anom, 1))
        y.append(1)

    X = np.stack(X).astype(np.float32)
    y = np.array(y, dtype=np.float32)

    indices = np.arange(len(y))
    np.random.shuffle(indices)
    return X[indices], y[indices]


# =========================
# 5. 真实故障数据窗口：用于测试
# =========================

def build_real_windows(df: pd.DataFrame):
    half = WINDOW_SIZE // 2
    values = df["value"].to_numpy(dtype=float)
    labels = df["label"].to_numpy(dtype=int)
    times = df["time"].astype(str).to_numpy()

    X = []
    y = []
    sample_times = []
    sample_values = []

    for c in range(half, len(values) - half):
        raw = values[c - half:c + half].copy()
        X.append(make_one_sample(raw, int(labels[c])))
        y.append(int(labels[c]))
        sample_times.append(times[c])
        sample_values.append(values[c])

    if len(X) == 0:
        raise ValueError("真实数据窗口为空，请确认 CSV 数据点数是否大于 WINDOW_SIZE。")

    return (
        np.stack(X).astype(np.float32),
        np.array(y, dtype=np.float32),
        np.array(sample_times),
        np.array(sample_values, dtype=np.float32),
    )


def split_train_val(X, y, train_ratio=0.8):
    n = len(y)
    cut = int(n * train_ratio)
    return X[:cut], y[:cut], X[cut:], y[cut:]


def main():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_prometheus_csv(CSV_PATH)
    fault_windows = load_fault_windows(FAULT_WINDOWS_PATH)

    # 先按故障窗口前后筛选，再打标签
    df = filter_df_around_fault_windows(df, fault_windows)

    df_labeled = label_real_points(df, fault_windows)
    # 用正常点作为合成训练底座；如果正常点太少，则用全部数据作为底座。
    normal_values = df_labeled.loc[df_labeled["label"] == 0, "value"].to_numpy(dtype=float)
    if len(normal_values) < WINDOW_SIZE * 2:
        print("警告：正常点太少，合成训练集将使用全部数据作为底座。")
        normal_values = df_labeled["value"].to_numpy(dtype=float)

    X_syn, y_syn = build_synthetic_dataset(normal_values)
    X_train, y_train, X_val, y_val = split_train_val(X_syn, y_syn, TRAIN_RATIO)

    X_real, y_real, real_times, real_values = build_real_windows(df_labeled)

    # 将真实数据全部作为 test。这样可以直接看 CNN 对真实 ChaosMesh 故障区间的输出。
    dataset_path = OUT_DIR / "sr_cnn_dataset.npz"
    np.savez_compressed(
        dataset_path,
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        X_test=X_real,
        y_test=y_real,
        test_times=real_times,
        test_values=real_values,
    )

    meta = {
        "csv_path": str(CSV_PATH),
        "fault_windows_path": str(FAULT_WINDOWS_PATH),
        "out_dir": str(OUT_DIR),
        "window_size": WINDOW_SIZE,
        "q": Q,
        "n_train": int(len(y_train)),
        "n_val": int(len(y_val)),
        "n_test": int(len(y_real)),
        "n_test_anomaly": int(np.sum(y_real)),
        "fault_windows": [(str(s), str(e)) for s, e in fault_windows],
        "note": "train/val are synthetic anomalies based on normal Prometheus data; test is real Prometheus data labeled by fault_windows.csv."
    }

    with open(OUT_DIR / "dataset_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 保存真实测试窗口的时间标签，便于检查
    test_meta = pd.DataFrame({
        "time": real_times,
        "value": real_values,
        "label": y_real.astype(int),
    })
    test_meta.to_csv(OUT_DIR / "real_test_windows.csv", index=False, encoding="utf-8-sig")

    print("SR-CNN 数据集生成完成。")
    print(f"数据集文件：{dataset_path}")
    print(f"训练集：{X_train.shape}, 异常比例={float(np.mean(y_train)):.3f}")
    print(f"验证集：{X_val.shape}, 异常比例={float(np.mean(y_val)):.3f}")
    print(f"真实测试集：{X_real.shape}, 故障点数={int(np.sum(y_real))}")
    print(f"故障窗口数量：{len(fault_windows)}")
    print(f"元信息：{OUT_DIR / 'dataset_meta.json'}")


if __name__ == "__main__":
    main()
