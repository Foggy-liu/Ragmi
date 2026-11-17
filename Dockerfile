FROM python:3.11-slim

WORKDIR /app

# ⚠️ 镜像源：默认走阿里云。
#    实测本机网络访问官方源会卡死 —— apt 拉 http://deb.debian.org 的 Packages 时
#    下载完 9.6MB 就无响应（挂住 18 分钟），pip 拉 files.pythonhosted.org 同样慢到超时。
#    阿里云源实测可用（apt update 53s / pip 单个 17MB wheel 58s）。
#    网络通畅时可以覆盖：--build-arg APT_MIRROR=... --build-arg PIP_INDEX_URL=...
ARG APT_MIRROR=https://mirrors.aliyun.com/debian
ARG APT_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# ⚠️ 系统库不是可有可无的：
#   libgl1 / libglib2.0-0 —— opencv-python 在 slim 镜像里 import cv2 会报
#                             "libGL.so.1: cannot open shared object file"，
#                             而 utils/docs/process/pdf_txt.py 在 **模块导入期** 就 import cv2
#                             → main.py 导入链 api_file → txt_main → pdf_txt → cv2
#                             → 缺这两个库整个 API 容器起不来
#   tesseract-ocr + chi-sim —— pytesseract 只提供 Python 封装，真正的 OCR 二进制要系统装；
#                             缺了 PDF 的 OCR 兜底路径直接返回"提取失败"
RUN set -eux; \
    sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g; s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
        tesseract-ocr-chi-sim; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# pip 缓存挂载（BuildKit cache mount）：wheel 留在构建缓存里，
# 改 requirements.txt 后重建不用重新下载几百 MB —— 镜像里也不会留下缓存。
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=300 -i "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
