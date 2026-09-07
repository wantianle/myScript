package svc

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"mdrive/md/internal/health"
)

// PreCheck runs the environment self-check, a faithful port of md.sh
// flow::pre (:1742-1863) restricted to the segments the G3.0 full-feature
// assessment kept: network (SOC2 + server), time sync, disk usage (root/cache/
// external) and disk read-only/data-root health, then service state. The
// device-ping and disk-fix segments were removed.
//
// It returns nil when the environment passes, and an error when anything is
// abnormal. The SOC2 network check is a hard gate (md.sh returns early on
// failure); the others accumulate `check_pass` and report at the end.
func (s *Svc) PreCheck(ctx context.Context) error {
	pass := true

	// --- Network SOC2 (hard gate, md.sh:1746-1753) ---
	s.log.Info("----------- Network Check -----------")
	soc2sh := s.shellOr("soc2", ctx)
	if soc2sh == nil {
		s.log.Err("请检查 soc2 供电/网线 (ping %s)，恢复后重试", s.cfg.SOC2IP)
		return fmt.Errorf("soc2 不可达")
	}
	defer soc2sh.Close()
	if _, err := soc2sh.Exec(ctx, "exit"); err != nil {
		s.log.Err("[网络] SOC2: 断开")
		s.log.Err("请检查 soc2 供电/网线 (ping %s)，恢复后重试", s.cfg.SOC2IP)
		return fmt.Errorf("soc2 不可达")
	}
	s.log.Info("[网络] SOC2: 正常")

	// --- Network server (soft fail, md.sh:1755-1761) ---
	local := s.shellOr("soc1", ctx)
	if local != nil {
		defer local.Close()
		if out, err := local.Exec(ctx, fmt.Sprintf("ping -c 1 -W 1 %s", s.cfg.ServerIP)); err != nil || out.Code != 0 {
			s.log.Info("[网络] %s: 断开", s.cfg.ServerIP)
			pass = false
		} else {
			s.log.Info("[网络] %s: 正常", s.cfg.ServerIP)
		}
	}

	// --- Time sync (md.sh:1802-1837); server time is a soft reference ---
	if !s.timeSyncCheck(ctx, local, soc2sh) {
		pass = false
	}

	// --- Disk check (md.sh:1839-1851), read-only; no fix trigger ---
	pass = s.diskCheck(ctx, local, soc2sh) && pass

	// --- Service state (md.sh:1852-1854) ---
	s.log.Info("--------------------------------------------")
	_ = s.Check(ctx, "soc1")
	_ = s.Check(ctx, "soc2")

	if !pass {
		s.log.Err("检测到环境异常 (网络/时间/硬盘)")
		return fmt.Errorf("环境自检未通过")
	}
	s.log.Ok("环境自检通过...")
	return nil
}

// timeSyncCheck compares SOC1 and SOC2 time against the server HTTP Date
// header. Returns true when the sync is normal (or the server is unreachable,
// in which case md.sh skips the judgment). Uses the health parsers indirectly
// via Shell output.
func (s *Svc) timeSyncCheck(ctx context.Context, local, soc2sh Shell) bool {
	ts1, t1str := s.localUnix(ctx, local)
	ts2, t2str := s.remoteUnix(ctx, soc2sh)

	// Server HTTP Date (soft reference; tsServer 0 == skip).
	tsServer := s.httpDateTS(ctx, local)

	s.log.Info("Server Time: %s", s.serverTimeStr(tsServer))
	s.log.Info("SOC1 Time:   %s", t1str)
	s.log.Info("SOC2 Time:   %s", t2str)

	if tsServer > 0 {
		d1 := abs(ts1 - tsServer)
		d2 := abs(ts2 - tsServer)
		if d1 <= 20 && d2 <= 20 {
			s.log.Info("时间同步状态: 正常 (误差 <= 20s)")
			return true
		}
		s.log.Info("时间同步状态: 异常! (SOC1误差:%ds, SOC2误差:%ds)", d1, d2)
		return false
	}
	return true // server unreachable => md.sh skips judgment
}

