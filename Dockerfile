FROM ubuntu:26.04
COPY . /app
WORKDIR /root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt install -y curl tzdata language-pack-zh-hans && curl -LsSf https://astral.sh/uv/install.sh | sh  \
    && export PATH="/root/.local/bin:$PATH" && echo -e "\nzh_CN.UTF-8 UTF-8\n" >> /etc/locale.gen  \
    && echo -e "\nexport LANG=zh_CN.UTF-8\nexport LANGUAGE=zh_CN:zh" >> /etc/profile \
    && uv venv --python 3.14 &&uv pip install -r /app/requirements.txt

ENV PATH="/root/.local/bin:${PATH}" LANG=zh_CN.UTF-8 LANGUAGE=zh_CN:zh
# 时区：镜像只内置 tzdata 保证能力，默认 UTC（中性、无惊喜）；
# 部署时用 -e TZ=Asia/Shanghai 等覆盖，datetime.now() 会自动跟随
ENV TZ=UTC

CMD uv run /app/main.py

# docker build --rm -t lemonclaw:0.0.1 .
# 国内 +8 时区示例：
#   docker run -e TZ=Asia/Shanghai -v ./.lemonclaw:/root/.lemonclaw -p 8765:8765 -d --name lemonclaw lemonclaw:0.0.1
# 纯 Linux 宿主机跟随宿主时区（备选）：
#   docker run -v /etc/localtime:/etc/localtime:ro -v /etc/timezone:/etc/timezone:ro -v ./.lemonclaw:/root/.lemonclaw -p 8765:8765 -d --name lemonclaw lemonclaw:0.0.1
