# Promotion Service 优惠券/促销码微服务开发说明

## 1. 开发目标

本次开发的目标是在 Online Boutique 微服务系统中新增一个独立的优惠券/促销码微服务 `promotionservice`，用于完成优惠码校验、折扣计算、购物车折扣预览和结算阶段最终折扣确认。

该功能不是简单地在前端页面上展示一个静态折扣，而是设计成一个完整的微服务交互链路：

```text
用户在购物车页输入优惠码
        ↓
frontend 调用 promotionservice 保存优惠码并预览折扣
        ↓
用户提交订单
        ↓
checkoutservice 调用 promotionservice 重新校验优惠码
        ↓
checkoutservice 使用折扣后的金额调用 paymentservice 扣款
        ↓
frontend 在订单完成页展示优惠码和折扣金额
```

通过这个链路，`promotionservice` 成为 Online Boutique 中一个真实参与业务流程的新微服务。它既和 `frontend` 有交互，也和 `checkoutservice` 有交互，并且最终会影响 `paymentservice` 的扣款金额，能够体现微服务开发、部署、测试、监控和故障注入的完整闭环。

## 2. 需求分析与设计取舍

### 2.1 为什么选择优惠券/促销码服务

Online Boutique 本身是电商系统，已有商品、购物车、结算、支付、推荐、广告等基础服务。优惠券/促销码属于典型电商业务能力，和现有系统的业务语义高度匹配。

相比只增强已有服务，新增 `promotionservice` 的优势是：

- 业务合理：优惠券服务是电商系统常见的独立业务模块。
- 展示清晰：可以在购物车页看到输入优惠码、折扣、折后总价。
- 交互完整：涉及 `frontend`、`checkoutservice`、`paymentservice` 三段链路。
- 运维友好：可以针对 `promotionservice` 做 Prometheus 指标采集和 ChaosMesh 故障注入。
- 难度可控：优惠规则采用内置规则，不接数据库，避免工作量失控。

### 2.2 为什么没有直接改成新的 gRPC 服务

Online Boutique 大多数核心服务之间使用 gRPC，但本次新增 `promotionservice` 采用 HTTP/JSON 方式，主要出于以下考虑：

- 降低 proto 生成和多语言联调成本。
- `frontend` 和 `checkoutservice` 都是 Go 服务，调用 HTTP/JSON 很直接。
- 优惠券服务本身是轻量查询/计算型服务，HTTP API 足够表达业务。
- HTTP 接口更容易被 JMeter、curl、Postman、Selenium 流程间接验证。
- `/metrics` 和 `/healthz` 也天然适合 HTTP 暴露。

同时，在 `protos/demo.proto` 中预留了 `promo_code` 和 `discount` 字段，作为后续升级到 gRPC 字段直传的设计记录。由于当前开发环境缺少 `protoc`，没有强行手改生成代码，而是采用更稳妥的运行时方案：`frontend` 将用户优惠码保存到 `promotionservice` 的 session 映射中，`checkoutservice` 使用已有的 `user_id` 查询该用户当前优惠码并重新计算折扣。这样避免了生成代码和 proto 描述符不一致的问题。

## 3. 总体架构

新增服务：

```text
promotionservice
```

主要调用关系：

```text
frontend  --HTTP/JSON-->  promotionservice
checkoutservice  --HTTP/JSON-->  promotionservice
checkoutservice  --gRPC-->  paymentservice
```

`frontend` 的职责：

- 在购物车页展示优惠码输入框。
- 将用户输入的优惠码保存到 promotionservice。
- 在购物车页调用 promotionservice 计算折扣预览。
- 在订单完成页再次调用 promotionservice 展示优惠码和折扣信息。

`promotionservice` 的职责：

- 保存用户 session 与优惠码的映射关系。
- 校验优惠码是否合法。
- 根据购物车商品小计和运费计算折扣。
- 返回折扣金额和折扣后总价。
- 暴露健康检查和 Prometheus 指标。

