cat << 'EOF' > /home/nvidia/check_network.sh
#!/bin/bash

TARGET_IP="192.168.21.10"
LOG_FILE="/home/nvidia/ping_report.log"

echo "开始监控 $TARGET_IP ..." >> $LOG_FILE
while true
do
    if ping -c 100 -i 0.2 -W 1 $TARGET_IP > /dev/null; then
        :
    else
        echo "$(date): 警告！$TARGET_IP 丢包或连接中断" >> $LOG_FILE
    fi
    sleep 1
done
EOF
