# SRCNN and InterFusion Reproduction on Online Boutique

本目录为《软件测试与维护》课程大作业中“论文算法复现”部分的代码与数据整理，主要围绕 **Online Boutique 微服务系统** 的运行监控数据，复现并验证两类时间序列异常检测方法：

1. **SR-CNN / SRCNN**：基于 Spectral Residual 与 CNN 的单变量时间序列异常检测方法；
2. **InterFusion**：KDD 2021 提出的多变量时间序列异常检测与解释方法。

本项目不是直接使用论文原始公开数据集，而是将算法迁移到课程实验中部署的 Online Boutique 微服务系统上。实验过程中通过 Prometheus 采集容器与 Pod 指标，并结合 ChaosMesh 对微服务系统进行故障注入，从而构造训练数据、测试数据和异常标签，用于验证算法在微服务监控场景下的可行性。

## 1. 项目背景

Online Boutique 是一个典型的云原生微服务示例系统，由多个服务共同组成，包括 `frontend`、`cartservice`、`checkoutservice`、`productcatalogservice`、`paymentservice`、`recommendationservice`、`redis-cart` 等。课程实验中将其部署在本地 Kubernetes / Minikube 环境中，并额外接入 Prometheus、Grafana 与 ChaosMesh。

整体实验流程如下：

1. 部署 Online Boutique 微服务系统；
2. 部署 Prometheus 与 Grafana，采集 Pod、容器、节点等运行指标；
3. 使用 ChaosMesh 对目标服务进行故障注入，例如 Pod Kill、网络延迟、CPU Stress 等；
4. 使用脚本从 Prometheus 中导出指定时间范围内的监控数据；
5. 将监控数据整理为 SR-CNN 和 InterFusion 可使用的输入格式；
6. 训练或运行异常检测模型；
7. 根据真实故障注入时间窗口进行结果分析。

本目录中保留了一部分 Online Boutique 原始部署文件，同时新增了算法复现所需的数据处理脚本、模型训练脚本、实验数据与结果文件。

## 2. 目录结构说明

```text
SRCNN_and_InterFusion-Online_Boutique/
├── InterFusion/
│   ├── algorithm/                    # InterFusion 原始算法代码
│   ├── data/                         # InterFusion 原始数据组织目录
│   ├── explib/                       # 原项目实验辅助代码
│   ├── online_boutique_data/         # 本次实验中整理的 Online Boutique 数据与结果
│   ├── online_boutique_tools/        # 面向 Online Boutique 的数据导出与转换脚本
│   ├── results/                      # InterFusion 训练与预测结果
│   ├── requirements.txt              # 原始环境依赖
│   └── requirements_win_cpu.txt      # Windows / CPU 环境下整理的依赖
│
├── python/
│   ├── make_sr_cnn_dataset.py         # 构造 SR-CNN 数据集
│   ├── train_sr_cnn.py                # 训练简化版 SR-CNN 并评估
│   ├── sr_decetion.py                 # SR 方法的单独检测与可视化脚本
│   └── backup_online_boutique_experiment.py
│
├── sr-cnn-dataset/
│   ├── dataset_meta.json              # SR-CNN 数据集元信息
│   ├── real_test_windows.csv          # 真实测试窗口信息
│   └── sr_cnn_dataset.npz             # SR-CNN 训练、验证、测试数据
│
├── sr-cnn-output/
│   ├── 01_training_loss.png           # SR-CNN 训练损失曲线
│   ├── 02_training_f1.png             # SR-CNN 训练 F1 曲线
│   ├── 03_real_cpu_with_srcnn_anomalies.png
│   ├── 04_real_srcnn_probability.png
│   ├── evaluation_summary.json        # SR-CNN 最终评估结果
│   ├── real_test_predictions.csv      # 真实测试集预测结果
│   ├── sr_cnn_model.pt                # 训练得到的模型权重
│   └── training_history.csv           # 每轮训练记录
│
├── prometheus-data/                   # 指定故障时间段导出的 Prometheus 数据
├── prometheus-container-data/         # 容器级指标导出数据
├── prometheus-online-boutique-pod-data/
│                                      # Online Boutique Pod 级指标导出数据
├── chaos-yamls/                       # ChaosMesh 故障注入配置与故障窗口记录
├── manifests-monitoring/              # 监控相关部署文件
├── kubernetes-manifests/              # Online Boutique Kubernetes 部署文件
├── export-prometheus-data.ps1         # 导出指定故障时间段 Prometheus 数据
├── export-online-boutique-pod-metrics.ps1
│                                      # 导出 Online Boutique Pod 级指标
└── export-container-metrics.ps1       # 导出容器级指标
```

