# Chaos Mesh Experiments for Online Boutique

本目录包含 6 个独立的 Chaos Mesh 故障注入实验文件。每个 YAML 只包含一个实验，建议一次只执行一个实验，观察完成后及时 delete，并等待系统恢复稳定后再执行下一个实验。

## 当前集群确认信息

- Online Boutique 部署在 `default` namespace。
- 目标 Pod / Deployment 使用的实际标签是 `app=<service>`，例如 `app=frontend`、`app=productcatalogservice`、`app=cartservice`、`app=checkoutservice`。
- Chaos Mesh 版本标签显示为 `2.8.3`，已安装 `PodChaos`、`StressChaos`、`NetworkChaos` 等 CRD。
- 当前 `StressChaos` webhook 对内存单位要求较严格，内存压力使用 `32MiB`，不要写成 Kubernetes 资源常见的 `32Mi`。

## 通用执行流程

每次实验前先确认所有业务 Pod 为 `Running`：

```powershell
kubectl get pods -n default -o wide
kubectl get deploy -n default
```

执行单个实验：

```powershell
kubectl apply -f .\code\chaos-experiments\<file-name>.yaml
```

观察实验对象：

```powershell
kubectl get podchaos,stresschaos,networkchaos -n default
kubectl describe podchaos,stresschaos,networkchaos -n default
kubectl get pods -n default -w
```

删除单个实验：

```powershell
kubectl delete -f .\code\chaos-experiments\<file-name>.yaml
```

实验结束后建议等待 1 到 2 分钟，再确认系统恢复：

```powershell
kubectl get pods -n default
kubectl get deploy -n default
```

## 实验列表

| 编号 | 文件 | 实验目的 | 注入对象 | 预期观察现象 |
| --- | --- | --- | --- | --- |
| 01 | `01-pod-kill-frontend.yaml` | 删除 frontend Pod，观察 Kubernetes 自愈 | `default` / `app=frontend` | 原 Pod 被删除，新 Pod 自动创建并恢复 Running，短时间前端访问可能中断 |
| 02 | `02-pod-failure-productcatalogservice.yaml` | 模拟商品目录服务短时间不可用 | `default` / `app=productcatalogservice` | 商品列表或商品详情请求异常，Pod 保持存在但不可用，2 分钟后恢复 |
| 03 | `03-stress-cpu-checkoutservice.yaml` | 对 checkoutservice 注入轻量 CPU 压力 | `default` / `app=checkoutservice` | Grafana 中 checkoutservice CPU 使用率上升，3 分钟后回落 |
| 04 | `04-stress-memory-cartservice.yaml` | 对 cartservice 注入轻量内存压力 | `default` / `app=cartservice` | Grafana 中 cartservice 内存使用量小幅上升，3 分钟后回落 |
| 05 | `05-network-delay-productcatalogservice.yaml` | 模拟商品目录服务网络延迟 | `default` / `app=productcatalogservice` | 商品相关请求耗时增加，可能出现页面加载变慢 |
| 06 | `06-network-partition-frontend-productcatalogservice.yaml` | 隔离 frontend 与 productcatalogservice | frontend 到 productcatalogservice，双向隔离 | 前端访问商品信息出现错误或空结果，2 分钟后恢复 |

## 推荐观察命令

Pod 状态与事件：

```powershell
kubectl get pods -n default -w
kubectl describe pod -n default -l app=frontend
kubectl describe pod -n default -l app=productcatalogservice
kubectl get events -n default --sort-by=.lastTimestamp
```

服务与 Endpoint：

```powershell
kubectl get svc -n default
kubectl get endpoints -n default frontend productcatalogservice cartservice checkoutservice
```

业务日志：

```powershell
kubectl logs -n default deploy/frontend --tail=100 -f
kubectl logs -n default deploy/productcatalogservice --tail=100 -f
kubectl logs -n default deploy/cartservice --tail=100 -f
kubectl logs -n default deploy/checkoutservice --tail=100 -f
```

Chaos Mesh 对象：

```powershell
kubectl get podchaos,stresschaos,networkchaos -n default
kubectl describe podchaos pod-kill-frontend -n default
kubectl describe podchaos pod-failure-productcatalogservice -n default
kubectl describe stresschaos stress-cpu-checkoutservice -n default
kubectl describe stresschaos stress-memory-cartservice -n default
kubectl describe networkchaos network-delay-productcatalogservice -n default
kubectl describe networkchaos network-partition-frontend-productcatalogservice -n default
```

## Grafana 建议观察指标

- Pod 状态：Pod Running/Restart、Deployment Available Replicas、Pod 重建时间。
- CPU：`checkoutservice` CPU 使用率、CPU throttling、Pod CPU usage。
- 内存：`cartservice` memory working set、memory usage、是否接近 limit。
- 网络：`productcatalogservice`、`cartservice`、`frontend` 的网络接收/发送速率、错误率、延迟变化。
- 服务访问：frontend 请求耗时、HTTP/gRPC 错误、页面加载是否变慢或出现错误。
- 节点资源：本地 Minikube / Docker Desktop 节点整体 CPU、内存，确认压力实验没有把本地集群打满。

## 单个实验命令速查

```powershell
kubectl apply -f .\code\chaos-experiments\01-pod-kill-frontend.yaml
kubectl delete -f .\code\chaos-experiments\01-pod-kill-frontend.yaml

kubectl apply -f .\code\chaos-experiments\02-pod-failure-productcatalogservice.yaml
kubectl delete -f .\code\chaos-experiments\02-pod-failure-productcatalogservice.yaml

kubectl apply -f .\code\chaos-experiments\03-stress-cpu-checkoutservice.yaml
kubectl delete -f .\code\chaos-experiments\03-stress-cpu-checkoutservice.yaml

kubectl apply -f .\code\chaos-experiments\04-stress-memory-cartservice.yaml
kubectl delete -f .\code\chaos-experiments\04-stress-memory-cartservice.yaml

kubectl apply -f .\code\chaos-experiments\05-network-delay-productcatalogservice.yaml
kubectl delete -f .\code\chaos-experiments\05-network-delay-productcatalogservice.yaml

kubectl apply -f .\code\chaos-experiments\06-network-partition-frontend-productcatalogservice.yaml
kubectl delete -f .\code\chaos-experiments\06-network-partition-frontend-productcatalogservice.yaml
```
