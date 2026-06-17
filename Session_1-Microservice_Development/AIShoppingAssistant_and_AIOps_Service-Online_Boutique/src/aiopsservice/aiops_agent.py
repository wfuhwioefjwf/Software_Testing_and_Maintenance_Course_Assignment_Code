import os
import time
import json
import requests
import subprocess
from openai import OpenAI

PROMETHEUS_URL = "http://pro-stack-kube-prometheus-prometheus.monitoring.svc:9090"

KNOWLEDGE_BASE_SOP = {
    "productcatalogservice": "SOP-001 [商品目录服务]: CPU飙升可能是遭受恶意刷单或缓存穿透。🚨 允许审批后重启！",
    "cartservice": "SOP-002 [购物车服务]: 强依赖 Redis，如果报错先检查 redis-cart 是否正常。🚨 允许审批后重启！",
    "frontend": "SOP-003 [前端服务]: 无状态服务，出现 500 错误允许尝试重启进行快速恢复。",
    "default": "SOP-通用 [通用排查指南]: 严格基于日志里的 Error/Exception 堆栈进行分析，必要时请求管理员审批重启。"
}

# ================= 工具库 (已修复为 online-boutique) =================
def execute_promql(query_str):
    print(f"📊 [工具执行] 查询监控: {query_str}")
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': query_str}, timeout=5)
        results = response.json().get('data', {}).get('result', [])
        return str(results) if results else "未查询到数据"
    except Exception as e:
        return f"查询失败: {e}"

def get_service_logs(service_name, tail_lines=30):
    print(f"📄 [工具执行] 抓取真实日志: deploy/{service_name} (最后 {tail_lines} 行)")
    try:
        cmd = f"/usr/local/bin/kubectl logs deploy/{service_name} -n default --tail={tail_lines}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
        return f"获取日志失败: {result.stderr}"
    except Exception as e:
        return f"执行错误: {str(e)}"

def restart_pod(service_name):
    print(f"🔄 [工具执行] 正在真实重启服务: {service_name}...")
    try:
        cmd = f"/usr/local/bin/kubectl rollout restart deploy/{service_name} -n default"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return f"✅ {service_name} 服务已成功触发滚动重启！"
        return f"❌ 重启失败: {result.stderr}"
    except Exception as e:
        return f"❌ 执行重启异常: {str(e)}"

AVAILABLE_TOOLS = {"execute_promql": execute_promql, "get_service_logs": get_service_logs, "restart_pod": restart_pod}

