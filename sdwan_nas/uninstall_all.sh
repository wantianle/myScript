#!/bin/bash

if [[ $EUID -ne 0 ]]; then
   echo "请使用 sudo 运行"
   exit 1
fi

remove_nas() {
    systemctl stop nasmount 2>/dev/null
    systemctl disable nasmount 2>/dev/null
    rm -f /etc/systemd/system/nasmount.service
    rm -f /usr/local/bin/nasmount_helper.sh
    umount -l /media/nas
    read -p "是否删除 nas 的凭证文件 /etc/creds/nas.cred? (y/n): " del_conf
    [[ "$del_conf" == "y" ]] && rm -rf /etc/creds
}

remove_sdwan() {
    systemctl stop sdwan 2>/dev/null
    systemctl disable sdwan 2>/dev/null
    ip link delete iwan1
    rm -f /etc/systemd/system/sdwan.service
    rm -f /usr/local/bin/sdwan_helper.sh
    rm -f /usr/local/bin/sdwand
    read -p "是否删除 sdwan 的配置文件 /etc/sdwan/iwan.conf? (y/n): " del_conf
    [[ "$del_conf" == "y" ]] && rm -rf /etc/sdwan
}

read -p "卸载 0.全部删除 / 1.sdwan / 2.nas ? (0/1/2): " del_service
echo "正在停止并删除服务..."
if [[ "$del_service" == "1" ]]; then
    remove_sdwan
elif [[ "$del_service" == "2" ]]; then
    remove_nas
elif [[ "$del_service" == "0" ]]; then
    remove_sdwan
    remove_nas
else
    echo "无效选项，退出。"
    exit 1
fi
systemctl daemon-reload
echo "卸载完成！所有后台进程已停止。"
exit 0
