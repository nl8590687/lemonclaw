FROM ubuntu:26.04
ARG PYTHON_VERSION=3.14

ENV DEBIAN_FRONTEND=noninteractive

# 系统依赖 + uv（uv 只在构建期装依赖时使用）
RUN apt-get update && apt install -y --no-install-recommends curl tzdata language-pack-zh-hans \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -sf /root/.local/bin/uv /usr/local/bin/uv \
    && echo -e "\nzh_CN.UTF-8 UTF-8\n" >> /etc/locale.gen \
    && echo -e "\nexport LANG=zh_CN.UTF-8\nexport LANGUAGE=zh_CN:zh" >> /etc/profile \
    && rm -rf /var/lib/apt/lists/*

# 在项目目录下创建 uv 默认使用的那份 venv（/app/.venv），依赖全部在构建期装好
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN uv venv .venv --python ${PYTHON_VERSION} --seed \
    && uv pip install --python .venv/bin/python -r requirements.txt -c constraints.txt

COPY . /app

# 运行期：uv 直接复用 /app/.venv，--no-sync 保证不解析依赖、不下载、不重建
# 工作目录保持 /root，使数据目录仍为 /root/.lemonclaw，兼容现有挂载方式
WORKDIR /root
ENV PATH="/app/.venv/bin:/root/.local/bin:${PATH}" LANG=zh_CN.UTF-8 LANGUAGE=zh_CN:zh
# 时区：镜像只内置 tzdata 保证能力，默认 UTC（中性、无惊喜）；
# 部署时用 -e TZ=Asia/Shanghai 等覆盖，datetime.now() 会自动跟随
ENV TZ=UTC

CMD ["uv", "run", "--no-sync", "--project", "/app", "python", "/app/main.py"]

# docker build --rm -t lemonclaw:0.0.1 .
# 国内 +8 时区示例：
#   docker run -e TZ=Asia/Shanghai -v ./.lemonclaw:/root/.lemonclaw -p 8765:8765 -d --name lemonclaw lemonclaw:0.0.1
# 纯 Linux 宿主机跟随宿主时区（备选）：
#   docker run -v /etc/localtime:/etc/localtime:ro -v /etc/timezone:/etc/timezone:ro -v ./.lemonclaw:/root/.lemonclaw -p 8765:8765 -d --name lemonclaw lemonclaw:0.0.1
