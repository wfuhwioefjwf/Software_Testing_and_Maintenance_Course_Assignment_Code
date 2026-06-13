
"""
train_sr_cnn.py

作用：
1. 读取 make_sr_cnn_dataset.py 生成的 sr_cnn_dataset.npz。
2. 训练简化版 SR-CNN：
   - 输入：SR saliency window，形状 [batch, 1, window_size]
   - 模型：两层 1D Conv + 两层全连接 + Sigmoid 输出
3. 在真实 ChaosMesh 故障数据上预测异常概率。
4. 输出：
   - 模型权重 sr_cnn_model.pt
   - 训练曲线
   - 真实测试集预测结果 CSV
   - 真实 CPU 曲线 + CNN 异常概率图
   - 点级评估和论文风格片段级调整评估

说明：
这是课程实验规模下的 SR-CNN 简化复现。
保持论文中“SR saliency map + CNN 判别器”的核心思路，
但模型规模和训练数据规模都远小于论文工业环境。
"""

import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader


# =========================
# 1. 用户配置区
# =========================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

DATASET_PATH = PROJECT_DIR / "sr-cnn-dataset" / "sr_cnn_dataset.npz"
OUT_DIR = PROJECT_DIR / "sr-cnn-output"

BATCH_SIZE = 64
EPOCHS = 40
LEARNING_RATE = 1e-3
THRESHOLD = 0.5

# 论文风格片段调整允许延迟点数。
# 你的采样间隔是 15s，则 12 个点约 3 分钟。
DELAY_POINTS = 12

RANDOM_SEED = 42


# =========================
# 2. 模型定义
# =========================

class SRCNN(nn.Module):
    """
    简化版 SR-CNN：
    两层 1D 卷积 + 两层全连接 + Sigmoid。
    """
    def __init__(self, window_size: int):
        super().__init__()

        self.features = nn.Sequential(
            nn.Conv1d(1, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )

        self.classifier = nn.Sequential(
            nn.Linear(32 * window_size, 64),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(64, 1)
        )

    def forward(self, x):
        z = self.features(x)
        logits = self.classifier(z)
        return logits.squeeze(1)


# =========================
# 3. 评估函数
# =========================

def binary_metrics(y_true, y_pred):
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
    acc = (tp + tn) / max(1, len(y_true))

    return {
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "Accuracy": acc,
        "Precision": precision,
        "Recall": recall,
        "F1": f1,
    }


def adjust_prediction_by_segments(y_true, y_pred, delay_points=12):
    """
    论文风格的异常片段调整：
    如果某个真实异常片段在开始后的 delay_points 个点内被检测到，
    则认为整个片段被成功检测到，把该片段预测整体调为 1。
    """
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    adjusted = y_pred.copy()

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
                adjusted[start:end + 1] = 1
        else:
            i += 1

    return adjusted


def count_detected_segments(y_true, y_pred):
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    total = 0
    detected = 0
    n = len(y_true)

    i = 0
    while i < n:
        if y_true[i] == 1:
            total += 1
            start = i
            while i < n and y_true[i] == 1:
                i += 1
            end = i - 1

            if np.any(y_pred[start:end + 1] == 1):
                detected += 1
        else:
            i += 1

    return total, detected


# =========================
# 4. 训练与预测
# =========================

def make_loader(X, y, batch_size, shuffle):
    X_tensor = torch.tensor(X, dtype=torch.float32).unsqueeze(1)
    y_tensor = torch.tensor(y, dtype=torch.float32)
    ds = TensorDataset(X_tensor, y_tensor)
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle)


def run_epoch(model, loader, criterion, optimizer=None, device="cpu"):
    is_train = optimizer is not None
    model.train(is_train)

    total_loss = 0.0
    all_probs = []
    all_labels = []

    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)

        if is_train:
            optimizer.zero_grad()

        logits = model(xb)
        loss = criterion(logits, yb)

        if is_train:
            loss.backward()
            optimizer.step()

        total_loss += float(loss.item()) * len(yb)

        probs = torch.sigmoid(logits).detach().cpu().numpy()
        all_probs.append(probs)
        all_labels.append(yb.detach().cpu().numpy())

    all_probs = np.concatenate(all_probs)
    all_labels = np.concatenate(all_labels)

    avg_loss = total_loss / len(all_labels)
    preds = (all_probs >= THRESHOLD).astype(int)
    metrics = binary_metrics(all_labels, preds)
    metrics["loss"] = avg_loss
    return metrics


def predict(model, X, device="cpu"):
    model.eval()
    loader = make_loader(X, np.zeros(len(X)), batch_size=BATCH_SIZE, shuffle=False)

    probs = []
    with torch.no_grad():
        for xb, _ in loader:
            xb = xb.to(device)
            logits = model(xb)
            p = torch.sigmoid(logits).cpu().numpy()
            probs.append(p)

    return np.concatenate(probs)


def plot_training_history(history, out_dir: Path):
    hist = pd.DataFrame(history)
    hist.to_csv(out_dir / "training_history.csv", index=False, encoding="utf-8-sig")

    plt.figure(figsize=(10, 5))
    plt.plot(hist["epoch"], hist["train_loss"], label="train loss")
    plt.plot(hist["epoch"], hist["val_loss"], label="val loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("SR-CNN Training Loss")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "01_training_loss.png", dpi=200)
    plt.close()

    plt.figure(figsize=(10, 5))
    plt.plot(hist["epoch"], hist["train_f1"], label="train F1")
    plt.plot(hist["epoch"], hist["val_f1"], label="val F1")
    plt.xlabel("Epoch")
    plt.ylabel("F1")
    plt.title("SR-CNN Training F1")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "02_training_f1.png", dpi=200)
    plt.close()


