FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim
WORKDIR /app

RUN sed -i "s/deb.debian.org/mirrors.cloud.aliyuncs.com/g" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true && apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .

# 把 grpcio-tools 装进容器
RUN pip install -i https://mirrors.cloud.aliyuncs.com/pypi/simple/ --trusted-host mirrors.cloud.aliyuncs.com --no-cache-dir grpcio-tools --extra-index-url https://mirrors.cloud.aliyuncs.com/pytorch-wheels/cpu -r requirements.txt
COPY . .

RUN python -m grpc_tools.protoc -I=./protos --python_out=. --grpc_python_out=. ./protos/demo.proto

EXPOSE 50051

# 开启实时日志
ENV PYTHONUNBUFFERED=1

CMD ["python", "shoppingassistantservice.py"]