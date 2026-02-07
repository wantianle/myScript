#!/bin/bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y terminator vim
sudo update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator /usr/bin/terminator 100
sudo update-alternatives --config x-terminal-emulator
sudo apt install peek -y
sudo apt install filezilla -y
sudo apt install ./todesk*.deb  -y
sudo apt install ./sougoupinyin*.deb  -y
sudo apt install ./Fershu*.deb  -y
sudo apt install ./WeChat*.deb  -y
sudo apt install ./wps*.deb  -y
sudo apt install ./chrome*.deb  -y
sudo timedatectl set-ntp true
gsettings set org.gnome.desktop.interface clock-show-seconds true

sudo apt install -y openssh-server cifs-utils && sudo systemctl enable --now ssh

# 安装curl
sudo apt install curl
# 配置阿里云镜像源公钥
sudo curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | sudo apt-key add -
# 添加阿里云镜像源
sudo add-apt-repository "deb [arch=amd64] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable"
# 安装docker社区版
sudo apt install -y docker-ce

sudo usermod -aG docker mini
sudo reboot now

docker login gcr.minieye.tech
