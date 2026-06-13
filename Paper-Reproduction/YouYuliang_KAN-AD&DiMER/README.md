# 微服务故障注入与异常检测实验

基于 ChaosMesh 的微服务故障注入与 KAN-AD/DiMER 异常检测复现实验。

## 实验概述

在 Online-Boutique 微服务系统上注入短时故障（2 分钟），通过 Prometheus 采集系统指标，使用 KAN-AD 和 DiMER 两种模型进行异常检测。

**实验结果**：
| 模型 | F1 | Precision | Recall |
|------|-----|-----------|--------|
| KAN-AD | 0.9937 | 0.9919 | 0.9974 |
| DiMER | 0.9990 | 0.9980 | 1.0000 |

## 环境要求

- Docker Desktop
- minikube v1.38+
- kubectl
- Python 3.10+
- Helm（用于 ChaosMesh）

## 复现流程

### 1. 启动 minikube 并部署 Online-Boutique

```bash
# 启动 minikube
minikube start --memory=4096 --cpus=4

# 切换到 minikube Docker 环境
eval $(minikube docker-env)

# 构建镜像（在 Online-Boutique 目录下）
cd Online-Boutique
for svc in adservice cartservice checkoutservice currencyservice emailservice frontend loadgenerator paymentservice productcatalogservice recommendationservice shippingservice; do
  if [ "$svc" = "cartservice" ]; then
    docker build -t $svc src/$svc/src/
  else
    docker build -t $svc src/$svc/
  fi
done

# 修改 imagePullPolicy 并部署
# 编辑 kubernetes-manifests/*.yaml，在每个 image: 行后添加 imagePullPolicy: IfNotPresent
kubectl apply -f kubernetes-manifests/

# 验证所有 Pod 运行正常
kubectl get pods
```

### 2. 安装 ChaosMesh

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
kubectl create ns chaos-testing
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-testing
```

### 3. 部署 Prometheus

```bash
# 如果 monitoring 命名空间中已有 Prometheus，跳过此步
kubectl get pods -n monitoring
```

### 4. 采集短时故障数据

```bash
python collect_short_fault_data.py
```

**采集参数**：
- 基线采集：15 分钟（每 5 秒采样）
- 故障持续时间：2 分钟
- 故障类型：8 种（网络延迟、网络丢包、CPU 压力、内存压力、Pod 杀死）
- 实验轮数：3 轮
- 总场景：24 个

数据保存在 `chaos_data_short/` 目录。

### 5. 转换数据并运行 KAN-AD

```bash
# 转换数据格式
python convert_short_to_kanad.py

# 运行 KAN-AD
cd KAN-AD
python run_short_exp.py
```

结果保存在 `KAN-AD/Results/Evals/KANAD/naive/ChaosBoutiqueShort/avg.json`。

### 6. 运行 DiMER

```bash
cd DiMER
python run_short_exp.py
```

结果保存在 `DiMER/results/short_experiment_results.json`。

## 目录结构

```
.
├── chaos_experiments.yaml          # ChaosMesh 故障定义
├── collect_short_fault_data.py     # 数据采集脚本
├── convert_short_to_kanad.py       # 数据转换脚本
├── chaos_data_short/               # 采集的原始数据
├── KAN-AD/                         # KAN-AD 模型
│   ├── kanad/                      # 模型代码
│   ├── run_short_exp.py            # 实验脚本
│   ├── datasets/UTS/ChaosBoutiqueShort/  # 转换后的数据
│   └── Results/                    # 实验结果
├── DiMER/                          # DiMER 模型
│   ├── dimer/                      # 模型代码
│   ├── run_short_exp.py            # 实验脚本
│   └── results/                    # 实验结果

```

## 故障类型

| 故障类型 | 目标服务 | 参数 |
|----------|----------|------|
| 网络延迟 | frontend | 200ms 延迟，50ms 抖动 |
| 网络延迟 | productcatalogservice | 300ms 延迟，100ms 抖动 |
| 网络丢包 | cartservice | 30% 丢包率 |
| 网络丢包 | paymentservice | 40% 丢包率 |
| CPU 压力 | checkoutservice | 2 workers, 80% |
| CPU 压力 | currencyservice | 2 workers, 90% |
| 内存压力 | recommendationservice | 128Mi |
| Pod 杀死 | adservice | 随机杀死 1 个 Pod |

## 采集的指标

- `container_cpu_usage_seconds_total` - CPU 使用
- `container_memory_working_set_bytes` - 内存使用
- `container_network_receive_bytes_total` - 网络接收
- `container_network_transmit_bytes_total` - 网络发送

## 模型配置

**KAN-AD** (`KAN-AD/kanad/config_short.toml`)：
```toml
window = 5
order = 2
batch_size = 8
epochs = 50
lr = 0.01
```

**DiMER**（`DiMER/run_short_exp.py`）：
```python
window_size = 5
batch_size = 16
epochs = 100
num_memory_slots = 20
hidden_dim = 64
latent_dim = 32
```
