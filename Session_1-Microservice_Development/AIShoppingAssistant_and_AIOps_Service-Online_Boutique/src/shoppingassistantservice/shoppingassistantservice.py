import grpc
from concurrent import futures
import json
import faiss
import numpy as np  # 新增：用于处理云端返回的向量数组
from openai import OpenAI
import demo_pb2
import demo_pb2_grpc

# ================= 配置中心 =================
DEEPSEEK_API_KEY = "sk-2cecfb91a36c413db3eb4dadf6fc0c9c"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

QWEN_API_KEY = "sk-abe3f00477f34b77bc572775460516ed"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_VISION_MODEL = "qwen3.7-plus"
QWEN_EMBEDDING_MODEL = "text-embedding-v3" # 新增：阿里百炼通用文本向量模型

class ShoppingAssistantService(demo_pb2_grpc.ShoppingAssistantServiceServicer):
    def __init__(self):
        print("🚀 初始化异构多模态 AI 导购大脑 (纯 API 轻量版)...", flush=True)
        self.deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        self.qwen_client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        
        print("✅ 客户端初始化完成！正在读取本地商品库 products.json...", flush=True)
        with open('products.json', 'r', encoding='utf-8') as f:
            self.products = json.load(f)['products']
        
        print(f"⏳ 正在调用阿里百炼 API ({QWEN_EMBEDDING_MODEL}) 为商品库生成向量 (分批处理)...", flush=True)
        texts = [f"{p['name']} {p['description']} {' '.join(p['categories'])}" for p in self.products]
        
        # 新增：定义批量大小，阿里的限制是 10
        BATCH_SIZE = 10
        all_embeddings_list = []
        
        # 将 texts 列表按照 BATCH_SIZE 进行切片，分批发送请求
        for i in range(0, len(texts), BATCH_SIZE):
            batch_texts = texts[i:i+BATCH_SIZE]
            
            # 打印一下进度，避免以为卡住了
            print(f"   -> 正在处理第 {i+1} 到 {min(i+BATCH_SIZE, len(texts))} 个商品...", flush=True)
            
            embed_response = self.qwen_client.embeddings.create(
                model=QWEN_EMBEDDING_MODEL,
                input=batch_texts
            )
            
            # 将这一批的向量结果添加到总列表中
            all_embeddings_list.extend([item.embedding for item in embed_response.data])
        
        # 将总列表转换为 FAISS 需要的 float32 numpy 数组
        embeddings_np = np.array(all_embeddings_list, dtype=np.float32)
        
        # 动态获取维度
        dimension = embeddings_np.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(embeddings_np)
        
        print(f"✅ FAISS 向量索引生成完毕 (共 {len(all_embeddings_list)} 条记录，维度 {dimension})，混合路由 AI 大脑准备就绪。", flush=True)

    def _analyze_image(self, base64_image):
        try:
            response = self.qwen_client.chat.completions.create(
                model=QWEN_VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"{base64_image}"}},
                            {"type": "text", "text": "请简短描述这张图片中适合作为礼物的物品及其风格特征，不超过100个字。"}
                        ]
                    }
                ],
                max_tokens=100
            )
            return response.choices[0].message.content
        except Exception as e:
            return "商品图片"

    def Chat(self, request, context):
        print(f"--- 进来了！请求类型: {type(request)} ---", flush=True)
        user_msg = request.user_message.strip()
        image_data = request.image_base64
        search_query = user_msg
        
        if image_data:
            image_description = self._analyze_image(image_data)
            search_query = f"{user_msg}。此外，寻找类似这种风格的商品：{image_description}" if user_msg else f"寻找类似这种风格的商品：{image_description}"
            if not user_msg:
                user_msg = "请帮我寻找与这张图片风格类似的商品。"

        # ================= 替换这一段 =================
        # 将用户的搜索词转化为向量
        query_response = self.qwen_client.embeddings.create(
            model=QWEN_EMBEDDING_MODEL,
            input=[search_query]
        )
        query_emb_np = np.array([query_response.data[0].embedding], dtype=np.float32)

        # 1. 在 FAISS 中扩大初始检索数量（比如先取出前 5 个候选）
        distances, indices = self.index.search(query_emb_np, k=5)
        
        # 💡 打印出来看看距离的具体数值，方便你后续微调阈值
        print(f"🧐 当前搜索词与前5名商品的距离: {distances[0]}", flush=True)

        # 2. 设定距离阈值 (对于 L2 距离，数值越小越相似)
        # 如果你发现推荐太严格（啥也不出），就把值调大 (例如 1.2, 1.5)
        # 如果你发现推荐太宽松（乱七八糟的也出），就把值调小 (例如 0.8, 0.9)
        DISTANCE_THRESHOLD = 1.0

        retrieved_products = []
        # 3. 遍历候选商品，只有距离小于等于阈值的才被选中
        for i, dist in enumerate(distances[0]):
            if dist <= DISTANCE_THRESHOLD:
                idx = indices[0][i]
                retrieved_products.append(self.products[idx])

        product_ids = [p['id'] for p in retrieved_products]
        # ==============================================

        context_str = "\n".join([f"- {p['name']}: {p['description']}" for p in retrieved_products])

        system_prompt = """你是一位 Online-Boutique 电商平台的金牌导购员，性格温和、亲密且充满热情。
        请仔细阅读系统为你检索出的【本地商品知识库】信息，为用户提供准确的购物建议，合理擅长使用各种亲切热情、直观的 emoji。

        【服务规范与红线】：
        1. 严格基于知识库：你只能推荐知识库中明确提供的商品，切勿凭空捏造任何商品名称、功能或价格！
        2. 缺货处理机制：如果系统匹配到的本地商品为空，或者检索出的商品与用户的需求完全不相关，请温和、诚实地告知用户目前暂无该商品。
        3. 缺货安抚话术：在告知没有商品后，请务必主动对用户说类似这样的话：“不过请您放心，我已经将您的这个心愿单悄悄记录下来啦，并反馈给我们的采购和商家团队加紧备货，希望能尽快为您奉上！”
        4. 灵活变通：如果在告知缺货并反馈备货之后，知识库里有稍微相关的替代品，可以顺便热情地问一句“虽然没有那个，但您要不要看看这款相似的宝贝呢？”。
        """

        user_prompt = f"用户的实时诉求是：'{user_msg}'\n\n系统匹配到的本地商品有：\n{context_str}"

        try:
            response = self.deepseek_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                extra_body={"thinking": {"type": "disabled"}}, 
                stream=True
            )
            
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield demo_pb2.ChatResponse(ai_reply=content, product_ids=[])
                    
            if product_ids:
                yield demo_pb2.ChatResponse(ai_reply="", product_ids=product_ids)
                
        except Exception as e:
            print(f"❌ DeepSeek 生成失败: {e}", flush=True)
            yield demo_pb2.ChatResponse(ai_reply="抱歉，我的大脑暂时开小差了。", product_ids=[])

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    demo_pb2_grpc.add_ShoppingAssistantServiceServicer_to_server(ShoppingAssistantService(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()