class AIOpsAgentPro:
    def __init__(self, api_key, base_url):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = "deepseek-v4-pro"
        
        self.tools_schema = [
            {
                "type": "function",
                "function": {
                    "name": "execute_promql",
                    "description": "执行 PromQL 获取 Prometheus 监控指标",
                    "parameters": {"type": "object", "properties": {"query_str": {"type": "string"}}, "required": ["query_str"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_service_logs",
                    "description": "获取指定微服务的真实日志，排查报错堆栈",
                    "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}}, "required": ["service_name"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "restart_pod",
                    "description": "重启服务。注意：必须在完全确认符合SOP安全规范后才能调用！",
                    "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}}, "required": ["service_name"]}
                }
            }
        ]

    def run_diagnosis(self, alert_context, target_service):
        print("\n" + "🔥" * 60)
        print(f"🚨 [ReAct 引擎唤醒] 接收到高危告警: {alert_context}")
        
        relevant_sop = KNOWLEDGE_BASE_SOP.get(target_service, "当前服务暂无特定 SOP，请按通用排查逻辑进行。")
        
        system_prompt = f"""
        你是一个资深的云原生 AIOps 专家。请严格遵循 ReAct (Reasoning and Acting) 范式进行排障。
        
        【工作流规范 (ReAct)】：
        1. Thought (思考): 面对告警或工具返回的结果，先说明你的分析思路。
        2. Action (行动): 决定调用哪些工具收集证据（如查监控、看日志、或执行重启）。
        3. Observation (观察): 根据工具返回的结果进行下一轮分析。
        4. 不断循环上述步骤，直到你得出了确切的根因结论，或者故障已恢复。
        5. Final Answer (最终结论): 给出最终的诊断报告总结，并停止调用任何工具。
        
        【相关知识库/SOP 注入】：\n{relevant_sop}
        
        【强制红线】：
        - 严禁未经日志/监控证实直接盲目猜测！
        - 必须先收集足够的数据，再决定是否调用重启服务工具！
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请排查此告警：{alert_context}"}
        ]
        
        MAX_ITERATIONS = 15
        step = 0
        
        while step < MAX_ITERATIONS:
            step += 1
            print(f"\n🧠 [ReAct 迭代轮次 {step}] 正在深度推理...")
            
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=self.tools_schema,
                tool_choice="auto"  # 让大模型自主决定是否需要调用工具
            )
            
            response_message = response.choices[0].message
            messages.append(response_message) 
            
            # 💡 [Thought 阶段]：打印大模型的内心独白
            if response_message.content:
                print(f"💡 [Thought 思考]: {response_message.content}")

            # 🎯 [判定阶段]：如果大模型没有返回任何工具调用，说明它认为排查结束了！
            if not response_message.tool_calls:
                print("\n" + "✨" * 20)
                print("✅ [Final Answer 最终诊断报告]:")
                print(response_message.content)
                print("🔥" * 60 + "\n")
                break  # 完美退出 ReAct 循环！

            # 🛠️ [Action 阶段]：大模型决定调用工具
            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                print(f"⚙️  [Action 行动]: 决定调用工具 -> {function_name} {function_args}")
                
                # --- HITL 人机协同审批逻辑保持不变 ---
                if function_name == "restart_pod":
                    print("\n" + "⚠️" * 20)
                    print(f"🚨 警告：AI 申请执行高危动作：【重启服务 {function_args.get('service_name')}】！")
                    approval = input("👉 请管理员审核，是否批准执行？(输入 y 批准，其他拒绝): ")
                    
                    if approval.strip().lower() != 'y':
                        print("⛔ 管理员已拒绝该操作。")
                        tool_result = "Action REJECTED by human administrator."
                    else:
                        print("✅ 管理员已批准。")
                        tool_result = restart_pod(**function_args)
                else:
                    # 执行普通查询工具
                    tool_result = AVAILABLE_TOOLS[function_name](**function_args)
                
                # 🔬 [Observation 阶段]：将工具执行结果喂回给大模型
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": str(tool_result),
                })
                print(f"🔬 [Observation 观察]: 已获取 {function_name} 结果，反馈给大模型大脑...")
        
        # 安全退出检测
        if step >= MAX_ITERATIONS:
            print("\n⚠️ 达到最大安全思考轮次 (15轮)，强行终止排障任务，防止死循环。\n")

def fetch_prom_data(promql):
    """通用 Prometheus 数据拉取函数"""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': promql}, timeout=3)
        return resp.json().get('data', {}).get('result', [])
    except:
        return []

def scan_all_services_health():
    """全网五维扫描引擎：CPU、内存、重启次数、全局网络"""
    # 1. 查 CPU (核)
    cpu_data = fetch_prom_data('sum(rate(container_cpu_usage_seconds_total{namespace="default", pod!=""}[3m])) by (pod)')
    # 2. 查 内存 (MB)
    mem_data = fetch_prom_data('sum(container_memory_working_set_bytes{namespace="default", pod!=""}) by (pod) / 1024 / 1024')
    # 3. 查 崩溃重启次数
    restarts_data = fetch_prom_data('sum(changes(container_start_time_seconds{namespace="default", pod!=""}[15m])) by (pod)')
    # 4. 查 全局宿主机网络吞吐 (MB/s)
    net_data = fetch_prom_data('sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*"}[3m])) / 1024 / 1024')
    
    global_net_mb = float(net_data[0]['value'][1]) if net_data else 0.0

    # 聚合所有微服务的数据
    services_health = {}
    for item in cpu_data:
        pod_name = item['metric'].get('pod', 'unknown')
        svc_name = "-".join(pod_name.split("-")[:-2]) if "-" in pod_name else pod_name
        services_health[svc_name] = {'pod': pod_name, 'cpu': float(item['value'][1]), 'mem': 0.0, 'restarts': 0}

    for item in mem_data:
        pod_name = item['metric'].get('pod', 'unknown')
        svc_name = "-".join(pod_name.split("-")[:-2]) if "-" in pod_name else pod_name
        if svc_name in services_health:
            services_health[svc_name]['mem'] = float(item['value'][1])

    for item in restarts_data:
        pod_name = item['metric'].get('pod', 'unknown')
        svc_name = "-".join(pod_name.split("-")[:-2]) if "-" in pod_name else pod_name
        if svc_name in services_health:
            services_health[svc_name]['restarts'] = int(item['value'][1])

    anomalies = []
    
    print(f"\n[{time.strftime('%H:%M:%S')}] 📡 雷达扫描完毕 | 全局网络流入: {global_net_mb:.2f} MB/s")
    print("=" * 75)
    print(f"{'状态':<3} | {'微服务名称':<20} | {'CPU(核)':<7} | {'内存(MB)':<8} | {'重启':<3} | {'诊断结论'}")
    print("-" * 75)
    
    # 排序：按 CPU 从高到低
    sorted_services = sorted(services_health.values(), key=lambda x: x['cpu'], reverse=True)
    
    for s in sorted_services:
        svc_name = "-".join(s['pod'].split("-")[:-2]) if "-" in s['pod'] else s['pod']
        cpu, mem, restarts = s['cpu'], s['mem'], s['restarts']
        
        status_icon = "🟢"
        diagnosis = "健康运行"
        
        # 🚨 动态多维异常检测逻辑
        if cpu > 0.5:
            status_icon, diagnosis = "🔴", "CPU 过载突增!"
            anomalies.append((svc_name, s['pod'], f"CPU 飙升至 {cpu:.2f} 核"))
        elif mem > 200.0:  # 内存大于 200MB 报警
            status_icon, diagnosis = "🔴", "内存泄漏警告!"
            anomalies.append((svc_name, s['pod'], f"内存暴涨至 {mem:.2f} MB"))
        elif restarts > 0:
            status_icon, diagnosis = "🔴", "进程崩溃重启!"
            anomalies.append((svc_name, s['pod'], f"异常重启了 {restarts} 次"))
        elif cpu > 0.1:
            status_icon, diagnosis = "🟡", "请求活跃"

        print(f" {status_icon}   | {svc_name:<25} | {cpu:<8.3f} | {mem:<10.1f} | {restarts:<5} | {diagnosis}")
            
    print("=" * 75)
    return anomalies

def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "")

    agent = AIOpsAgentPro(api_key=api_key, base_url=base_url)
    
    print("\n" + "=" * 20)
    print("🛡️  五维立体 AIOps 智能雷达已上线！")
    print("📡  正在全域监听 [CPU | 内存 | 网络吞吐 | 崩溃频次]...")
    print("=" * 20 + "\n")
    
    while True:
        anomalies = scan_all_services_health()
        
        if anomalies:
            # 取第一个严重故障进行处理
            svc_name, pod_name, reason = anomalies[0]
            alert_msg = f"🚨 雷达告警：[{svc_name}] 发生致命异常！具体表现为：{reason}。疑似发生网络拥塞雪崩或内存溢出！"
            
            agent.run_diagnosis(alert_context=alert_msg, target_service=svc_name)
            
            print("⏳ 故障处理完毕，进入 60 秒系统冷却期，防止告警风暴...")
            time.sleep(60) 
        else:
            time.sleep(10)

if __name__ == "__main__":
    main()
