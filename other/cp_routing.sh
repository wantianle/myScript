#! /usr/bin/bash
old_routing="./k281和游1老地图路线default_cycle_routing.txt"
new_routing="./k281和游1新图路线default_cycle_routing.txt"
you1_blacklist="./you1拉黑添加到routing_map最后面.txt"
k281_blacklist="./k281拉黑添加到routing_map最后面.txt"

echo ">>> 请更新完地图版本后使用，如果已集成 routing 和拉黑，那就无需使用此脚本！"
read -p "[1] 新地图 [2] 老地图: " map
read -p "[1] you1 [2] k281: " blacklist

if [[ $map == "1" ]]; then
    scp ./$new_routing soc1:/mdrive/mdrive_map/hdmap/default_cycle_routing.txt
else
    scp ./$old_routing soc1:/mdrive/mdrive_map/hdmap/default_cycle_routing.txt
fi

if [[ $blacklist == "1" ]]; then
    scp $you1_blacklist soc1:~/backlist_lane.txt
else
    scp $k281_blacklist soc1:~/backlist_lane.txt
fi
ssh -t soc1 "cat ~/backlist_lane.txt >> /mdrive/mdrive_map/hdmap/routing_map.txt && sudo chmod 775 -R /mdrive/mdrive_map/hdmap/"
