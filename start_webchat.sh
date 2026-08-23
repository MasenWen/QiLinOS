#!/usr/bin/env bash
# webchat 直连启动（监听 0.0.0.0 + token 鉴权）
export WEBCHAT_HOST=0.0.0.0
export WEBCHAT_TOKEN=$(cat /tmp/webchat_token.txt)
cd /home/kylin/work/projects/project_dev1
exec .venv/bin/python webchat.py 8080 >> webchat.log 2>&1
