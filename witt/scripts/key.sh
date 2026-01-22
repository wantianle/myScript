for port in {6171,6173,6175,6177,6179,6181}; do
    echo "正在给端口 $port 的车分发钥匙..."
    ssh-copy-id -o StrictHostKeyChecking=no -o ConnectTimeout=2 -p $port nvidia@ad.minieye.tech
done

function go() {
    local port=$1
    local mode=${2:-1}

    if [ -z "$port" ]; then
        echo "使用方法: go [端口] [1或2]"
        echo "示例: go 6171 (进SOC1) | go 6171 2 (进SOC2)"
        return 1
    fi

    if [[ "$mode" == "2" || "$mode" == "s2" ]]; then
        echo "穿透 SOC1 (端口:$port) ---> SOC2 (192.168.10.3)..."
        # -A 转发密钥，-t 开启交互终端
        ssh -A -t -p "$port" nvidia@ad.minieye.tech \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            "ssh nvidia@192.168.10.3 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    else
        echo "直连 SOC1 (端口:$port)..."
        ssh -p "$port" nvidia@ad.minieye.tech \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null
    fi
}
