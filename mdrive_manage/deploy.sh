#!/bin/bash
port=(6171 6173 6175 6177 6179 6181)
for p in "${port[@]}"; do
    scp -P $p ./md.sh nvidia@ad.minieye.tech:~/
    ssh -p $p nvidia@ad.minieye.tech '$HOME/md.sh init'
done
