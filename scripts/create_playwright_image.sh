#!/bin/bash
set -e

IMAGE_NAME="iatreon-playwright"
IMAGE_TAG="1.59.0-noble"

# Build the image using the Dockerfile in the docker/playwright-server directory
docker build -t ${IMAGE_NAME}:${IMAGE_TAG} -f docker/playwright-server/Dockerfile .

echo "Built ${IMAGE_NAME}:${IMAGE_TAG}"
