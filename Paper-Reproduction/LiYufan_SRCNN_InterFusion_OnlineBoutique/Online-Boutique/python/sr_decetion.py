import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# =========================
# 1. 用户配置区
# =========================

CSV_PATH = r"E:\0AI\Online-Boutique\prometheus-online-boutique-pod-data\01_frontend_pod_cpu.csv"
OUT_DIR = r".\sr-output"

# 如果你的 CSV 是完整导出的，通常有 time_local、value 两列
TIME_COLUMN = "time_local"
VALUE_COLUMN = "value"

# 故障区间，用于画阴影和计算评估指标
# 请根据你的真实 full csv 时间修改。格式要和 time_local 基本一致。
# 如果暂时不想评估，可以都设为 None。
FAULT_START =  "2026-06-12 01:29:57"
FAULT_END =  "2026-06-12 01:43:57"

# 示例：
# FAULT_START = "2026-06-12 01:32:57"
# FAULT_END   = "2026-06-12 01:38:27"

# SR 参数
WINDOW_SIZE = 64
Q = 3
Z = 21
TAU = 3.0
KAPPA = 5
M = 5

# 如果数据点很少，前几个点不适合做 FFT，这里设置最小历史长度
MIN_HISTORY = 8


# =========================
# 2. SR 核心算法
# =========================

def moving_average_same(x: np.ndarray, window: int) -> np.ndarray:
    """
    对输入序列做简单移动平均。
    论文中的 AL(f) 可以理解为对 log amplitude spectrum 做平均滤波。
    """
    if window <= 1:
        return x.copy()

    kernel = np.ones(window, dtype=float) / window
    return np.convolve(x, kernel, mode="same")


def spectral_residual_transform(x: np.ndarray, q: int = 3) -> np.ndarray:
    """
    对一个窗口序列计算 Spectral Residual saliency map。

    论文步骤：
    A(f) = Amplitude(F(x))
    P(f) = Phase(F(x))
    L(f) = log(A(f))
    AL(f) = hq(f) * L(f)
    R(f) = L(f) - AL(f)
    S(x) = |F^{-1}(exp(R(f) + iP(f)))|
    """
    x = np.asarray(x, dtype=float)

    # 避免全 0 或非法值
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    fft_result = np.fft.fft(x)

    amplitude = np.abs(fft_result)
    phase = np.angle(fft_result)

    # 防止 log(0)
    log_amplitude = np.log(amplitude + 1e-8)

    avg_log_amplitude = moving_average_same(log_amplitude, q)

    spectral_residual = log_amplitude - avg_log_amplitude

    saliency_map = np.abs(
        np.fft.ifft(np.exp(spectral_residual + 1j * phase))
    )

    return saliency_map


def append_estimated_points(window_values: np.ndarray, m: int = 5, kappa: int = 5) -> np.ndarray:
    """
    论文中提到：SR 在目标点位于滑动窗口中部时效果更好。
    因此在线检测最新点 x_n 时，在序列尾部添加若干估计点。

    这里按照论文思路：
    1. 使用最近 m 个点估计平均斜率
    2. 得到 x_{n+1}
    3. 复制 x_{n+1} 共 kappa 次追加到尾部
    """
    x = np.asarray(window_values, dtype=float)

    if len(x) < m + 2:
        return x

    slopes = []
    for i in range(1, m + 1):
        slope = (x[-1] - x[-1 - i]) / i
        slopes.append(slope)

    avg_slope = np.mean(slopes)

    # 对应论文里的 x_{n+1} 估计思想
    next_point = x[-m] + avg_slope * m

    estimated_points = np.repeat(next_point, kappa)

    return np.concatenate([x, estimated_points])


