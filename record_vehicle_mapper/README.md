# record_vehicle_mapper

用于从 `L4_cases` 下的 `soc2` record 文件反查原始 record 路径，提取车号，并把 case record、raw record、version 文件里的 `mdrive_conf` 信息关联成 JSON。

默认路径：

- case record 根目录：`/media/pnc_team-planning_algo-driving/L4_cases`
- raw record 根目录 1：`/media/nas/00.raw`
- raw record 根目录 2：`/media/nas/04.mdrive3/01.road_test`
- 只扫描路径中包含 `soc2` 目录的 record
- record 文件名匹配：`YYYYMMDDHHMMSS.record.NNNNN.HHMMSS` 或追加 `.split`，例如 `20260403213546.record.00008.214340`、`20260403213546.record.00008.214340.split`
- raw 查找会取 record 文件名前 8 位日期，先查当天；当天找不到这个 record 时，再查次日。例如 `20260228140727.record.00003.141028` 会先查 `/media/nas/00.raw/20260228`，找不到才查 `/media/nas/00.raw/20260301`
- 搜索策略是先查 `/media/nas/00.raw/当天`，再查 `/media/nas/00.raw/次日`；两者都没找到的 record，才会 fallback 去 road test 查找
- road test fallback 会取 record 文件名前 4 位年份，例如 `20260228140727.record.00003.141028` 会去 `/media/nas/04.mdrive3/01.road_test/所有车号/2026` 下查找同名文件
- version 文件名优先级：`version.json`、`version.txt`

## 使用

```bash
cd /home/mini/dev/myScript/record_vehicle_mapper
python3 record_vehicle_mapper.py -o record_vehicle_map.json
```

指定路径：

```bash
python3 record_vehicle_mapper.py \
  --case-root /media/pnc_team-planning_algo-driving/L4_cases \
  --raw-root /media/nas/00.raw \
  --road-test-root /media/nas/04.mdrive3/01.road_test \
  --soc soc2 \
  -o record_vehicle_map.json
```

排除 `L4_cases` 下某个目录，例如不扫描 `odom数据包` 目录里的 record：

```bash
python3 record_vehicle_mapper.py --exclude-dir 'odom数据包' -o record_vehicle_map.json
```

排除多个目录时重复传参：

```bash
python3 record_vehicle_mapper.py \
  --exclude-dir 'odom数据包' \
  --exclude-dir '其他目录' \
  -o record_vehicle_map.json
```

只记录 version 文件路径，不解析 `mdrive_conf` 内容：

```bash
python3 record_vehicle_mapper.py --no-version-content -o record_vehicle_map.json
```

默认会在 stderr 打印进度，例如当前扫描的日期目录、已扫描目录数、已匹配数量。调大或调小进度打印间隔：

```bash
python3 record_vehicle_mapper.py --progress-interval 500 -o record_vehicle_map.json
```

关闭进度输出：

```bash
python3 record_vehicle_mapper.py --quiet -o record_vehicle_map.json
```

## 输出结构

输出 JSON 主要包含：

- `summary`：统计数量，包括匹配、未找到、重名歧义数量
- `vehicles`：按车号聚合后的结果
- `NotFound`：没有找到原始地址的 case record

每个车辆下的条目只保留必要字段：

- `case_record_path`
- `raw_record_path`
- `version_path`
- `version_info`
- `match_status`

`version_info` 只包含 `mdrive_conf` 行解析出来的结构化字段，例如：

```json
{
  "pakage": "mdrive_conf",
  "branch": "release/xxx",
  "version": "ECAR_HW4.4.3.1.release/xxx_30e1c650"
}
```

字段顺序为 `pakage`、`branch`、`version`。其中 `pakage` 来自第一列，`version` 来自第二列，`branch` 只有 `mdrive_conf` 行存在第三列时才会出现。

同一个 record 如果在 `/media/nas/00.raw` 已经找到，不会再去 road test 搜索这个 record。只有同一个搜索源内找到多个路径时，`match_status` 才会标为 `ambiguous`，这些匹配会分别出现在对应车号的 `vehicles` 列表里。

## 生成 config 目录

`prepare_case_configs.py` 读取上一步生成的 JSON，在每个 `case_record_path` 旁边创建同名 `.config` 目录：

```bash
python3 prepare_case_configs.py record_vehicle_map.json --dry-run
```

确认计划后执行：

```bash
python3 prepare_case_configs.py record_vehicle_map.json
```

它会做这些事：

- 从 `vehicles` 分组读取 `case_record_path`、`version_path`、`version_info`
- 在 `case_record_path.config` 下复制原始 `version.json` 或 `version.txt`，已存在时静默覆盖
- 优先使用 `version_info.branch` 作为 `~/dev/mdrive_conf` 里的 git 分支执行 `git switch`
- 如果缺少 `branch`，则从 `version_info.version` 第四个 `.` 后解析分支名：遇到 8 位 hash 时取 hash 前的部分，没有 hash 时取后续全部，例如 `release_260310_cca98d38` 解析为分支 `release_260310` 和提交 `cca98d38`，`xinzhou_1230` 解析为分支 `xinzhou_1230`
- 从 `version_info.version` 里取第一个 `.` 前的平台名，例如 `ECAR_HW4`
- 从 `version_info.version` 里查找 8 位提交 hash；找得到就用该历史提交，找不到就用切换后分支的 `HEAD`
- 根据 `version_path` 所属路径类型解析车号；支持 `00.raw`、`01.load_test`、`04.mdrive3/01.road_test`，解析不到时退回 JSON 的车辆 key
- 导出 `ECAR_HW4/vehicle_name/<车号>/vehicle_config.pb.txt` 到 `.config/vehicle_config.pb.txt`，已存在时静默覆盖

默认 mdrive_conf 仓库路径是 `~/dev/mdrive_conf`，可通过 `--repo` 指定。

默认会在 stderr 打印带颜色的进度，包括加载 JSON、任务数量、当前任务序号、车号、分支、ref、复制 version、git switch、git show 和写出外参。关闭进度输出可加 `--quiet`。

如果最终 `failed` 不为 0，脚本会打印 `failures` 明细，列出每个失败的 `stage`、`case_record_path`、车号、分支、ref 和错误信息，方便定位是哪条 record、哪个阶段失败。

如果 `git switch` 失败，脚本会立即终止，不再继续处理后续 record，并在终端打印失败位置，包括 `case_record_path`、分支名、车号、repo 路径和 git 的 stderr，方便排查。