// diskCheck drives the read-only disk segment: Root /, Cache, external data
// disk usage, plus the read-only / data-root symlink probes from the
// downgraded diagnose. Returns true when all pass.
func (s *Svc) diskCheck(ctx context.Context, local, soc2sh Shell) bool {
	ok := true

	// Root + Cache usage (md.sh:1841-1842).
	if !s.diskUsage(ctx, local, "Root (/)", "/") {
		ok = false
	}
	if !s.diskUsage(ctx, local, "Cache (.cache)", s.cfg.MDriveCache) {
		ok = false
	}

	// External data disk: mount + content access + read-only probe + free-space
	// warning (downgraded diagnose, no 1-7 code, no fix).
	if !s.diskExternalCheck(ctx, local, soc2sh) {
		ok = false
	}

	return ok
}

// diskUsage reports one disk's used percent and warms when >= 85% (md.sh
// disk::usage:1094-1112). Returns true when normal.
func (s *Svc) diskUsage(ctx context.Context, sh Shell, name, path string) bool {
	if sh == nil {
		return true
	}
	out, err := sh.Exec(ctx, fmt.Sprintf("df -h %s 2>/dev/null", path))
	if err != nil {
		s.log.Err("[硬盘] %s: 读取失败", name)
		return false
	}
	pct, ok := health.RowUsedPct(out.Stdout)
	if !ok {
		s.log.Err("[硬盘] %s: 读取失败", name)
		return false
	}
	if pct >= 85 {
		s.log.Err("[硬盘] %s: 空间不足! (%d%%)", name, pct)
		return false
	}
	s.log.Info("[硬盘] %s: 正常 (%d%%)", name, pct)
	return true
}

// diskExternalCheck probes the external data disk (md.sh diagnose segments
// minus the repair/error codes). Returns true when healthy.
func (s *Svc) diskExternalCheck(ctx context.Context, local, soc2sh Shell) bool {
	ok := true

	// Mounted locally and on soc2 (md.sh:1142-1152).
	if local != nil {
		if out, err := local.Exec(ctx, fmt.Sprintf("mountpoint -q %s", s.cfg.MountRoot)); err != nil || out.Code != 0 {
			s.log.Err("硬盘未挂载 soc1:%s", s.cfg.MountRoot)
			ok = false
		}
	}
	if soc2sh != nil {
		if out, err := soc2sh.Exec(ctx, fmt.Sprintf("mountpoint -q %s", s.cfg.MountRoot)); err != nil || out.Code != 0 {
			s.log.Err("硬盘未挂载 soc2:%s", s.cfg.MountRoot)
			ok = false
		}
	}

	// Content access (md.sh:1159-1167).
	if local != nil {
		if out, err := local.Exec(ctx, fmt.Sprintf("timeout 2 stat -t %s/data >/dev/null 2>&1", s.cfg.MountRoot)); err != nil || out.Code != 0 {
			s.log.Err("挂载目录内容无法访问 %s", s.cfg.MountRoot)
			ok = false
		}
	}
	if soc2sh != nil {
		if out, err := soc2sh.Exec(ctx, fmt.Sprintf("timeout 2 stat -t %s/data >/dev/null 2>&1", s.cfg.MountRoot)); err != nil || out.Code != 0 {
			s.log.Err("挂载目录内容无法访问 %s", s.cfg.MountRoot)
			ok = false
		}
	}

	// Read-only degradation (md.sh:1169-1177).
	if local != nil {
		if out, err := local.Exec(ctx, "cat /proc/mounts"); err == nil && health.ReadOnly(out.Stdout, s.cfg.MountRoot) {
			s.log.Err("文件系统已降级为 [只读] soc1:%s", s.cfg.MountRoot)
			ok = false
		}
	}
	if soc2sh != nil {
		if out, err := soc2sh.Exec(ctx, "cat /proc/mounts"); err == nil && health.ReadOnly(out.Stdout, s.cfg.MountRoot) {
			s.log.Err("文件系统已降级为 [只读] soc2:%s", s.cfg.MountRoot)
			ok = false
		}
	}

	// External disk usage + cache free-space warning. md.sh flow::pre:1846
	// (`disk::usage "External (data)" $MOUNT_ROOT`) and diagnose:1186-1191
	// (`disk_free_gb "$MDRIVE_CACHE"`) both run df on the LOCAL soc1 — MDRIVE_CACHE
	// (/mdrive/.cache) is a soc1 path. Query local, not soc2.
	if ok && local != nil {
		if !s.diskUsage(ctx, local, "External (data)", s.cfg.MountRoot) {
			ok = false
		}
		s.localDiskFreeGBWarning(ctx, local)
	}

	return ok
}

