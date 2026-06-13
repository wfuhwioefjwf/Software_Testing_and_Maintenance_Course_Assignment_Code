# Selenium Test for Online Boutique

## 实验目的

使用 Python + Selenium 对 Online Boutique 微服务电商系统进行前端功能测试，记录完整购物流程中关键步骤的耗时、执行状态和错误信息，为软件测试与维护大作业提供自动化测试数据。

## 目录结构

```text
selenium-tests/
├── test_online_boutique_flow.py
├── online_boutique_metrics.csv
└── README.md
```

## 运行前准备

确保已安装 Python、Selenium，以及本机 Chrome 或 Edge 浏览器。

当前脚本已默认配置以下本机驱动路径：

```text
D:\chromedriver-win64\chromedriver.exe
D:\edgedriver_win64\msedgedriver.exe
```

如果需要临时覆盖驱动路径，可以在 PowerShell 中设置：

```powershell
$env:CHROMEDRIVER_PATH="D:\chromedriver-win64\chromedriver.exe"
$env:EDGEDRIVER_PATH="D:\edgedriver_win64\msedgedriver.exe"
```

Online Boutique 端口转发示例：

```powershell
kubectl port-forward -n default svc/frontend-external 8080:80
```

如果你的集群没有 `frontend-external`，也可以转发内部 Service：

```powershell
kubectl port-forward -n default svc/frontend 8080:80
```

## 运行方式

进入测试目录：

```powershell
cd D:\Latex\软测维大作业\code\selenium-tests
```

运行测试：

```powershell
python .\test_online_boutique_flow.py
```

脚本默认连续运行 5 次完整购物流程，并按 `test_step` 计算平均耗时后追加写入 CSV。

如果端口不是默认值，可以通过环境变量指定访问地址：

```powershell
$env:ONLINE_BOUTIQUE_URL="http://localhost:8080"
python .\test_online_boutique_flow.py
```

## 浏览器切换

脚本开头有：

```python
BROWSER = "edge"
```

需要使用 Chrome 时，手动改成：

```python
BROWSER = "chrome"
```

脚本启动浏览器时使用临时独立 profile，并关闭信用卡、地址、密码、支付请求、同步和扩展相关功能，避免结算表单填写或提交过程中弹出的保存提示影响自动化测试。

## 输出结果

测试结果追加写入：

```text
online_boutique_metrics.csv
```

CSV 字段为：

```text
system,browser,test_step,status,duration_seconds,remark,timestamp
```

每次执行脚本后，每个步骤会写入一条平均值记录。`duration_seconds` 为 5 次运行的平均耗时；`remark` 会记录参与平均的运行次数、通过次数和失败次数。如果某一步失败，脚本会停止后续流程，把已完成步骤的平均值写入 CSV，并在失败步骤的 `remark` 中记录错误信息。

## 测试范围

Online Boutique 测试完整购物流程：打开首页、进入商品详情、加入购物车、检查购物车、填写结算表单、提交订单、等待订单确认，并点击 `Continue Shopping` 返回购物页面。