`checkoutservice` 的职责：

- 在下单时重新计算订单商品小计和运费。
- 调用 promotionservice 做最终优惠校验。
- 使用 promotionservice 返回的折后金额调用 paymentservice。
- 如果 promotionservice 不可用，则下单失败，便于故障注入展示。

## 4. Promotion Service 接口设计

### 4.1 健康检查接口

```http
GET /healthz
```

返回：

```text
ok
```

用途：

- Kubernetes readinessProbe
- Kubernetes livenessProbe
- 手工验证服务是否存活

### 4.2 Prometheus 指标接口

```http
GET /metrics
```

返回 Prometheus text exposition format，例如：

```text
promotionservice_requests_total 10
promotionservice_quote_requests_total 4
promotionservice_errors_total 0
promotionservice_request_duration_seconds_sum 0.031
promotionservice_request_duration_seconds_count 10
```

用途：

- Prometheus 抓取服务请求量。
- Grafana 展示请求数、错误数、请求耗时。
- ChaosMesh 故障注入后观察服务表现。

### 4.3 保存用户优惠码

```http
POST /api/v1/promotions/session
```

请求体：

```json
{
  "user_id": "session-id",
  "code": "SAVE10"
}
```

行为：

- `code` 会被自动去除首尾空格并转为大写。
- 如果 `code` 为空，则清除该用户当前优惠码。
- 服务使用内存中的 `map[user_id]promo_code` 保存映射。
- 使用 `sync.RWMutex` 保护并发访问。

### 4.4 计算优惠报价

```http
POST /api/v1/promotions/quote
```

请求体：

```json
{
  "user_id": "session-id",
  "code": "SAVE10",
  "subtotal": {
    "currency_code": "USD",
    "units": 50,
    "nanos": 0
  },
  "shipping": {
    "currency_code": "USD",
    "units": 5,
    "nanos": 0
  }
}
```

返回体：

```json
{
  "valid": true,
  "code": "SAVE10",
  "message": "SAVE10 applied: 10% off merchandise.",
  "discount": {
    "currency_code": "USD",
    "units": 5,
    "nanos": 0
  },
  "final_total": {
    "currency_code": "USD",
    "units": 50,
    "nanos": 0
  }
}
```

如果请求中 `code` 为空，但提供了 `user_id`，服务会根据 `user_id` 查询之前保存的优惠码。这一点用于 `checkoutservice` 的最终校验：checkout 不需要从 gRPC 请求中额外获得优惠码，也能根据用户 session 找到当前优惠码。

## 5. 优惠规则设计

当前内置 3 个演示优惠码：

| 优惠码 | 规则 | 示例 |
|---|---|---|
| `SAVE10` | 商品小计 10% 折扣 | 商品小计 50 美元，优惠 5 美元 |
| `WELCOME5` | 商品小计满 25 美元减 5 美元 | 商品小计 30 美元，优惠 5 美元 |
| `FREESHIP` | 免运费 | 运费 8.99 美元，优惠 8.99 美元 |

非法优惠码会返回：

```json
{
  "valid": false,
  "message": "Promotion code is not valid.",
  "discount": {
    "units": 0,
    "nanos": 0
  }
}
```

优惠金额不会超过订单总价，避免出现负数总价。

## 6. 金额处理技巧

Online Boutique 使用类似 Google Money 的结构表示金额：

```text
currency_code
units
nanos
```

直接用浮点数做金额计算容易出现精度误差，因此 `promotionservice` 内部采用“分”为单位进行计算：

```go
func cents(m money) int64 {
    return m.Units*100 + int64(math.Round(float64(m.Nanos)/10000000.0))
}
```

计算完成后再转换回 `Money` 风格结构：

```go
func moneyFromCents(currency string, value int64) money {
    units := value / 100
    nanos := int32((value % 100) * 10000000)
    return money{CurrencyCode: currency, Units: units, Nanos: nanos}
}
```