## 3. 数据采集与故障注入

本项目的数据来源于部署后的 Online Boutique 微服务系统。实验中主要关注微服务运行过程中的 CPU、内存、网络收发、Pod Ready 状态、Pod 重启次数等指标。

Prometheus 数据导出脚本主要包括：

```text
export-prometheus-data.ps1
export-online-boutique-pod-metrics.ps1
export-container-metrics.ps1
```

其中，`export-online-boutique-pod-metrics.ps1` 用于导出 Online Boutique 命名空间下 Pod 级别的 CPU、内存、网络收发、Ready 状态和重启次数；`export-container-metrics.ps1` 同时考虑了新旧标签格式，避免不同 Prometheus / cAdvisor 版本下标签名不一致导致查询为空；`export-prometheus-data.ps1` 则用于导出某一轮指定故障时间段的数据。

实验中通过 ChaosMesh 对微服务进行故障注入。由于异常检测模型需要明确的标签，因此故障注入脚本会记录故障开始与结束时间，并生成类似 `fault_windows.csv` 的故障窗口文件。后续 SR-CNN 和 InterFusion 的数据预处理都会根据这些时间窗口为测试数据打上异常标签。

## 4. SR-CNN 复现部分

### 4.1 方法简介

SR-CNN 是一种面向时间序列异常检测的方法。其核心思想可以概括为：

1. 对原始时间序列进行频域分析；
2. 通过 Spectral Residual 方法突出时间序列中的突变、尖峰和局部异常；
3. 将得到的 saliency map 切分为固定长度窗口；
4. 使用 CNN 对窗口进行二分类，判断窗口中心点是否处于异常状态。

在原论文中，SR-CNN 面向的是大规模工业监控时间序列。本项目中，为了适应课程实验规模和本地 Online Boutique 数据量有限的问题，采用了工程化简化复现方式：保留 “Spectral Residual saliency map + CNN 判别器” 的核心流程，但模型规模、训练样本规模和特征复杂度均小于工业级实现。

### 4.2 数据构造

SR-CNN 数据集由 `python/make_sr_cnn_dataset.py` 生成。该脚本主要完成以下工作：

1. 读取 Prometheus 导出的 `frontend` Pod CPU 指标；
2. 读取 ChaosMesh 故障注入产生的 `fault_windows.csv`；
3. 根据正常 CPU 曲线合成异常样本，构造训练集和验证集；
4. 根据真实故障时间窗口为真实监控数据打标签，构造测试集；
5. 对时间序列计算 Spectral Residual saliency map；
6. 将 saliency 序列切分为固定长度窗口；
7. 保存为 `sr-cnn-dataset/sr_cnn_dataset.npz`。

本项目中窗口标签的定义方式为：如果窗口中心点处于故障注入时间窗口内，则该窗口标签为异常；否则为正常。

### 4.3 模型训练与预测

SR-CNN 模型由 `python/train_sr_cnn.py` 训练。该脚本读取 `sr_cnn_dataset.npz` 后，训练一个简化版 1D CNN 模型。模型结构为：