def sr_detect_streaming(
    values: np.ndarray,
    window_size: int = 64,
    q: int = 3,
    z: int = 21,
    tau: float = 3.0,
    kappa: int = 5,
    m: int = 5,
    min_history: int = 8,
):
    """
    用滑动窗口模拟论文中的在线检测方式。
    对每一个当前点 x_n：
    1. 取最近 window_size 个点
    2. 在尾部添加 kappa 个估计点
    3. 计算 SR saliency map
    4. 取原当前点对应的 saliency 值
    5. 和前 z 个点的局部平均比较
    6. score > tau 判定为异常
    """
    values = np.asarray(values, dtype=float)
    n = len(values)

    saliency = np.full(n, np.nan)
    score = np.full(n, np.nan)
    is_anomaly = np.zeros(n, dtype=int)

    for t in range(n):
        start = max(0, t - window_size + 1)
        history = values[start:t + 1]

        if len(history) < min_history:
            continue

        actual_len = len(history)

        extended = append_estimated_points(history, m=min(m, max(1, len(history) - 2)), kappa=kappa)

        saliency_map = spectral_residual_transform(extended, q=q)

        # 当前真实点在 extended 中的位置
        current_index = actual_len - 1
        current_saliency = saliency_map[current_index]

        # 论文中使用当前点前 z 个 saliency 的局部平均
        local_start = max(0, current_index - z)
        local_values = saliency_map[local_start:current_index]

        if len(local_values) == 0:
            local_avg = np.mean(saliency_map[:current_index + 1])
        else:
            local_avg = np.mean(local_values)

        local_avg = max(local_avg, 1e-8)

        anomaly_score = (current_saliency - local_avg) / local_avg

        saliency[t] = current_saliency
        score[t] = anomaly_score

        if anomaly_score > tau:
            is_anomaly[t] = 1

    return saliency, score, is_anomaly


# =========================
# 3. 数据读取与清洗
# =========================

def load_prometheus_csv(path: str, time_column: str, value_column: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    if time_column not in df.columns:
        raise ValueError(f"找不到时间列：{time_column}，当前 CSV 列为：{list(df.columns)}")

    if value_column not in df.columns:
        raise ValueError(f"找不到数值列：{value_column}，当前 CSV 列为：{list(df.columns)}")

    df = df[[time_column, value_column]].copy()
    df.columns = ["time", "value"]

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df = df.dropna(subset=["time", "value"])
    df = df.sort_values("time").reset_index(drop=True)

    # 同一时间如果有重复，取平均
    df = df.groupby("time", as_index=False)["value"].mean()

    return df


# =========================
# 4. 评估函数，可选
# =========================

def add_fault_label(df: pd.DataFrame, fault_start, fault_end) -> pd.DataFrame:
    df = df.copy()
    df["label"] = 0

    if fault_start is None or fault_end is None:
        return df

    start = pd.to_datetime(fault_start)
    end = pd.to_datetime(fault_end)

    df.loc[(df["time"] >= start) & (df["time"] <= end), "label"] = 1
    return df


def evaluate_point_level(y_true: np.ndarray, y_pred: np.ndarray):
    """
    简单点级评估。
    注意：论文更强调异常片段级评估，但点级评估更容易实现和解释。
    """
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "Precision": precision,
        "Recall": recall,
        "F1": f1,
    }


def evaluate_segment_level(df: pd.DataFrame):
    """
    简化版区间评估：
    只要故障区间内检测到至少一个异常点，就认为本次故障被检测到。
    这个更适合你的 ChaosMesh 故障注入实验。
    """
    if "label" not in df.columns or df["label"].sum() == 0:
        return None

    fault_points = df[df["label"] == 1]
    detected_in_fault = int(fault_points["is_anomaly"].sum())

    return {
        "fault_segment_detected": detected_in_fault > 0,
        "detected_points_in_fault": detected_in_fault,
        "total_fault_points": int(len(fault_points)),
    }


# =========================
# 5. 绘图
# =========================

def plot_results(df: pd.DataFrame, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)

    # 图 1：原始曲线 + 异常点
    plt.figure(figsize=(14, 5))
    plt.plot(df["time"], df["value"], linewidth=1.5, label="frontend CPU")

    anomaly_df = df[df["is_anomaly"] == 1]
    plt.scatter(anomaly_df["time"], anomaly_df["value"], s=45, label="SR detected anomaly")

    if "label" in df.columns and df["label"].sum() > 0:
        fault_df = df[df["label"] == 1]
        plt.axvspan(fault_df["time"].min(), fault_df["time"].max(), alpha=0.2, label="fault injection period")

    plt.title("Frontend Pod CPU with SR Anomaly Detection")
    plt.xlabel("Time")
    plt.ylabel("CPU usage")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "01_raw_cpu_with_sr_anomalies.png"), dpi=200)
    plt.close()

    # 图 2：saliency map
    plt.figure(figsize=(14, 5))
    plt.plot(df["time"], df["saliency"], linewidth=1.5, label="SR saliency")

    if "label" in df.columns and df["label"].sum() > 0:
        fault_df = df[df["label"] == 1]
        plt.axvspan(fault_df["time"].min(), fault_df["time"].max(), alpha=0.2, label="fault injection period")

    plt.title("SR Saliency Map")
    plt.xlabel("Time")
    plt.ylabel("Saliency")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "02_sr_saliency.png"), dpi=200)
    plt.close()

    # 图 3：异常分数 + 阈值
    plt.figure(figsize=(14, 5))
    plt.plot(df["time"], df["score"], linewidth=1.5, label="SR anomaly score")
    plt.axhline(TAU, linestyle="--", label=f"threshold tau={TAU}")

    if "label" in df.columns and df["label"].sum() > 0:
        fault_df = df[df["label"] == 1]
        plt.axvspan(fault_df["time"].min(), fault_df["time"].max(), alpha=0.2, label="fault injection period")

    plt.title("SR Anomaly Score")
    plt.xlabel("Time")
    plt.ylabel("Score")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "03_sr_score.png"), dpi=200)
    plt.close()


