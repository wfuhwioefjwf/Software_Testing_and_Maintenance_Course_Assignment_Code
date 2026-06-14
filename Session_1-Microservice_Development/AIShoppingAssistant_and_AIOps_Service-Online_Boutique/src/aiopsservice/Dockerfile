FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.10-slim
WORKDIR /app

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list 2>/dev/null || true && \
    apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN curl -LO "https://mirrors.aliyun.com/kubernetes/release/v1.31.0/bin/linux/amd64/kubectl" \
    && chmod +x kubectl \
    && mv kubectl /usr/local/bin/

COPY requirements_agent.txt .
RUN pip install --no-cache-dir -r requirements_agent.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY aiops_agent.py .

ENV PYTHONUNBUFFERED=1
CMD ["python", "aiops_agent.py"]