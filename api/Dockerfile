# =============================================================================
# Horizon 极目楚天 · 后端镜像（FastAPI / uvicorn）
# 构建：在 api/ 目录执行  docker build -t horizon-api:local .
#      国内网络可加 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
#      需要 A 股数据源可加 --build-arg INSTALL_AKSHARE=1（镜像体积会明显增大）
# 运行：非 root（uid/gid 10001）
# =============================================================================
FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG INSTALL_AKSHARE=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

WORKDIR /app

# 仅安装运行期必需的系统包。
# psycopg[binary] 提供预编译 wheel，因此不需要 gcc / libpq-dev。
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

# --- 依赖层（先拷贝依赖清单，最大化利用构建缓存） ---------------------------
COPY requirements.txt ./
RUN pip install --index-url "${PIP_INDEX_URL}" -r requirements.txt \
 && pip install --index-url "${PIP_INDEX_URL}" \
        "psycopg[binary]>=3.2" \
        "celery>=5.4" \
        "redis>=5.0" \
 && if [ "${INSTALL_AKSHARE}" = "1" ]; then \
        pip install --index-url "${PIP_INDEX_URL}" akshare ; \
    fi

# --- 应用代码层 --------------------------------------------------------------
COPY app ./app

# --- 非 root 用户 ------------------------------------------------------------
RUN groupadd --system --gid 10001 horizon \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home \
            --shell /usr/sbin/nologin horizon \
 && chown -R 10001:10001 /app

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).getcode() == 200 else 1)"]

# --proxy-headers：位于 nginx 之后时按 X-Forwarded-* 还原客户端 IP 与协议。
# 若需要信任非环回来源的转发头，额外设置 FORWARDED_ALLOW_IPS（默认仅 127.0.0.1）。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]