```text
输入：SR saliency window
形状：[batch, 1, window_size]

模型：
Conv1d → ReLU → Conv1d → ReLU → Flatten
→ Linear → ReLU → Dropout → Linear

输出：
异常概率
```

训练完成后，脚本会输出：

```text
sr-cnn-output/sr_cnn_model.pt
sr-cnn-output/training_history.csv
sr-cnn-output/01_training_loss.png
sr-cnn-output/02_training_f1.png
sr-cnn-output/real_test_predictions.csv
sr-cnn-output/03_real_cpu_with_srcnn_anomalies.png
sr-cnn-output/04_real_srcnn_probability.png
sr-cnn-output/evaluation_summary.json
```

其中，`03_real_cpu_with_srcnn_anomalies.png` 用于将真实 CPU 曲线、故障窗口和模型检测出的异常点进行对比；`04_real_srcnn_probability.png` 用于观察模型在真实测试集上的异常概率变化。

### 4.4 运行方式

在项目根目录下运行：

```powershell
cd .\Session_4-Paper_Reproduction\SRCNN_and_InterFusion-Online_Boutique

python .\python\make_sr_cnn_dataset.py
python .\python\train_sr_cnn.py
```

如果重新采集了 Prometheus 数据，需要先确认以下文件是否存在：

```text
prometheus-online-boutique-pod-data/01_frontend_pod_cpu.csv
chaos-yamls/fault_windows.csv
```

如果 `fault_windows.csv` 不存在，可以在 `make_sr_cnn_dataset.py` 中手动填写故障窗口，或重新运行故障注入记录脚本。

### 4.5 实验结果说明

本次 SR-CNN 训练过程中，训练损失整体下降，训练 F1 和验证 F1 均逐步提升，说明模型能够从合成异常样本中学习到一定的异常模式。最终验证集 F1 达到较高水平，表明模型在训练数据分布内具有较好的分类能力。

在真实 Online Boutique 故障测试数据上，模型的点级检测效果弱于验证集。这是符合实验预期的，因为训练集中的异常主要由正常数据合成得到，而真实故障注入对 CPU 曲线的影响可能存在延迟、波动不明显、局部变化不连续等问题。因此，点级评估中会出现一部分漏检和误报。

本项目同时采用了论文中常见的异常片段级评估思路：只要模型在真实异常片段开始后一定延迟范围内检测到异常，就认为该异常片段被成功捕捉。使用这种评估方式后，模型能够更好地反映微服务故障检测场景中的实际需求。对于运维监控而言，模型不一定需要精确定位每一个异常点，但需要尽早发现一次故障事件。

本次实验中，SR-CNN 在真实故障片段上的检测效果明显优于纯点级评估，说明 SR-CNN 对微服务运行指标中的突变和异常波动具有一定捕捉能力。但是，由于本实验数据量较小、训练异常主要依赖合成、监控指标只选取了少量核心指标，因此模型仍存在泛化能力不足的问题。

## 5. InterFusion 复现部分

### 5.1 方法简介

InterFusion 是 KDD 2021 论文提出的多变量时间序列异常检测与解释方法。该方法面向多维监控指标，核心思想是使用层次化变分自编码器建模多变量时间序列中的正常模式，并通过层次化随机隐变量分别学习指标间关系和时间依赖关系。

与 SR-CNN 相比，InterFusion 更适合处理多指标联合异常检测问题。例如，在微服务系统中，CPU、内存、网络收发、Pod Ready 状态、重启次数等指标之间往往存在关联。某一次故障不一定只表现为单一指标突变，而可能体现为多个指标之间关系发生变化。InterFusion 正是希望从多变量时间序列中学习这种正常依赖结构，并在依赖结构被破坏时识别异常。

### 5.2 数据适配

原始 InterFusion 项目主要支持论文中的公开数据集，例如 SMD、SWaT、WADI 等。本项目为了将其迁移到 Online Boutique 微服务系统上，新增了 `InterFusion/online_boutique_tools/` 目录，用于导出、整理和转换 Online Boutique 的 Prometheus 监控数据。