这样做有几个好处：

- 避免浮点金额误差。
- 保持和 Online Boutique 原有金额结构兼容。
- frontend、checkoutservice、promotionservice 之间的数据格式一致。
- 方便在报告中说明数据处理和工程细节。

## 7. 并发与状态管理

`promotionservice` 使用内存 `map` 保存用户 session 和优惠码之间的关系：

```go
sessions map[string]string
```

由于 HTTP 服务可能并发处理多个请求，所以使用：

```go
sync.RWMutex
```

来保护读写：

- `sessionHandler` 写入或删除优惠码时加写锁。
- `quoteHandler` 根据 user_id 查询优惠码时加读锁。

这种设计不需要数据库，适合课程项目和本地实验环境。它的局限是服务重启后 session 优惠码会丢失，如果要扩展到生产级系统，可以替换为 Redis、数据库或 Kubernetes ConfigMap/Secret 管理规则。

## 8. Frontend 修改内容

### 8.1 新增 promotion 客户端

新增文件：

```text
src/frontend/promotion.go
```

主要功能：

- 定义 HTTP 请求/响应结构。
- 将 frontend 的 `pb.Money` 转换为 JSON 友好的 `promotionMoney`。
- 调用 promotionservice 的 quote 接口。
- 调用 promotionservice 的 session 接口。
- 设置 300ms 超时，避免 promotionservice 响应慢时拖垮前端。

关键方法：

```go
quotePromotion(...)
savePromotionCode(...)
postPromotionJSON(...)
```

### 8.2 注册 promotionservice 地址

修改：

```text
src/frontend/main.go
```

新增字段：

```go
promotionSvcAddr string
```

新增环境变量：

```text
PROMOTION_SERVICE_ADDR
```

Kubernetes 中配置为：

```text
http://promotionservice:8080
```

### 8.3 新增购物车优惠码路由

新增路由：

```go
r.HandleFunc(baseUrl+"/cart/promo", svc.applyPromotionHandler).Methods(http.MethodPost)
```

用户在购物车页输入优惠码后，表单提交到 `/cart/promo`。frontend 会：

1. 读取用户输入的 `promo_code`。
2. 去除空格并转换为大写。
3. 调用 promotionservice 保存该用户的优惠码。
4. 将优惠码写入浏览器 cookie。
5. 重定向回购物车页。

### 8.4 购物车页折扣预览

修改：

```text
src/frontend/handlers.go
```

在 `viewCartHandler` 中：

1. 计算商品小计 `subtotalPrice`。
2. 获取运费 `shippingCost`。
3. 读取当前用户优惠码。
4. 调用 promotionservice 获取折扣。
5. 如果优惠有效，则用 `final_total` 替换购物车总价。
6. 将 promotion 信息传给模板。

修改：

```text
src/frontend/templates/cart.html
```

新增展示：

- 优惠码输入框
- Apply 按钮
- 优惠码校验消息
- Discount 行
- 折扣后的 Total

### 8.5 订单完成页展示

修改：

```text
src/frontend/templates/order.html
```

订单完成后，frontend 会根据订单商品和运费再次查询 promotionservice，并展示：

```text
Promotion SAVE10 (-$5.00)
Total Paid $50.00
```

这样展示效果更完整，答辩时可以清楚证明优惠码影响了订单金额。

## 9. Checkoutservice 修改内容

### 9.1 新增 promotion 客户端

新增文件：

```text
src/checkoutservice/promotion.go
```

主要功能：

- 构造 promotionservice quote 请求。
- 将 checkoutservice 的 `pb.Money` 转为 JSON 金额结构。
- 调用 promotionservice。
- 设置 500ms 超时。
- 校验返回结果中必须包含 `final_total`。

### 9.2 结算前最终校验

修改：

```text
src/checkoutservice/main.go
```

原始逻辑是：

