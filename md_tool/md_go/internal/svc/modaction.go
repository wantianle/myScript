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
	s.log.Info("正在对 [%s] %s 执行 %s...", soc, mod, action)

	cmd := fmt.Sprintf("sudo supervisorctl %s %s", action, mod)
	var out ExecOut
	// Stdin isolation for soc2 (`</dev/null`, md.sh:807) is handled by the
	// exec layer: sshx.Exec treats a nil Stdin as /dev/null (ssh -n), so a
	// batched stdin stream is never consumed by the remote command.
	out, _ = sh.Exec(ctx, cmd)

	sleepCtx(ctx)

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
	soc, err := resolveModuleSOC(socArg)
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
		return fmt.Errorf("%d 个模块操作失败", fail)
	}
	return nil
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

// resolveModuleSOC maps socArg (soc1|1|soc2|2) to a module target (md.sh:838-842).
func resolveModuleSOC(socArg string) (string, error) {
	switch socArg {
	case "soc1", "1":
		return "soc1", nil
	case "soc2", "2":
		return "soc2", nil
	default:
		return "", fmt.Errorf("无效 SOC: %s (1=soc1, 2=soc2)", socArg)
	}
}