其中，`make_interfusion_dataset.py` 主要完成以下工作：

1. 读取训练 CSV 和测试 CSV；
2. 按时间戳排序并去重；
3. 去除 `unix_time`、`time_utc`、`time_local`、`label` 等非特征列；
4. 将剩余指标列作为多变量时间序列特征；
5. 生成 InterFusion 需要的 `.pkl` 文件：

   * `online_boutique_train.pkl`
   * `online_boutique_test.pkl`
   * `online_boutique_test_label.pkl`
6. 保存特征列名和数据集元信息，便于结果解释和复现实验。

数据转换后的文件会放入 InterFusion 的 `data/processed` 目录或指定输出目录中，供 `stack_train.py` 和 `stack_predict.py` 使用。

### 5.3 运行方式

进入 InterFusion 目录：

```powershell
cd .\Session_4-Paper_Reproduction\SRCNN_and_InterFusion-Online_Boutique\InterFusion
```

安装依赖：

```powershell
pip install -r requirements_win_cpu.txt
```

如果在 Linux 或原始论文环境中复现，也可以参考：

```powershell
pip install -r requirements.txt
```

生成 Online Boutique 数据集：

```powershell
python .\online_boutique_tools\make_interfusion_dataset.py `
  --train_csv .\online_boutique_data\prom_train_20260612_053834\train.csv `
  --test_csv .\online_boutique_data\prom_test_from_kill_20260612_173018\test.csv `
  --out_dir .\data\processed `
  --dataset_name online_boutique
```

实际运行时，`train_csv` 和 `test_csv` 需要根据当前保留的数据目录调整。由于不同实验批次的时间戳不同，README 中不写死所有具体批次路径，避免复现时误用旧路径。

训练 InterFusion：

```powershell
python .\algorithm\stack_train.py --dataset=online_boutique
```

预测与评估：

```powershell
python .\algorithm\stack_predict.py --load_model_dir=.\results\stack_train\
```

如果运行时遇到数据维度不匹配，需要检查：

1. `algorithm/utils.py` 中是否已经添加 `online_boutique` 数据集维度；
2. 训练集和测试集是否使用完全一致的特征列；
3. 测试集是否包含 `label` 列；
4. 是否存在空值、无穷值或非数值列；
5. `.pkl` 文件是否被保存到了 InterFusion 实际读取的目录。

### 5.4 实验结果说明

InterFusion 的优势在于多变量建模。相比只使用 `frontend` CPU 的 SR-CNN，InterFusion 可以同时利用 CPU、内存、网络、Ready 状态、重启次数等多种指标，理论上更适合复杂微服务故障场景。

但是，在本课程实验规模下，InterFusion 的训练效果受到以下因素影响：

1. 数据量较小
   InterFusion 需要足够多的正常多变量时间序列来学习稳定的正常模式。如果训练数据时间较短，模型可能只能记住局部波动，难以学习微服务系统长期稳定运行规律。

2. 指标维度和数据质量有限
   Prometheus 导出的指标存在标签格式差异、部分查询为空、不同 Pod 指标对齐困难等问题。即使完成数据转换，特征之间也可能存在缺失、稀疏或噪声较高的情况。

3. 故障影响不一定显著
   Pod Kill 或网络延迟并不一定会在所有指标上同时产生明显异常。有些故障会被 Kubernetes 自动恢复机制快速掩盖，导致异常窗口内的监控曲线变化不够强烈。

4. 原算法环境较旧
   InterFusion 原始代码面向较旧的 Python、TensorFlow / 依赖环境。在 Windows CPU 环境下复现时，需要处理依赖兼容、路径、数据集注册、训练参数等问题。

因此，本项目中的 InterFusion 复现重点并不是完全达到原论文指标，而是验证其能否在 Online Boutique 微服务监控数据上完成数据接入、训练、预测和结果分析流程。最终结果保存在 `InterFusion/results/` 和 `InterFusion/online_boutique_data/result_final.txt` 中。