```text
商品小计 + 运费 = total
调用 paymentservice 扣款 total
```

修改后逻辑是：

```text
商品小计 + 运费 = total
调用 promotionservice 获取折扣
如果优惠有效：
    total = promotionservice.final_total
调用 paymentservice 扣款 total
```

关键点：

- frontend 的折扣只用于展示，不能作为最终付款依据。
- checkoutservice 会重新计算订单金额，并再次调用 promotionservice。
- 这样避免用户通过篡改前端页面影响真实扣款金额。

如果 promotionservice 不可用：

```go
return nil, status.Errorf(codes.Unavailable, "promotion service unavailable: %+v", err)
```

这个设计让故障注入效果更明显：当 promotionservice 被 ChaosMesh 注入延迟或故障时，下单链路会直接受到影响，便于观察系统稳定性和故障传播。

## 10. Proto 设计记录

修改：

```text
protos/demo.proto
```

新增字段：

```proto
message OrderResult {
    Money discount = 6;
    string promo_code = 7;
}

message PlaceOrderRequest {
    string promo_code = 7;
}
```

这些字段用于记录理想 gRPC 设计：未来如果环境中安装了 `protoc` 和 Go/Python/Java 生成插件，可以重新生成各服务的 proto 代码，改为直接在 `PlaceOrderRequest` 中传递 `promo_code`，并在 `OrderResult` 中返回 `discount`。

当前实现没有直接依赖这些生成字段，原因是开发环境缺少 `protoc`。为了避免手工修改生成代码造成 proto 描述符不一致，本次使用 session 绑定方式完成运行时链路。

## 11. Kubernetes 与部署修改

### 11.1 新增 promotionservice manifests

新增：

```text
kubernetes-manifests/promotionservice.yaml
kustomize/base/promotionservice.yaml
```

包含：

- Deployment
- Service
- ServiceAccount
- readinessProbe
- livenessProbe
- Prometheus scrape annotations
- CPU/memory requests 和 limits

Prometheus annotations：

```yaml
prometheus.io/scrape: "true"
prometheus.io/path: "/metrics"
prometheus.io/port: "8080"
```

### 11.2 接入 frontend 和 checkoutservice

修改：

```text
kubernetes-manifests/frontend.yaml
kubernetes-manifests/checkoutservice.yaml
kustomize/base/frontend.yaml
kustomize/base/checkoutservice.yaml
```

新增环境变量：

```yaml
- name: PROMOTION_SERVICE_ADDR
  value: "http://promotionservice:8080"
```

### 11.3 Skaffold 构建配置

修改：

```text
skaffold.yaml
```

新增镜像构建项：

```yaml
- image: promotionservice
  context: src/promotionservice
```

因此执行：

```bash
skaffold run
```

时，Skaffold 会同时构建并部署：

- frontend
- checkoutservice
- promotionservice
- 其他原有服务

### 11.4 Release manifests

修改：

```text
release/kubernetes-manifests.yaml
```

同步加入：

- promotionservice Deployment
- promotionservice Service
- promotionservice ServiceAccount
- frontend 的 `PROMOTION_SERVICE_ADDR`
- checkoutservice 的 `PROMOTION_SERVICE_ADDR`

需要注意：如果直接使用 release 文件部署，必须确保 frontend、checkoutservice、promotionservice 使用的是本次修改后的自定义镜像。更推荐本地实验时使用 `skaffold run`，因为它会自动构建本地修改后的镜像。

## 12. Docker 化

新增：

```text
src/promotionservice/Dockerfile
```

构建方式采用多阶段构建：

1. 使用 `golang:1.23.1-alpine` 编译静态二进制。
2. 使用 `scratch` 作为最终运行镜像。

优点：

- 镜像小。
- 攻击面少。
- 不依赖运行时 shell 或额外系统库。
- 和 Online Boutique 其他 Go 服务 Dockerfile 风格一致。

## 13. 测试与验证

