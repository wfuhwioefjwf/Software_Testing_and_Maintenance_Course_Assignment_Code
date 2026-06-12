# Online Boutique Anomaly Detection and Root Cause Localization Reproduction

本仓库整理了基于 Online Boutique 微服务系统的异常检测与根因定位复现实验代码，主要包含两条论文复现链路：

- CATCH：面向多变量时序指标的异常检测。
- KPIRoot：基于监控指标的服务级根因定位。

仓库中仅保留代码、脚本和实验配置，不包含采集得到的原始数据、模型输出、图片、论文 PDF、PPT 或其他结果文件。

## Repository Structure

```text
.
├── CATCH/                 # CATCH 论文复现代码
├── KPIRoot/               # KPIRoot 论文复现代码与 Online Boutique 适配脚本
├── Online-Boutique/       # Online Boutique 微服务系统代码与部署配置
├── chaos/                 # ChaosMesh 故障注入配置
├── jmeter/                # JMeter 压测脚本
├── scripts/               # 数据采集、格式转换、结果汇总等辅助脚本
├── selenium/              # Selenium 业务访问脚本
├── package.json           # Node.js 辅助脚本依赖
├── package-lock.json
└── README.md
```

## Requirements

推荐在 Windows + PowerShell 环境下运行，实验环境依赖如下：

- Python 3.10 或兼容版本
- Conda 或 venv
- Docker Desktop
- Kubernetes 环境
- kubectl
- Helm
- ChaosMesh
- Prometheus
- Apache JMeter
- Node.js

Python 依赖可分别参考：

```powershell
pip install -r CATCH/requirements.txt
pip install -r KPIRoot/requirements.txt
```

Node.js 依赖：

```powershell
npm install
```

## Experiment Workflow

整体流程如下：

1. 部署 Online Boutique 微服务系统。
2. 使用 JMeter 或 Selenium 产生稳定业务流量。
3. 使用 ChaosMesh 注入 pod-kill、network-delay、CPU stress 等故障。
4. 从 Prometheus 导出服务级和 pod 级监控指标。
5. 将宽表监控数据转换为 CATCH 所需的长时序输入。
6. 将 Prometheus 指标转换为 KPIRoot 所需的服务级候选输入。
7. 分别运行 CATCH 和 KPIRoot，得到异常检测与根因候选排序结果。

## Useful Scripts

常用脚本位于 `scripts/`：

- `export_prometheus.py`：导出 Prometheus 指标。
- `export_prometheus_full_pods.py`：导出更完整的 pod 级指标。
- `build_wide_table.py`：构建统一宽表。
- `build_catch_input.py`：生成 CATCH 输入。
- `build_kpiroot_input.py`、`build_kpiroot_input_v2.py`：生成 KPIRoot 输入。
- `build_kpiroot_full_service_case.py`：构建服务级 KPIRoot 实验用例。
- `build_run_summary.py`：汇总单次实验信息。
- `plot_run_case_summary.py`：绘制实验摘要图。
- `run_kpiroot_formal_run005.ps1`：KPIRoot 正式实验流程脚本示例。

## CATCH Reproduction

CATCH 复现代码保存在 `CATCH/`。项目适配流程为：

1. 从 Prometheus 指标构建多变量时序宽表。
2. 转换为 CATCH 所需的长序列输入格式。
3. 使用 CATCH 的时域与频域重构误差进行异常检测。
4. 根据故障注入时间窗口计算检测效果。

运行前请根据本地数据路径修改相关脚本参数。

## KPIRoot Reproduction

KPIRoot 复现代码保存在 `KPIRoot/`。项目适配流程为：

1. 从 Prometheus 指标中提取服务或 pod 级 KPI。
2. 按异常窗口构造 KPIRoot 输入。
3. 使用 SAX 表示、Jaccard 相似度和 Granger 因果关系生成候选排序。
4. 将原论文中的 KPI 级定位结果适配为 Online Boutique 的服务级候选排序。
5. 使用 Hit@k 或 tie-aware rank 等口径评估根因服务是否进入候选前列。

## Data and Results

本提交目录不包含实验数据和结果文件。运行脚本时需要自行准备或重新采集：

- Prometheus 导出的原始指标
- JMeter 压测结果
- CATCH 输入与输出
- KPIRoot 输入与输出
- 图像、报告和 PPT 文件

建议将运行产物保存在仓库外部的 `data/`、`result/`、`outputs/` 或类似目录中，避免与提交代码混在一起。

## Notes

- 本仓库用于课程项目复现实验提交，重点是代码、配置与复现流程。
- Online Boutique、CATCH 和 KPIRoot 子目录中保留了各自的原始代码结构。
- 运行前请根据本机 Kubernetes、Prometheus、JMeter 和 Python 环境调整路径与参数。
