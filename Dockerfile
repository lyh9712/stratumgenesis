# =============================================================================
# StratumGenesis v0.3 · 实验原型镜像（线④：部署与分发）
# =============================================================================
# ⚠️ 绑定地址红线（务必先读 DEPLOY.md §2）
#   server.py 目前硬编码监听 127.0.0.1:28417。server.py 是线①的独占文件，
#   本镜像【不修改它】。因此容器内只有环回地址可达 —— EXPOSE 28417 只是文档
#   声明，不会让宿主机或外部访问到服务。
#   想在容器外访问，必须额外做一层转发（见 DEPLOY.md §2 的四种做法与风险），
#   或等线①把监听地址改成可配置后再重建镜像。
# =============================================================================

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 全量复制：若后续补上 .dockerignore，可改回「先 COPY requirements.txt 再 COPY .」
# 的缓存分层写法；当前一次性复制，避免通配符 COPY 在无匹配时构建失败。
COPY . .

# 依赖安装：requirements.txt 已存在（ecdsa==0.19.2）时按文件装；
# 若部署者用的是精简/旧检出（无该文件），退回安装唯一第三方依赖，
# 保证镜像在任何检出状态下都能构建成功。
RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        pip install --no-cache-dir ecdsa; \
    fi

# 仓库内的 data/chain_v1.json 是【旧版 chain-v1 格式样本】且含明文私钥，
# 已被 .gitignore 排除。若从本地工作目录（而非干净检出）构建，它会被 COPY 进来，
# 导致 server.py 启动时因版本不匹配直接退出。这里在镜像内移除并建空目录，
# 让服务以「创世 + 预沉积演示地层」启动；真实数据请用卷挂载。
RUN rm -rf /app/data && mkdir -p /app/data

# 链数据落盘位置（挂卷即可持久化；不挂则容器销毁后链数据丢失）
VOLUME ["/app/data"]

# 仅文档性声明：实际可达性取决于 §2 的转发方案
EXPOSE 28417

# 容器内自检：GET / 返回 index.html 即视为存活（server.py 无 /health 端点）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:28417/', timeout=4)" || exit 1

CMD ["python", "server.py"]
