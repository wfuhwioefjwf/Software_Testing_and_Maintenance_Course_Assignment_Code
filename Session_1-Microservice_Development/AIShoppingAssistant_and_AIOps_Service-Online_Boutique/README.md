# Shopping Assistant Service AI 智能导购微服务

## 1. 服务概述

`shoppingassistantservice` 是 Online Boutique 系统中的 AI 智能导购微服务。该服务基于 Python 构建，对外提供 gRPC 接口，主要负责接收前端网关传递的用户文本与图片诉求，结合商品知识库和知识图谱（RAG），为用户提供商品推荐与购物咨询服务。

## 2. 核心功能

- **多模态意图识别与图文双模态回答：** 支持接收文本与图片（Base64 编码）双模态输入，利用视觉模型提取图片中的商品风格与特征。
- **基于本地商品知识库与知识图谱的精准推荐（RAG）：** 服务启动时自动读取 `products.json` 构建 FAISS 内存级向量库。AI 智能体能够根据用户的多模态输入，结合RAG快速检索最匹配的Top-N候 选商品和图检索多跳推理，生成包含商品卡片的图文并茂的推荐结果。
- **缺货安抚与规则约束：** 在 System Prompt 中注入了标准作业程序（SOP），**严格限制模型凭空捏造商品**，并在无匹配结果时输出规范的安抚反馈。
- **流式响应（Streaming）：** 采用 **Server-Streaming RPC** 模式，将大模型的生成结果实时分块（Chunk）返回给前端，降低端到端首字延迟（TTFT），实时拼装并利用marked.js 进行Markdown 渲染。
- **多轮对话上下文记忆：** 导购系统设计了基于SessionID的历史对话滑动窗口缓存机制。 系统会保存用户对话记录，并在多轮交互中，AI智能体能够“记住”用户在前序对话 中提到的尺寸、颜色偏好或预算限制，实现连贯的顾问式导购服务。

## 3. 架构与交互链路

本服务不直接面向最终用户，而是作为后端服务被 `frontend` 网关调用。核心数据流向如下：

```text
Browser (用户终端)
  │
  ├─ HTTP POST /bot (JSON) 
  │
Frontend (Go 网关)
  │
  ├─ gRPC Unary-Stream 
  │
ShoppingAssistantService (Python 智能导购服务)
  │
  ├─ HTTP API ──> Qwen API (文本向量化 & 图片特征提取)
  │
  ├─ Local ─────> FAISS Vector Index (商品相似度检索)
  │
  └─ HTTP API (Stream) ──> DeepSeek API (大语言模型推理)
```

## 4. 接口定义

服务基于 Protobuf 定义，暴露以下 gRPC 接口：

```protobuf
service ShoppingAssistantService {
    rpc Chat(ChatRequest) returns (stream ChatResponse) {}
}

message ChatRequest {
    string user_message = 1;
    string image_base64 = 2; 
}

message ChatResponse {
    string ai_reply = 1;
    repeated string product_ids = 2;
}
```

注：服务通过 `yield` 返回数据，当生成推荐商品时，会在流的最后一次返回中包含 `product_ids`。

## 5. 环境变量与配置

运行该服务需要配置以下大模型 API 密钥。部署时可通过 Kubernetes `env` 注入：

| **环境变量**        | **说明**                  | **默认值示例**                       |
| ------------------- | ------------------------- | ------------------------------------ |
| `DEEPSEEK_API_KEY`  | DeepSeek 语言模型 API Key | `sk-...`                             |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址         | `https://api.deepseek.com`           |
| `QWEN_API_KEY`      | 阿里云百炼 (Qwen) API Key | `sk-...`                             |
| `QWEN_BASE_URL`     | 阿里云百炼 API 地址       | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

## 6. 构建与部署

### 6.1 容器化构建

- 本服务采用基础镜像 `python:3.12-slim` 进行打包。
- 为确保多端契约一致性，`demo_pb2.py` 与 `demo_pb2_grpc.py` 不作为静态文件提交，而是在 Docker 构建的最后阶段动态使用 `grpc_tools.protoc` 编译生成。

### 6.2 Kubernetes 部署

- **资源要求：** 建议配置适当的 CPU 与内存 limits（推荐 `CPU: 200m`, `Memory: 256Mi`），以应对 FAISS 向量库常驻内存的需求。
- **镜像拉取策略：** 在迭代开发期间，`deployment.yaml` 中配置为 `imagePullPolicy: IfNotPresent`，以配合 Skaffold 实现本地镜像的热更新。

## 7. 观测与排障设计

- **日志标准：** 服务通过 `PYTHONUNBUFFERED=1` 环境变量强制开启实时标准输出，记录了 FAISS 索引构建进度、检索相似度得分与阈值、模型调用等关键调试信息，便于通过 `kubectl logs` 追踪模型检索逻辑。
- **依赖说明：** 该服务强依赖外部公网 API（DeepSeek / Qwen）。若出现 gRPC 超时，需优先排查集群节点的外网连通性或 API 提供商的可用性。



# AIOps Service 智能运维

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
