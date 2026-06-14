# 加分项：AIOps Service 智能运维服务

## 1. 服务概述

`aiopsservice` 是针对微服务商城系统设计的一个独立自主的智能运维（AIOps）后台守护微服务。该服务集成了 Prometheus 监控矩阵与 DeepSeek 大语言模型，旨在实现系统异常的**主动感知、自主根因分析、流程审批与受控故障恢复**的闭环运维。

## 2. 核心架构与功能

本服务基于大模型 Agent 架构开发，具备以下核心能力：

- **多维实时监控巡检：** 周期性轮询 Prometheus API，对全局微服务的 CPU、内存、崩溃重启频次及网络吞吐进行多维度聚合分析。
- **ReAct 范式与工具调用：** 赋予大模型操作物理集群的能力。大模型可根据排障上下文，自主调用预定义的 `tools_schema`（包括执行 PromQL `execute_promql`、抓取容器日志 `get_service_logs`、重启服务 `restart_pod`）。
- **轻量级 RAG 与 SOP 注入：** 服务内置本地《运维操作手册》（SOP）。在触发告警时，系统会精准检索对应微服务的标准处理规范，并作为上下文注入大模型 Prompt，有效抑制大模型的“幻觉”与盲目操作，提高运维的准确和专业性。
- **Human-in-the-Loop (人机协同审批)：** 针对 `restart_pod` 等高危变更操作，Agent 内部硬编码了权限拦截器。执行前会挂起进程，等待集群管理员通过终端输入授权（`y/n`），确保生产环境变更的安全可控。

## 3. 部署与权限配置 (RBAC)

由于该服务需要读取系统级日志并修改 Deployment 状态，普通的微服务权限无法满足需求。系统通过专用的 `aiopsservice.yaml` 实施了严格的**基于角色的访问控制（RBAC）**：

- **ServiceAccount:** 为该服务分配了独立的 `aiopsservice-sa`。
- **ClusterRole:** 遵循最小权限原则，仅授予 `pods` 与 `pods/log` 的 `[get, list, watch]` 权限，以及 `deployments` 的 `[patch, update]` 权限。
- **容器基础环境：** Dockerfile 采用多阶段构建，在 `python:3.10-slim` 基础镜像中静态植入了 `kubectl` 工具（v1.31.0），并在构建阶段锁定了阿里云镜像源以加速国内网络依赖拉取。

## 4. 环境变量说明

该服务依赖以下配置运行，建议在 Kubernetes Deployment 中以 `env` 注入或通过 ConfigMap/Secret 管理：

| **环境变量/常量**  | **说明**                                       | **默认值示例**                                               |
| ------------------ | ---------------------------------------------- | ------------------------------------------------------------ |
| `PROMETHEUS_URL`   | 集群内部的 Prometheus API 服务地址             | `http://pro-stack-kube-prometheus-prometheus.monitoring.svc:9090` |
| `OPENAI_API_KEY`   | DeepSeek 模型调用的 API 密钥                   | `sk-...`                                                     |
| `PYTHONUNBUFFERED` | 强制 Python 关闭标准输出缓冲，确保日志实时打出 | `1`                                                          |

## 5. 运维介入指南 (核心实操)

为支持人机协同（HITL）审批，该微服务的 Kubernetes Deployment 显式开启了交互终端配置：

```yaml
tty: true
stdin: true
```

**操作步骤：**

当集群内微服务发生故障，且 AIOps Agent 经过日志分析决定执行 `restart_pod` 时，Agent 会在后台挂起并等待人工指令。集群管理员需按以下步骤介入：

1. **接入 Agent 终端：**

   使用 `kubectl attach` 命令连接到正在运行的智能体容器，接管标准输入输出：

   ```bash
   AGENT_POD=$(kubectl get pods -n default -l app=aiopsservice -o jsonpath='{.items[0].metadata.name}')
   
   kubectl attach $AGENT_POD -c server -n default -i -t
   ```

2. **查看诊断报告与审批：**

   接入后，终端将实时打印大模型的诊断分析依据以及警告提示：

   ```bash
   🚨 警告：AI 申请执行高危动作：【重启服务 cartservice】！
   👉 请管理员审核，是否批准执行？(输入 y 批准，其他拒绝): 
   ```

3. **执行决策：**

   管理员键盘输入 `y` 并回车，Agent 将调用 K8s API 执行滚动重启；输入其他字符将阻断操作。

4. **退出终端：**

   审批完成后，切勿使用 `Ctrl+C`（会终止服务进程），应使用组合键 **`Ctrl+P, Ctrl+Q`** 将其放入后台继续巡检。