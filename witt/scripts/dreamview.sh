docker exec -d "$CONTAINER" bash -c 'sudo -E bash /mdrive/mdrive/scripts/cmd.sh && sudo supervisorctl start Dreamview'
log_info "Supervisor status 和 Dreamview 已启动..."

# docker exec -d "$CONTAINER" bash -c "/mdrive/mdrive/bin/mdrive_multiviz >/dev/null 2>&1"

# 打开浏览器
nohup xdg-open http://localhost:9001 >/dev/null 2>&1 &
sleep 1
nohup xdg-open http://localhost:8888 >/dev/null 2>&1 &
