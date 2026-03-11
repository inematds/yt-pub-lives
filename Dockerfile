FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp
RUN pip install --no-cache-dir yt-dlp

# Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App
COPY dashboard/ /app/dashboard/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*

# Directories
RUN mkdir -p /data/lives /config

# ENV defaults
ENV GWS_CONFIG_DIR=/config
ENV LIVES_DIR=/data/lives
ENV PYTHONUNBUFFERED=1

WORKDIR /app

EXPOSE 8090

CMD ["python3", "dashboard/server.py", "8090"]
