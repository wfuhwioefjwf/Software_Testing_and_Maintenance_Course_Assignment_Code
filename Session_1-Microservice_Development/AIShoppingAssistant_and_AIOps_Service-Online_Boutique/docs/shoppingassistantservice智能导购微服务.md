# Shopping Assistant Service AI 智能导购微服务

## 1. 服务概述

`shoppingassistantservice` 是 Online Boutique 系统中的 AI 智能导购微服务。该服务基于 Python 构建，对外提供 gRPC 接口，主要负责接收前端网关传递的用户文本与图片诉求，结合商品知识库和知识图谱（RAG），为用户提供商品推荐与购物咨询服务。

## 2. 核心功能

- **多模态意图识别与图文双模态回答：** 支持接收文本与图片（Base64 编码）双模态输入，利用视觉模型提取图片中的商品风格与特征。
- **基于本地商品知识库与知识图谱的精准推荐（RAG）：** 服务启动时自动读取 `products.json` 构建 FAISS 内存级向量库。AI 智能体能够根据用户的多模态输入，结合RAG快速检索最匹配的Top-N候 选商品和图检索多跳推理，生成包含商品卡片的图文并茂的推荐结果。
- **缺货安抚与规则约束：** 在 System Prompt 中注入了标准作业程序（SOP），**严格限制模型凭空捏造商品**，并在无匹配结果时输出规范的安抚反馈。
- **流式响应（Streaming）：** 采用 **Server-Streaming RPC** 模式，将大模型的生成结果实时分块（Chunk）返回给前端，降低端到端首字延迟（TTFT），实时拼装并利用marked.js 进行Markdown 渲染。
- **多轮对话上下文记忆：**导购系统设计了基于SessionID的历史对话滑动窗口缓存机制。 系统会保存用户对话记录，并在多轮交互中，AI智能体能够“记住”用户在前序对话 中提到的尺寸、颜色偏好或预算限制，实现连贯的顾问式导购服务。

## 3. 架构与交互链路

本服务不直接面向最终用户，而是作为后端服务被 `frontend` 网关调用。核心数据流向如下：

```text
Browser (用户终端)
  │
  ├─ [HTTP POST /bot (JSON)] 
  │
Frontend (Go 网关)
  │
  ├─ [gRPC Unary-Stream] 
  │
ShoppingAssistantService (Python 智能导购服务)
  │
  ├─ [HTTP API] ──> Qwen API (文本向量化 & 图片特征提取)
  │
  ├─ [Local] ─────> FAISS Vector Index (商品相似度检索)
  │
  └─ [HTTP API (Stream)] ──> DeepSeek API (大语言模型推理)
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
| `QWEN_BASE_URL`     | 阿里云百炼 API 地址       | `https://dashscope.aliyuncs.com/...` |

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