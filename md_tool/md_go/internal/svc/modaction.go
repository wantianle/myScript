package svc

import (
	"context"
	"fmt"
	"strings"
)

// RunModuleAction runs a supervisorctl action on one module of one soc
// (md.sh svc::_run_module_action :801-818). soc1 runs locally; soc2 over ssh
// with stdin isolated (`</dev/null`, md.sh:807). It returns the supervisorctl
// exit code after a 1s settle (md.sh:809 `sleep 1`).
func (s *Svc) RunModuleAction(ctx context.Context, soc, mod, action string) error {
	sh := s.shellOr(soc, ctx)
	if sh == nil {
		return fmt.Errorf("[%s] 无法建立连接", soc)
	}
	defer sh.Close()
	s.log.Info("正在对 [%s] %s 执行 %s...", soc, mod, action)

	cmd := fmt.Sprintf("sudo supervisorctl %s %s", action, mod)
	// Stdin isolation for soc2 (`</dev/null`, md.sh:807) is handled by the
	// exec layer: sshx.Exec treats a nil Stdin as /dev/null (ssh -n), so a
	// batched stdin stream is never consumed by the remote command.
	out, err := sh.Exec(ctx, cmd)

	sleepCtx(ctx)

	// A transport-layer failure (mid-stream disconnect or the exec deadline)
	// surfaces as err with Code==0 — never trust Code alone. The Bash version
	// treats a dropped SSH connection as rc==255 (md.sh:812-813), so map any
	// exec error here onto that same "SSH 连接错误" path instead of falsely
	// reporting success.
	if err != nil {
		s.log.Err("[%s] %s %s 失败: soc2 SSH 连接错误 (%v)", soc, mod, action, err)
		return fmt.Errorf("[%s] %s %s SSH 连接错误", soc, mod, action)
	}

	rc := out.Code
	switch {
	case rc == 0:
		s.log.Ok("[%s] %s %s 成功", soc, mod, action)
		return nil
	case rc == 255:
		s.log.Err("[%s] %s %s 失败: soc2 SSH 连接错误", soc, mod, action)
	default:
		msg := out.Stderr
		if msg == "" {
			msg = out.Stdout
		}
		s.log.Err("[%s] %s %s 失败: %s", soc, mod, action, strings.TrimSpace(msg))
	}
	return fmt.Errorf("[%s] %s %s 退出码 %d", soc, mod, action, rc)
}

// ModCtl runs action on every module in mods, all on one soc (md.sh
// svc::mod_ctl :822-850). action is start/stop/restart; socArg is
// soc1|1|soc2|2. It returns the number of failures.
func (s *Svc) ModCtl(ctx context.Context, action, socArg string, mods []string) error {
	if action == "" || socArg == "" || len(mods) == 0 {
		return fmt.Errorf("用法: md m <start|stop|restart> <1(soc1)|2(soc2)> <模块名...>")
	}
	switch action {
	case "start", "stop", "restart":
	default:
		return fmt.Errorf("无效操作: %s (仅支持 start/stop/restart)", action)
	}
	soc, err := ResolveSOC(socArg, "", true)
	if err != nil {
		return err
	}

	fail := 0
	for _, mod := range mods {
		if err := s.RunModuleAction(ctx, soc, mod, action); err != nil {
			fail++
		}
	}
	if fail > 0 {
		// Bash svc::mod_ctl returns the failure count N as the exit code
		// (md.sh:849-850), so a wrapper script can distinguish partial failure.
		return &ModuleBatchError{Count: fail}
	}
	return nil
}

// ModuleBatchError reports how many modules failed in a batch action. The CLI
// uses Count as the process exit code (mirroring md.sh), so a script can
// distinguish "all ok" (0) from "N failed" (N).
type ModuleBatchError struct{ Count int }

func (e *ModuleBatchError) Error() string {
	return fmt.Sprintf("%d 个模块操作失败", e.Count)
}

// HandleSelectedRow parses one ANSI-stripped selected row and dispatches the
// action (md.sh svc::mod_handler :886-908). It returns the resulting error, or
// nil when the action was a log-open (which returns no error but emits the
// log-view command via the callback).
func (s *Svc) HandleSelectedRow(ctx context.Context, rawLine, action string, openLog func(soc, mod, logType string) error) error {
	line := strings.TrimSpace(StripANSI(rawLine))
	fields := strings.Fields(line)
	if len(fields) < 2 {
		return fmt.Errorf("无法解析模块行: %q", rawLine)
	}
	soc := strings.Trim(fields[0], "[]")
	mod := fields[1]
	if soc == "" || mod == "" {
		return fmt.Errorf("无法解析模块行: %q", rawLine)
	}

	switch action {
	case "glog", "sv":
		if openLog != nil {
			return openLog(soc, mod, action)
		}
		return nil
	case "start", "stop", "restart":
		return s.RunModuleAction(ctx, soc, mod, action)
	default:
		return fmt.Errorf("未知动作: %s", action)
	}
}