// localDiskFreeGBWarning logs a cache-space warning when the LOCAL cache has
// < 5GB free (md.sh diagnose:1186-1191, downgraded to a warning).
func (s *Svc) localDiskFreeGBWarning(ctx context.Context, sh Shell) {
	if sh == nil {
		return
	}
	out, err := sh.Exec(ctx, fmt.Sprintf("df -BG %s 2>/dev/null", s.cfg.MDriveCache))
	if err != nil {
		return
	}
	gb, ok := health.RowFreeGB(out.Stdout)
	if ok && gb < 5 {
		s.log.Warn("%s 剩余空间不足 5GB (当前: %dGB)，过低会影响 OTA 版本升级", s.cfg.MDriveCache, gb)
	}
}

// localUnix returns (unix, human) for the soc1 clock.
func (s *Svc) localUnix(ctx context.Context, sh Shell) (int64, string) {
	if sh == nil {
		return 0, ""
	}
	out, _ := sh.Exec(ctx, "date +%s")
	ts, _ := strconv.ParseInt(strings.TrimSpace(out.Stdout), 10, 64)
	out2, _ := sh.Exec(ctx, "date +'%Y-%m-%d %H:%M:%S'")
	return ts, strings.TrimSpace(out2.Stdout)
}

// remoteUnix returns (unix, human) for the soc2 clock.
func (s *Svc) remoteUnix(ctx context.Context, sh Shell) (int64, string) {
	if sh == nil {
		return 0, ""
	}
	out, _ := sh.Exec(ctx, "date +%s")
	ts, _ := strconv.ParseInt(strings.TrimSpace(out.Stdout), 10, 64)
	out2, _ := sh.Exec(ctx, "date +'%Y-%m-%d %H:%M:%S'")
	return ts, strings.TrimSpace(out2.Stdout)
}

// httpDateTS fetches the server HTTP Date header as a unix timestamp, or 0
// when unreachable (md.sh:1811-1822 skips time sync then).
func (s *Svc) httpDateTS(ctx context.Context, sh Shell) int64 {
	if sh == nil {
		return 0
	}
	out, err := sh.Exec(ctx, fmt.Sprintf("curl -Is --connect-timeout 2 %s | grep -i '^Date:' | cut -d' ' -f2-7 | tr -d '\\r'", s.cfg.ServerIP))
	if err != nil {
		return 0
	}
	dateStr := strings.TrimSpace(out.Stdout)
	if dateStr == "" {
		return 0
	}
	// Use `date -d` on the remote side to normalize to epoch (the Bash tool
	// calls date -d "$http_date" +%s). This needs date + many formats, so we
	// run it through the shell rather than parse in Go.
	res, err := sh.Exec(ctx, fmt.Sprintf("date -d '%s' +%%s 2>/dev/null", dateStr))
	if err != nil {
		return 0
	}
	ts, _ := strconv.ParseInt(strings.TrimSpace(res.Stdout), 10, 64)
	return ts
}

// serverTimeStr renders the server time for display; "" when ts==0.
func (s *Svc) serverTimeStr(ts int64) string {
	if ts == 0 {
		return "获取失败"
	}
	return fmt.Sprintf("%s", timeFromUnix(ts))
}

func abs(n int64) int64 {
	if n < 0 {
		return -n
	}
	return n
}

// timeFromUnix is a tiny helper so the display string is deterministic.
var timeFromUnix = func(ts int64) string {
	return strconv.FormatInt(ts, 10) // seconds since epoch; caller may want HH:MM:SS later
}