### 13.1 单元测试

新增：

```text
src/promotionservice/main_test.go
```

覆盖场景：

- `SAVE10` 正确计算 10% 折扣。
- `WELCOME5` 在未满 25 美元时返回无效。
- `FREESHIP` 正确抵扣运费。

### 13.2 构建验证

已验证：

```bash
go test ./...
go build ./...
```

通过的模块：

- `src/promotionservice`
- `src/frontend`
- `src/checkoutservice`

### 13.3 Docker 验证

已执行：

```bash
docker build src/promotionservice -t promotionservice:test
```

并通过容器烟测：

```http
GET /healthz
POST /api/v1/promotions/quote
```

`SAVE10` 输入：

```json
{
  "code": "SAVE10",
  "subtotal": {
    "currency_code": "USD",
    "units": 50,
    "nanos": 0
  },
  "shipping": {
    "currency_code": "USD",
    "units": 5,
    "nanos": 0
  }
}
```

返回：

```json
{
  "valid": true,
  "code": "SAVE10",
  "discount": {
    "currency_code": "USD",
    "units": 5,
    "nanos": 0
  },
  "final_total": {
    "currency_code": "USD",
    "units": 50,
    "nanos": 0
  }
}
```

### 13.4 Kubernetes 渲染验证

已执行：

```bash
kubectl kustomize kubernetes-manifests
kubectl kustomize kustomize/base
```

渲染结果中包含：

- promotionservice ServiceAccount
- promotionservice Service
- promotionservice Deployment
- frontend 的 `PROMOTION_SERVICE_ADDR`
- checkoutservice 的 `PROMOTION_SERVICE_ADDR`

由于本机 kubeconfig 权限限制，`kubectl apply --dry-run=client` 无法访问 API discovery，因此没有完成 apply dry-run，但 kustomize 渲染本身已经通过。

## 14. 可观测性设计

promotionservice 暴露 `/metrics`，可以被 Prometheus 抓取。

当前指标：

| 指标名 | 类型 | 含义 |
|---|---|---|
| `promotionservice_requests_total` | counter | 总 HTTP 请求数 |
| `promotionservice_quote_requests_total` | counter | quote 请求数 |
| `promotionservice_errors_total` | counter | 错误请求数 |
| `promotionservice_request_duration_seconds_sum` | summary-like | 请求耗时总和 |
| `promotionservice_request_duration_seconds_count` | summary-like | 请求耗时计数 |

Grafana 可以展示：

- promotionservice QPS
- quote 请求量
- 错误率
- 平均请求耗时

平均耗时可以通过：

```promql
rate(promotionservice_request_duration_seconds_sum[1m])
/
rate(promotionservice_request_duration_seconds_count[1m])
```

计算。

## 15. ChaosMesh 故障注入展示思路

可以针对 `promotionservice` 做以下故障注入：

### 15.1 网络延迟

对 promotionservice 注入网络延迟后，观察：

- 购物车页优惠码应用是否变慢。
- checkoutservice 下单是否失败或延迟增加。
- Grafana 中 promotionservice 请求耗时是否升高。

### 15.2 Pod Kill

杀掉 promotionservice Pod 后，观察：

- frontend 购物车页是否记录 promotion quote 失败。
- checkoutservice 是否返回 `promotion service unavailable`。
- 订单链路是否受到影响。

### 15.3 CPU 压力

对 promotionservice 注入 CPU 压力后，观察：

- promotionservice 请求耗时。
- checkoutservice 付款前等待时间。
- JMeter 下单接口响应时间变化。

这种故障注入很适合在报告中展示“新增微服务对系统链路的影响”和“微服务故障传播”。

## 16. Selenium 与 JMeter 测试建议

### 16.1 Selenium 功能测试

测试流程：

