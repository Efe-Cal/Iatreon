#!/bin/bash
set -e

IMAGE_NAME="iatreon-playwright"
IMAGE_TAG="1.59.0-noble"
CONTAINER_NAME="iatreon-playwright-server"
PLAYWRIGHT_PORT=3000

# Remove existing container if it exists
docker rm -f ${CONTAINER_NAME} >/dev/null 2>&1 || true

# Run the container
docker run \
  --name ${CONTAINER_NAME} \
  --rm \
  --detach \
  --init \
  --ipc=host \
  --add-host=hostmachine:host-gateway \
  --publish ${PLAYWRIGHT_PORT}:3000 \
  --workdir /home/pwuser \
  --user pwuser \
  ${IMAGE_NAME}:${IMAGE_TAG}

echo "Playwright server is starting on ws://127.0.0.1:${PLAYWRIGHT_PORT}/"
echo "If needed, set PLAYWRIGHT_WS_ENDPOINT=ws://127.0.0.1:${PLAYWRIGHT_PORT}/"