def adjust_prediction_by_segments(y_true, y_pred, delay_points=12):
    """
    论文风格的异常片段调整评估。

    思路：
    如果某个连续故障片段内，算法在片段开始后的 delay_points 个点内检测到异常，
    则认为整个故障片段被成功检测到，并把该片段的预测结果整体调整为 1。

    delay_points:
    你的数据是 15 秒一个点。
    12 个点约等于 3 分钟。
    如果希望更宽松，可以设为 20 或 28。
    """
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    adjusted_pred = y_pred.copy()
    n = len(y_true)

    i = 0
    while i < n:
        if y_true[i] == 1:
            start = i
            while i < n and y_true[i] == 1:
                i += 1
            end = i - 1

            detect_end = min(end, start + delay_points)

            if np.any(y_pred[start:detect_end + 1] == 1):
                adjusted_pred[start:end + 1] = 1
        else:
            i += 1

    return adjusted_pred


def evaluate_with_paper_adjustment(df, delay_points=12):
    """
    使用论文风格的片段调整后，再计算 Precision / Recall / F1。
    """
    if "label" not in df.columns or df["label"].sum() == 0:
        return None

    y_true = df["label"].to_numpy().astype(int)
    y_pred = df["is_anomaly"].to_numpy().astype(int)

    adjusted_pred = adjust_prediction_by_segments(
        y_true,
        y_pred,
        delay_points=delay_points
    )

    metrics = evaluate_point_level(y_true, adjusted_pred)
    return metrics, adjusted_pred


# =========================
# 6. 主程序
# =========================

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    df = load_prometheus_csv(CSV_PATH, TIME_COLUMN, VALUE_COLUMN)

    values = df["value"].to_numpy()

    saliency, score, is_anomaly = sr_detect_streaming(
        values,
        window_size=WINDOW_SIZE,
        q=Q,
        z=Z,
        tau=TAU,
        kappa=KAPPA,
        m=M,
        min_history=MIN_HISTORY,
    )

    df["saliency"] = saliency
    df["score"] = score
    df["is_anomaly"] = is_anomaly

    df = add_fault_label(df, FAULT_START, FAULT_END)

    result_csv = os.path.join(OUT_DIR, "sr_detection_result.csv")
    df.to_csv(result_csv, index=False, encoding="utf-8-sig")

    plot_results(df, OUT_DIR)

    print("SR 检测完成。")
    print(f"输入数据点数：{len(df)}")
    print(f"检测到异常点数：{int(df['is_anomaly'].sum())}")
    print(f"结果 CSV：{result_csv}")
    print(f"图片输出目录：{OUT_DIR}")

    if df["label"].sum() > 0:
        point_metrics = evaluate_point_level(df["label"].to_numpy(), df["is_anomaly"].to_numpy())
        segment_metrics = evaluate_segment_level(df)
        adjusted_metrics, adjusted_pred = evaluate_with_paper_adjustment(df, delay_points=12)
        df["is_anomaly_adjusted"] = adjusted_pred

        adjusted_csv = os.path.join(OUT_DIR, "sr_detection_result_adjusted.csv")
        df.to_csv(adjusted_csv, index=False, encoding="utf-8-sig")

        print("\n论文风格片段调整后评估：")
        for k, v in adjusted_metrics.items():
            print(f"{k}: {v}")

        print(f"\n调整后结果 CSV：{adjusted_csv}")

        print("\n点级评估：")
        for k, v in point_metrics.items():
            print(f"{k}: {v}")

        print("\n区间级评估：")
        print(segment_metrics)


if __name__ == "__main__":
    main()
