# 软件测试与维护大作业代码仓库

## 仓库作用

本仓库用于保存“软件测试与维护（2026 年春）”大作业的项目源码、实验配置、测试脚本和论文复现代码。根据作业要求，本项目围绕微服务系统的部署、测试与维护展开，覆盖微服务开发、故障注入与监控、功能/性能测试、异常检测与故障诊断论文复现等内容。

我们小组选择的微服务系统是 **Online Boutique**。Online Boutique 是 Google Cloud 提供的云原生电商微服务演示系统，包含前端、购物车、商品目录、结算、支付、推荐、广告等多个服务，适合用于 Kubernetes 部署、可观测性建设、故障注入和测试实验。

## 完成内容说明

根据大作业文档中的“要求+评分标准”，本项目选择了比 SockShop 更复杂的开源微服务系统 Online Boutique 进行部署、监控和维护，符合第二档要求；同时在 Online Boutique 基础上进行了微服务开发，已完成 `promotionservice` 优惠券/促销码微服务的设计、实现与系统集成，符合第三档中“完成一到两个微服务开发”的要求。

在测试与维护方面，本项目完成了基于 Chaos Mesh 的故障注入实验，并结合 Prometheus 与 Grafana 进行监控数据采集和可视化分析；完成了基于 Selenium 的前端功能测试，以及基于 JMeter 的轻负载、中负载和高负载性能测试；完成了多篇异常检测与故障诊断相关论文的复现，包括 CATCH、KPIRoot、KAN-AD、DiMER、SRCNN 和 InterFusion，覆盖了作业要求中的异常数据采集、算法复现和效果分析内容，也对应加分项中的更多论文复现与对比。

## 小组成员分工

- 沈远航：负责微服务开发，开发 Online Boutique 中的 `promotionservice` 优惠券/促销码微服务。
- 杨嘉仪：负责微服务开发，开发 Online Boutique 中的 `shoppingassistantservice` AI 智能导购微服务和 `aiopsservice` 智能运维开发。
- 薛以贤：负责故障注入与监控、微服务系统测试两部分。
- 王熙康：负责异常数据采集与分析，复现论文为 `CATCH`和`KPIRoot`。
- 游雨亮：负责异常数据采集与分析，复现论文为 `KAN-AD`和`DiMER`。
- 李宇帆：负责异常数据采集与分析，复现论文为 `SRCNN`和`InterFusion`。


## 仓库结构与使用方法

### Session 1：微服务开发

目录：`Session_1-Microservice_Development/Promotion_Service-Online_Boutique`

该目录保存基于 Online Boutique 的微服务开发代码与说明。当前入口 README 详细说明了新增 `promotionservice` 优惠券/促销码微服务的开发目标、接口设计、服务交互链路、部署配置和验证方式。使用时先阅读该目录下的 `README.md`，再根据其中说明构建镜像、部署 Kubernetes 配置，并通过前端购物车与结算流程验证优惠码功能。

### Session 2：故障注入与监控

目录：`Session_2-Fault_Injection_and_Monitoring/Chaos_Experiments`

该目录保存 Chaos Mesh 故障注入实验配置，共包含 Pod 删除、Pod 故障、CPU 压力、内存压力、网络延迟和网络隔离等实验。使用时先确认 Online Boutique 已部署在 Kubernetes 集群中，并已配置 Prometheus/Grafana 监控；随后参考该目录下的 `README.md`，使用 `kubectl apply -f <实验文件>` 执行单个故障实验，观察 Pod 状态、服务日志和 Grafana 指标，实验结束后使用 `kubectl delete -f <实验文件>` 清理。

### Session 3：微服务系统测试

目录：`Session_3-Microservice_System_Testing`

该目录包含两类测试代码：

- `Jmeter_Tests`：保存 JMeter 性能测试计划，面向 Online Boutique 前端服务设计轻负载、中负载和高负载三组购物流程压测。使用前需要将前端服务端口转发到 `http://localhost:8080`，然后按照该目录 `README.md` 中的命令运行对应 `.jmx` 文件，并查看生成的 `.jtl` 与 HTML 报告。
- `Selenium_Tests`：保存 Python + Selenium 功能测试脚本，用于自动执行打开首页、进入商品详情、加入购物车、填写结算表单、提交订单和返回购物页面等完整购物流程。使用前需要准备浏览器驱动并完成端口转发，然后运行 `python .\test_online_boutique_flow.py`，测试结果会写入 CSV 文件。

### Session 4：异常数据采集与分析——论文复现

目录：`Session_4-Paper_Reproduction`

该目录保存基于 Online Boutique 监控数据的异常检测与故障诊断论文复现代码，分为三个子项目：

- `CATCH_and_KPIRoot-Online_Boutique`：复现 CATCH 多变量时序异常检测与 KPIRoot 根因定位方法。使用流程包括部署 Online Boutique、产生业务流量、通过 Chaos Mesh 注入故障、从 Prometheus 导出指标、转换输入格式，并分别运行 CATCH 与 KPIRoot。
- `KAN-AD_and_DiMER-Online_Boutique`：复现 KAN-AD 与 DiMER 异常检测方法。使用流程包括启动 minikube、部署 Online Boutique、安装 Chaos Mesh 和 Prometheus、采集短时故障数据、转换数据格式，并运行 KAN-AD 与 DiMER 的实验脚本。
- `SRCNN_and_InterFusion-Online_Boutique`：保存 Online Boutique 工程和 InterFusion 等复现相关代码。使用时先参考顶层 README 部署 Online Boutique，再进入 `InterFusion` 子目录，按照其 README 安装依赖、准备训练/测试数据并运行训练和预测脚本。

各论文复现目录中的 README 已给出更细的依赖安装、数据准备、脚本入口和结果文件位置。实际运行前需要根据本机的 Kubernetes、Prometheus、JMeter、Python 环境和数据保存路径调整参数。