1. 打开首页。
2. 进入某个商品详情页。
3. 添加商品到购物车。
4. 在购物车页输入 `SAVE10`。
5. 点击 Apply。
6. 检查页面出现 `SAVE10 applied`。
7. 检查 Discount 行出现。
8. 提交订单。
9. 检查订单完成页展示 Promotion 和折后 Total Paid。

### 16.2 JMeter 性能测试

建议压测接口：

- `GET /`
- `GET /product/{id}`
- `GET /cart`
- `POST /cart/promo`
- `POST /cart/checkout`

建议对比：

- 不使用优惠码时的购物车/下单响应时间。
- 使用优惠码时的购物车/下单响应时间。
- promotionservice 被 ChaosMesh 注入延迟后的响应时间。

## 17. 本次开发涉及的文件

新增文件：

```text
src/promotionservice/go.mod
src/promotionservice/main.go
src/promotionservice/main_test.go
src/promotionservice/Dockerfile
src/frontend/promotion.go
src/checkoutservice/promotion.go
kubernetes-manifests/promotionservice.yaml
kustomize/base/promotionservice.yaml
docs/promotionservice-development.md
```

修改文件：

```text
src/frontend/main.go
src/frontend/handlers.go
src/frontend/templates/cart.html
src/frontend/templates/order.html
src/frontend/static/styles/cart.css
src/checkoutservice/main.go
protos/demo.proto
skaffold.yaml
kubernetes-manifests/kustomization.yaml
kubernetes-manifests/frontend.yaml
kubernetes-manifests/checkoutservice.yaml
kustomize/base/kustomization.yaml
kustomize/base/frontend.yaml
kustomize/base/checkoutservice.yaml
release/kubernetes-manifests.yaml
```

## 18. 技术点总结

本次开发使用和体现了以下技术：

- Go HTTP 服务开发。
- REST/JSON API 设计。
- 微服务间 HTTP 调用。
- gRPC 业务链路旁路扩展。
- Kubernetes Deployment/Service/ServiceAccount。
- Skaffold 镜像构建与部署。
- Docker 多阶段构建。
- Prometheus metrics 文本格式暴露。
- Kubernetes readinessProbe/livenessProbe。
- 金额计算精度处理。
- 并发读写保护。
- frontend 模板渲染。
- checkout 最终服务端校验。
- ChaosMesh 故障注入友好设计。

## 19. 可以在报告中强调的贡献点

报告中可以这样总结本人的开发贡献：

1. 设计并实现了新的 `promotionservice` 微服务，提供优惠码保存、校验和折扣计算能力。
2. 设计了 `frontend -> promotionservice -> checkoutservice -> paymentservice` 的完整业务链路。
3. 在购物车页增加优惠码输入、折扣预览和折后总价展示。
4. 在 checkoutservice 中实现服务端最终校验，避免只依赖前端折扣，提升业务可信度。
5. 为 promotionservice 增加 `/healthz` 和 `/metrics`，支持 Kubernetes 健康检查和 Prometheus 监控。
6. 编写 promotionservice 单元测试，覆盖核心优惠规则。
7. 修改 Skaffold 与 Kubernetes manifests，使新增微服务可以容器化部署到集群中。
8. 为后续 ChaosMesh 故障注入、Grafana 监控展示、Selenium/JMeter 测试提供了明确切入点。

## 20. 局限性与后续优化

当前实现适合课程项目和展示，但仍有可以扩展的地方：

- 优惠码规则当前写在代码中，后续可以接数据库或 ConfigMap。
- session 与优惠码关系当前保存在内存中，服务重启会丢失，后续可以接 Redis。
- 当前没有优惠码有效期、使用次数、用户限领等复杂规则，后续可以扩展。
- 当前 promotionservice 使用 HTTP/JSON，后续可以基于 `protos/demo.proto` 中预留字段升级为 gRPC。
- 当前 metrics 是轻量手写版，后续可以接入正式 Prometheus Go client。

这些局限性也可以在报告中写成“未来优化方向”，体现对系统可扩展性的思考。


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
