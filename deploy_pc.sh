#!/bin/bash

# 自动检测 Ubuntu 版本并配置阿里云镜像源
CODENAME=$(lsb_release -cs)

if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    # 新格式（Ubuntu 24.04+）
    sudo tee /etc/apt/sources.list.d/ubuntu.sources << EOF
Types: deb
URIs: http://mirrors.aliyun.com/ubuntu/
Suites: ${CODENAME} ${CODENAME}-updates ${CODENAME}-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://mirrors.aliyun.com/ubuntu/
Suites: ${CODENAME}-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
else
    # 传统格式（Ubuntu 24.04 以下或手动保留的配置）
    sudo tee /etc/apt/sources.list << EOF
deb http://mirrors.aliyun.com/ubuntu/ ${CODENAME} main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ ${CODENAME}-updates main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ ${CODENAME}-backports main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ ${CODENAME}-security main restricted universe multiverse
EOF
fi
sudo apt update && sudo apt upgrade -y
