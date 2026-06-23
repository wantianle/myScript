# 离线雷达重录脚本使用说明

本文说明根目录脚本 `mdrive/scripts/offline_lidar_rerecord.sh` 的用途和使用方式。

## 3 分钟上手

### 1. 启动开发容器

```bash
bash mdrive/docker/dev_start.sh
```

### 2. 执行离线重录

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap
```

### 3. 查看输出

默认输出文件：

```text
bag/20260530/record_20260530_162834_pointcloud.mcap
```

检查输出 topic：

```bash
docker exec mdrive_runtime_minieye bash -lc \
  'source /mdrive/mdrive/setup.sh && \
   mkit info -f /mdrive/bag/20260530/record_20260530_162834_pointcloud.mcap --channels'
```

预期至少包含：

```text
/sensor/pointcloud/lidar_fusion
/sensor/pointcloud/lidar_at128_front
```

### 4. 排查问题时保留临时日志

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap \
  --keep-temp
```

## 目的

原始包里只有 `/sensor/lidar/scan`，没有融合点云和单雷达点云时，可以用这个脚本自动完成下面这条链路：

1. 在开发容器内读取输入 MCAP
2. 回放 `/sensor/lidar/scan`
3. 启动 `mdrive_driver_lidar`，由 `SCAN -> PointCloud`
4. 用 `monitor record` 录制新的点云 MCAP

输出包会补出：

- `/sensor/pointcloud/lidar_fusion`
- `/sensor/pointcloud/lidar_at128_front`

同时会尽量保留输入包中其他已存在、且 `dds_flow.json` 支持录制的非点云 topic。

## 前提

- 在仓库根目录执行
- 开发容器已启动
- 默认容器名是 `mdrive_runtime_minieye`
- 输入包路径必须在当前项目目录下，因为脚本通过 `/mdrive` 挂载映射到容器
- 容器里不能已有正在运行的 `mdrive_driver_lidar`

进入容器的常规方式仍然是：

```bash
bash mdrive/docker/dev_into.sh
```

但这个脚本本身从宿主机直接执行，不需要你手工先进容器。

## 基本用法

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap
```

如果不指定输出路径，默认会在输入包同目录下生成：

```text
<原文件名>_pointcloud.mcap
```

例如：

```text
bag/20260530/record_20260530_162834_pointcloud.mcap
```

## 指定输出路径

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap \
  -o bag/20260530/record_20260530_162834_lidar_out.mcap
```

## 可选参数

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh --help
```

当前参数如下：

- `-i, --input`
  输入 MCAP，必须包含 `/sensor/lidar/scan`
- `-o, --output`
  输出 MCAP 路径
- `-n, --name`
  容器名，默认 `mdrive_runtime_minieye`
- `-r, --rate`
  `mkit play` 回放倍率，默认 `1.0`
- `-s, --start-offset`
  从输入包第几秒开始回放，默认 `0`
- `--recorder-warmup`
  启动 `monitor record` 后等待几秒再起 lidar driver，默认 `2`
- `--driver-warmup`
  启动 `mdrive_driver_lidar` 后等待几秒再开始回放，默认 `3`
- `--tail-wait`
  回放结束后再等几秒再停止 `monitor record`，默认 `2`
- `--keep-temp`
  保留容器内临时目录和日志，便于排查

## 脚本内部做了什么

脚本会在容器内自动执行这些步骤：

1. `mkit info` 读取输入包的通道列表和时长
2. 生成临时 `record_config.json`

生成规则：

- 删除输入包里的 `/sensor/lidar/scan`
- 删除输入包里已有的 pointcloud topic，避免重录旧点云
- 只保留 `dds_flow.json` 里支持录制的 topic
- 额外补上
  - `/sensor/pointcloud/lidar_fusion`
  - `/sensor/pointcloud/lidar_at128_front`

3. 启动 `monitor record`
4. 启动 `mdrive_driver_lidar --proto_config lidar_conf_scan.pb.txt`
5. 用 `mkit play` 回放输入包
6. 回放结束后等待 `tail-wait` 秒，再停止录制
7. 输出新的 MCAP

## 输出窗口说明

脚本当前策略不是“录固定时长”，而是“回放结束后再停录制”。

这样做的目的是让输出窗口尽量贴近输入窗口，而不是靠 `Duration - 1s` 或 `Duration - 2s` 这种静态裁剪。

但要注意：

- 输入是 `scan`
- 输出是 `pointcloud`
- 中间有组帧

所以输出时窗通常只能“尽量贴近”，不能保证和输入包的时间边界逐微秒一致。首尾差异通常来自：

- lidar driver 组帧预热
- 首尾不完整帧不出点云
- 回放结束后的尾部 flush

如果你需要的是严格文件到文件、完全复用原始时间戳边界的转换，那就不是这个脚本的目标，而需要做真正的离线转换工具。

## 验证结果

可用下面命令检查输出包：

```bash
docker exec mdrive_runtime_minieye bash -lc \
  'source /mdrive/mdrive/setup.sh && \
   mkit info -f /mdrive/bag/20260530/record_20260530_162834_pointcloud.mcap --channels'
```

预期至少能看到：

```text
/sensor/pointcloud/lidar_fusion
/sensor/pointcloud/lidar_at128_front
```

## 常见问题

### 1. 报 `container not running`

先启动容器，再执行脚本：

```bash
bash mdrive/docker/dev_start.sh
```

### 2. 报 `existing mdrive_driver_lidar process detected`

说明容器里已经有人手工起了 `mdrive_driver_lidar`，或上次异常退出后残留进程。

先在容器里清掉：

```bash
bash mdrive/docker/dev_into.sh
ps -ef | grep mdrive_driver_lidar
kill -INT <pid>
```

### 3. 想看详细日志

加 `--keep-temp`：

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap \
  --keep-temp
```

脚本结束时会打印容器内临时目录，例如：

```text
/tmp/offline_lidar_20260530_203733_1159377
```

里面有：

- `record.log`
- `driver.log`
- `play.log`
- `record_config.json`

### 4. 为什么输出里不保留旧 pointcloud topic

脚本会主动把输入包中已有的 pointcloud topic 从回放中排除，也不会把它们加到新的录制配置里。

这是为了避免：

- 旧点云和新点云同时存在
- 误把原始点云再次录进结果包
- topic 冲突后难以判断哪一路是新生成的

## 推荐命令

最常用的是：

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap
```

排查问题时用：

```bash
bash mdrive/scripts/offline_lidar_rerecord.sh \
  -i bag/20260530/record_20260530_162834.mcap \
  --keep-temp
```