## 6. SR-CNN 与 InterFusion 对比

| 对比项      | SR-CNN                  | InterFusion            |
| -------- | ----------------------- | ---------------------- |
| 输入类型     | 单变量时间序列为主               | 多变量时间序列                |
| 本项目主要输入  | `frontend` Pod CPU      | CPU、内存、网络、Ready、重启等多指标 |
| 核心思想     | Spectral Residual + CNN | 层次化 VAE 建模指标间与时间依赖     |
| 数据需求     | 相对较低，可用合成异常训练           | 较高，需要较稳定的正常多变量数据       |
| 工程复现难度   | 较低                      | 较高                     |
| 对课程实验适配性 | 更容易快速得到可视化结果            | 更贴近微服务多指标异常检测场景        |
| 主要问题     | 真实故障泛化能力受合成数据影响         | 小数据量和环境兼容问题影响训练效果      |

总体来看，SR-CNN 更适合在课程实验中快速验证“监控指标异常检测”的基本流程；InterFusion 更适合体现论文复现的复杂性和多变量微服务监控场景的研究价值。

## 7. 已保留的实验输出

SR-CNN 输出文件位于：

```text
sr-cnn-output/
```

主要包括：

```text
01_training_loss.png
02_training_f1.png
03_real_cpu_with_srcnn_anomalies.png
04_real_srcnn_probability.png
evaluation_summary.json
real_test_predictions.csv
sr_cnn_model.pt
training_history.csv
```

InterFusion 输出文件位于：

```text
InterFusion/results/
InterFusion/online_boutique_data/
```

主要包括：

```text
stack_predict/
stack_predict_*/
result_final.txt
```

这些文件用于支撑实验报告中的结果分析，包括训练过程、异常检测效果、模型误报漏报原因和后续优化建议。

## 8. 复现实验注意事项

1. Prometheus 地址需要根据本机端口修改
   PowerShell 导出脚本中的 `$PromUrl` 可能是某一次实验中的本地端口，例如 `http://127.0.0.1:61279`。重新运行时需要先通过 `minikube service` 或端口转发确认 Prometheus 当前地址。

2. 故障窗口必须与监控数据时间对齐
   如果 `fault_windows.csv` 中记录的是本地时间，而 Prometheus 导出的是 UTC 时间，需要统一时间格式，否则会导致标签错位。

3. Online Boutique 的负载生成器会影响指标
   `loadgenerator` 会持续访问前端服务，因此部分 CPU、网络或文件系统读写波动可能来自正常负载，而不一定是故障本身。

4. 不同 Prometheus 版本的标签可能不同
   有的环境使用 `namespace`、`pod`、`container`，有的环境使用 `kubernetes_namespace`、`kubernetes_pod_name`、`container_name`。因此导出脚本中保留了新旧标签两套查询方式。

5. InterFusion 需要确认数据维度
   如果新增或删除 Prometheus 指标，需要同步修改数据集注册信息，否则训练或预测阶段可能出现维度不匹配。

6. 本项目为课程实验复现
   由于实验环境、数据规模和故障注入方式均与论文工业环境不同，因此实验结果主要用于说明算法流程、工程适配过程和异常检测现象，不应直接与原论文完整指标进行严格对比。

## 9. 参考论文

### SR-CNN

Ren, H., Xu, B., Wang, Y., Yi, C., Huang, C., Kou, X., Xing, T., Yang, M., Tong, J., & Zhang, Q.
**Time-Series Anomaly Detection Service at Microsoft**.
KDD 2019.

### InterFusion

Li, Z., Zhao, Y., Han, J., Su, Y., Jiao, R., Wen, X., & Pei, D.
**Multivariate Time Series Anomaly Detection and Interpretation using Hierarchical Inter-Metric and Temporal Embedding**.
KDD 2021.
