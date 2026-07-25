#!/bin/bash
cd /root/Iatreon
git pull origin main
docker compose down
docker compose up -d --build