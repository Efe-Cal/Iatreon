FROM mcr.microsoft.com/playwright:v1.59.0-noble

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-noto-core \
        fonts-noto-cjk \
        fonts-freefont-ttf \
        fontconfig && \
    rm -rf /var/lib/apt/lists/* && \
    fc-cache -fv

CMD ["/bin/sh", "-c", "npx -y playwright@1.59.0 run-server --port 3000 --host 0.0.0.0"]
