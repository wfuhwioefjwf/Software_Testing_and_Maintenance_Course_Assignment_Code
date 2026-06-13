# JMeter Tests for Online Boutique

## 实验目的

使用 JMeter 对 Online Boutique 前端服务进行性能测试，通过轻负载、中负载和高负载三组并发场景模拟用户访问完整购物流程，观察平均响应时间、95% 响应时间、吞吐量和错误率等指标变化。

测试对象：

```text
http://localhost:8080
```

前端服务端口转发命令示例：

```powershell
kubectl port-forward svc/frontend 8080:80 -n default
```

本目录只提供 JMeter 测试计划文件，不需要执行 `kubectl` 命令。

## 目录结构

```text
jmeter-tests/
├── jmx/
│   ├── online_boutique_light_load.jmx
│   ├── online_boutique_medium_load.jmx
│   └── online_boutique_high_load.jmx
├── results/
└── README.md
```

## 运行前准备

1. 确认 Online Boutique 前端已经可以通过 `http://localhost:8080` 访问。
2. 确认所有 Online Boutique 业务 Pod 处于 `Running` 状态。
3. 测试前建议关闭 `loadgenerator`，避免它产生额外背景流量影响 JMeter 结果。
4. 不要同时运行 Chaos Mesh 故障注入实验，避免性能数据混入故障影响。
5. 三组测试之间建议等待 1 到 2 分钟，让系统恢复稳定。

## 负载场景

| 场景 | JMX 文件 | 并发用户数 | Ramp-up | 持续时间 |
| --- | --- | ---: | ---: | ---: |
| 轻负载 | `jmx/online_boutique_light_load.jmx` | 5 | 10 秒 | 180 秒 |
| 中负载 | `jmx/online_boutique_medium_load.jmx` | 15 | 30 秒 | 180 秒 |
| 高负载 | `jmx/online_boutique_high_load.jmx` | 30 | 60 秒 | 180 秒 |

不再设计额外的持续负载实验。

## 业务流程

每个 JMX 文件都使用 `Transaction Controller` 统计完整事务耗时，事务名为：

```text
Online Boutique Shopping Flow
```

事务内包含以下 HTTP 请求：

1. `GET /`：访问首页。
2. `GET /product/OLJCESPC7Z`：访问商品详情页，商品为 `Sunglasses`。
3. `POST /cart`：加入购物车，参数为 `product_id=OLJCESPC7Z`、`quantity=1`。
4. `GET /cart`：访问购物车页面。
5. `POST /cart/checkout`：提交订单。

请求参数参考了当前项目中的 Online Boutique 前端源码和 Selenium 测试脚本。其中：

- 加入购物车表单字段来自 `product.html`：`product_id`、`quantity`。
- 提交订单字段来自 `cart.html` 和 `handlers.go`：`email`、`street_address`、`zip_code`、`city`、`state`、`country`、`credit_card_number`、`credit_card_expiration_month`、`credit_card_expiration_year`、`credit_card_cvv`。
- 商品 ID 来自 `products.json`：`OLJCESPC7Z`。

## JMeter 组件

每个测试计划包含：

- Thread Group
- HTTP Request Defaults
- HTTP Cookie Manager
- HTTP Header Manager
- Transaction Controller
- HTTP Request Samplers
- Summary Report
- Aggregate Report
- View Results Tree

`View Results Tree` 已保留但默认禁用。调试脚本时可以临时启用；正式压测时建议保持关闭，以减少 JMeter 客户端自身开销。

未包含 Backend Listener。

## 运行命令

进入测试目录：

```powershell
cd D:\Latex\软测维大作业\code\jmeter-tests
```

轻负载：

```powershell
jmeter -n -t jmx/online_boutique_light_load.jmx -l results/light_load.jtl -e -o results/light_load_report
```

中负载：

```powershell
jmeter -n -t jmx/online_boutique_medium_load.jmx -l results/medium_load.jtl -e -o results/medium_load_report
```

高负载：

```powershell
jmeter -n -t jmx/online_boutique_high_load.jmx -l results/high_load.jtl -e -o results/high_load_report
```

如果重复运行同一场景，先删除对应的 `.jtl` 文件和报告目录，或更换输出文件名，避免 JMeter 报告目录已存在导致运行失败。

## 关注指标

建议重点关注：

- 平均响应时间：观察整体响应耗时是否随并发上升明显增加。
- 95% 响应时间：观察大多数请求的尾部延迟。
- 吞吐量：观察每秒处理请求数随并发上升的变化。
- 错误率：观察是否出现 HTTP 4xx/5xx、连接失败或订单提交失败。

建议同时在 Grafana 中观察：

- frontend Pod CPU / Memory
- checkoutservice、cartservice、productcatalogservice 的 CPU / Memory
- Pod 重启次数
- 网络流量
- 服务错误率和请求延迟

