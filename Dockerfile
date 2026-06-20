FROM ubuntu:26.04
COPY . /app
WORKDIR /root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt install -y curl language-pack-zh-hans && curl -LsSf https://astral.sh/uv/install.sh | sh  \
    && export PATH="/root/.local/bin:$PATH" && echo -e "\nzh_CN.UTF-8 UTF-8\n" >> /etc/locale.gen  \
    && echo -e "\nexport LANG=zh_CN.UTF-8\nexport LANGUAGE=zh_CN:zh" >> /etc/profile \
    && uv venv --python 3.14 &&uv pip install -r /app/requirements.txt

ENV PATH="/root/.local/bin:${PATH}" LANG=zh_CN.UTF-8 LANGUAGE=zh_CN:zh

CMD uv run /app/main.py

# docker build --rm -t lemonclaw:0.0.1 .
# docker run -v ./.lemonclaw:/app/.lemonclaw -p 8765:8765 -d --name lemonclaw lemonclaw:0.0.1