def plot_real_test_results(result_df: pd.DataFrame, out_dir: Path):
    result_df["time"] = pd.to_datetime(result_df["time"], errors="coerce")

    plt.figure(figsize=(14, 5))
    plt.plot(result_df["time"], result_df["value"], label="frontend CPU", linewidth=1.5)

    fault_df = result_df[result_df["label"] == 1]
    if len(fault_df) > 0:
        plt.axvspan(fault_df["time"].min(), fault_df["time"].max(), alpha=0.2, label="fault injection period")

    pred_df = result_df[result_df["pred"] == 1]
    if len(pred_df) > 0:
        plt.scatter(pred_df["time"], pred_df["value"], s=45, label="SR-CNN detected anomaly")

    plt.xlabel("Time")
    plt.ylabel("CPU usage")
    plt.title("Frontend Pod CPU with SR-CNN Detection")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "03_real_cpu_with_srcnn_anomalies.png", dpi=200)
    plt.close()

    plt.figure(figsize=(14, 5))
    plt.plot(result_df["time"], result_df["prob"], label="SR-CNN anomaly probability", linewidth=1.5)
    plt.axhline(THRESHOLD, linestyle="--", label=f"threshold={THRESHOLD}")

    if len(fault_df) > 0:
        plt.axvspan(fault_df["time"].min(), fault_df["time"].max(), alpha=0.2, label="fault injection period")

    plt.xlabel("Time")
    plt.ylabel("Anomaly probability")
    plt.title("SR-CNN Anomaly Probability on Real ChaosMesh Data")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_dir / "04_real_srcnn_probability.png", dpi=200)
    plt.close()


def main():
    torch.manual_seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"找不到数据集：{DATASET_PATH}，请先运行 make_sr_cnn_dataset.py")

    data = np.load(DATASET_PATH, allow_pickle=True)
    X_train = data["X_train"]
    y_train = data["y_train"]
    X_val = data["X_val"]
    y_val = data["y_val"]
    X_test = data["X_test"]
    y_test = data["y_test"]
    test_times = data["test_times"]
    test_values = data["test_values"]

    window_size = X_train.shape[1]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"使用设备：{device}")
    print(f"训练集：{X_train.shape}, 验证集：{X_val.shape}, 真实测试集：{X_test.shape}")

    train_loader = make_loader(X_train, y_train, BATCH_SIZE, shuffle=True)
    val_loader = make_loader(X_val, y_val, BATCH_SIZE, shuffle=False)

    model = SRCNN(window_size=window_size).to(device)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    history = []
    best_val_f1 = -1.0
    best_path = OUT_DIR / "sr_cnn_model.pt"

    for epoch in range(1, EPOCHS + 1):
        train_metrics = run_epoch(model, train_loader, criterion, optimizer, device)
        val_metrics = run_epoch(model, val_loader, criterion, None, device)

        row = {
            "epoch": epoch,
            "train_loss": train_metrics["loss"],
            "val_loss": val_metrics["loss"],
            "train_f1": train_metrics["F1"],
            "val_f1": val_metrics["F1"],
            "train_precision": train_metrics["Precision"],
            "train_recall": train_metrics["Recall"],
            "val_precision": val_metrics["Precision"],
            "val_recall": val_metrics["Recall"],
        }
        history.append(row)

        print(
            f"Epoch {epoch:03d} | "
            f"train loss={row['train_loss']:.4f}, f1={row['train_f1']:.4f} | "
            f"val loss={row['val_loss']:.4f}, f1={row['val_f1']:.4f}"
        )

        if val_metrics["F1"] > best_val_f1:
            best_val_f1 = val_metrics["F1"]
            torch.save(model.state_dict(), best_path)

    plot_training_history(history, OUT_DIR)

    # 加载验证集上最优模型
    model.load_state_dict(torch.load(best_path, map_location=device))

    probs = predict(model, X_test, device=device)
    preds = (probs >= THRESHOLD).astype(int)

    raw_metrics = binary_metrics(y_test, preds)
    adjusted_preds = adjust_prediction_by_segments(y_test, preds, delay_points=DELAY_POINTS)
    adjusted_metrics = binary_metrics(y_test, adjusted_preds)

    total_segments, detected_segments = count_detected_segments(y_test, preds)

    result_df = pd.DataFrame({
        "time": test_times,
        "value": test_values,
        "label": y_test.astype(int),
        "prob": probs,
        "pred": preds.astype(int),
        "pred_adjusted": adjusted_preds.astype(int),
    })
    result_df.to_csv(OUT_DIR / "real_test_predictions.csv", index=False, encoding="utf-8-sig")

    plot_real_test_results(result_df, OUT_DIR)

    summary = {
        "threshold": THRESHOLD,
        "delay_points": DELAY_POINTS,
        "best_val_f1": best_val_f1,
        "raw_point_metrics": raw_metrics,
        "paper_style_adjusted_metrics": adjusted_metrics,
        "total_fault_segments": total_segments,
        "detected_fault_segments": detected_segments,
        "model_path": str(best_path),
    }

    with open(OUT_DIR / "evaluation_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n真实测试集点级评估：")
    for k, v in raw_metrics.items():
        print(f"{k}: {v}")

    print("\n论文风格片段调整后评估：")
    for k, v in adjusted_metrics.items():
        print(f"{k}: {v}")

    print(f"\n故障片段检测：{detected_segments}/{total_segments}")
    print(f"模型已保存：{best_path}")
    print(f"预测结果：{OUT_DIR / 'real_test_predictions.csv'}")
    print(f"评估摘要：{OUT_DIR / 'evaluation_summary.json'}")
    print(f"图片输出目录：{OUT_DIR}")


if __name__ == "__main__":
    main()
