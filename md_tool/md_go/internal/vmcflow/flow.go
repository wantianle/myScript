package vmcflow

import (
	"context"
	"fmt"
	"strings"

	"mdrive/md/internal/svc"
	"mdrive/md/internal/vmc"
)

// Upgrader is the interactive response reader abstraction for the confirm
// prompts (md.sh's `read -r ans`). The CLI wires a real stdin-backed reader.
type Prompt func(prompt string) (string, error)

// Upgradable is one `pkg:lat_ver:branch:plat:cur_ver` item produced by
// check_updates (md.sh:1342).
type Upgradable struct {
	Pkg      string
	Latest   string
	Branch   string
	Platform string
	Current  string
}

// CheckUpdates scans ~/.md_remotes and reports per-package current/latest
// version status (vmc::check_updates :1326-1353). It returns the list of
// upgradable items (empty when up to date or the config file is missing).
func (v *VMC) CheckUpdates(ctx context.Context) ([]Upgradable, error) {
	if v.Cfg.RemotesPath == "" {
		return nil, fmt.Errorf("配置文件不存在，请先添加分支")
	}
	rows, err := v.remoteLines(ctx)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, nil
	}

	var upgradable []Upgradable
	v.Log.Info("----------------------------------")
	for _, r := range rows {
		if r.Name == "" || strings.HasPrefix(r.Name, "#") {
			continue
		}
		cur, _ := v.CurrentVersion(ctx, r.Name)
		lat, ok := v.LatestVersion(ctx, r.Name, r.Branch, r.Platform)
		if !ok {
			v.Log.Err("%-15s %s", r.Name, "未找到远程版本")
			continue
		}
		if cur == lat {
			v.Log.Info("%-15s %s (已最新)", r.Name, lat)
		} else {
			v.Log.Info("%-15s %s (可更新)", r.Name, lat)
		}
		upgradable = append(upgradable, Upgradable{
			Pkg: r.Name, Latest: lat, Branch: r.Branch,
			Platform: r.Platform, Current: cur,
		})
	}
	v.Log.Info("----------------------------------")
	return upgradable, nil
}

// UpgradePort is the decision input to Upgrade: the pre-check passed flag and
// the confirm response (md.sh:1415-1424).
type UpgradePort struct {
	PreCheckPassed bool
	Confirm        string // "y"/""/other per md.sh; "f" forces when precheck failed
}

// Upgrade runs the full upgrade flow (vmc::upgrade :1415-1502).
func (v *VMC) Upgrade(ctx context.Context, port UpgradePort) error {
	if port.PreCheckPassed {
		if !promptAccept(port.Confirm) {
			v.Log.Err("已取消升级")
			return nil
		}
	} else {
		if port.Confirm != "f" {
			v.Log.Err("已取消升级")
			return nil
		}
	}

	upgradable, err := v.CheckUpdates(ctx)
	if err != nil {
		return err
	}
	if len(upgradable) == 0 {
		v.Log.Ok("所有组件均已是最新，无需升级。")
		return nil
	}

	// Multi-branch selection: group by unique pkg, pick one version per pkg
	// (md.sh:1432-1472). Single-option packages are auto-accepted when newer.
	var queue []Upgradable
	for _, up := range v.dedupePkgs(upgradable) {
		options := v.optionsFor(upgradable, up.Pkg)
		if len(options) == 1 {
			if options[0].Latest != options[0].Current {
				queue = append(queue, options[0])
			}
			continue
		}
		// Multiple branches for this pkg: present a menu (md.sh:1449-1470). For
		// the Go migration the interactive pick is deferred to the CLI layer;
		// here we auto-pick the first non-installed option and log for the
		// operator to override later.
		v.Log.Info("发现 [%s] 存在多个分支配置，请选择目标版本:", up.Pkg)
		for i, o := range options {
			status := ""
			if o.Latest == o.Current {
				status = "(当前已安装)"
			}
			v.Log.Info("  [%d] 分支: %s | 版本: %s %s", i, o.Branch, o.Latest, status)
		}
		for _, o := range options {
			if o.Latest != o.Current {
				queue = append(queue, o)
				break
			}
		}
	}

	if len(queue) == 0 {
		v.Log.Warn("未选择任何安装项")
		return nil
	}

	// stop both, install each, restart.
	v.Log.Info("确定执行升级")
	_ = v.Svc.Manage(ctx, "stop", "soc1")
	_ = v.Svc.Manage(ctx, "stop", "soc2")

	failed := false
	for _, q := range queue {
		v.Log.Info("正在安装 [%s] %s ...", q.Pkg, q.Latest)
		if err := v.InstallPkg(ctx, q.Pkg, q.Latest); err != nil {
			v.Log.Err("[%s] 安装失败", q.Pkg)
			failed = true
		} else {
			v.Log.Ok("[%s] 安装成功", q.Pkg)
		}
	}

	if failed {
		v.Log.Err("存在安装失败项，已停止自动启动服务，请检查后手动处理")
		v.Log.Warn("执行 md start 恢复双端服务运行")
		return fmt.Errorf("存在安装失败项")
	}

	_, _, _ = v.vmcExec(ctx, "list")
	_ = v.Svc.Manage(ctx, "start", "soc1")
	_ = v.Svc.Manage(ctx, "start", "soc2")
	return nil
}

// Install runs the vi-editor version install flow (vmc::install :1506-1591).
// The edited input text is supplied by the caller (the CLI opens $EDITOR);
// targets are extracted the same way md.sh's _extract does.
func (v *VMC) Install(ctx context.Context, inputText string, port UpgradePort) error {
	if port.PreCheckPassed {
		if !promptAccept(port.Confirm) {
			v.Log.Warn("已取消升级")
			return nil
		}
	} else {
		if port.Confirm != "f" {
			v.Log.Warn("已取消升级")
			return nil
		}
	}

	targets := vmc.ParseEditText(inputText, vmc.DefaultVersionSpecs())
	if len(targets) == 0 {
		v.Log.Warn("未提取到任何可安装版本")
		return fmt.Errorf("未提取到任何可安装版本")
	}

	failed := false
	stopped := false
	installed := false
	for _, t := range targets {
		if t.Version == "" {
			v.Log.Warn("跳过包 [%s]: 未在输入中提取到版本号", t.Name)
			continue
		}
		v.Log.Info("正在安装 [%s] 版本: %s ...", t.Name, t.Version)
		installed = true
		if !stopped {
			_ = v.Svc.Manage(ctx, "stop", "soc1")
			_ = v.Svc.Manage(ctx, "stop", "soc2")
			stopped = true
		}
		if err := v.InstallPkg(ctx, t.Name, t.Version); err != nil {
			v.Log.Err("[%s] 安装失败", t.Name)
			failed = true
		} else {
			v.Log.Ok("[%s] 安装成功", t.Name)
		}
	}

	if !installed {
		return fmt.Errorf("未提取到任何可安装版本")
	}
	if failed {
		v.Log.Err("存在安装失败项，已停止自动启动服务，请检查后手动处理")
		v.Log.Warn("执行 md start 恢复双端服务运行")
		return fmt.Errorf("存在安装失败项")
	}

	_ = v.Svc.Manage(ctx, "start", "soc1")
	_ = v.Svc.Manage(ctx, "start", "soc2")
	return nil
}

// Finstall installs a specific pkg@version, optionally resolving the pkg from
// a version query when no pkg name is given (vmc::finstall :1598-1629).
func (v *VMC) Finstall(ctx context.Context, version, pkg string) error {
	if pkg == "" {
		recs, err := v.Fsearch(ctx, version)
		if err != nil {
			return err
		}
		pkg = vmc.SelectPackageByVersion(recs, version)
	}
	if pkg == "" {
		return fmt.Errorf("未找到适用于 Orin 平台的包，请检查版本是否正确！")
	}
	v.Log.Info("下载安装 [%s] %s...", pkg, version)
	if err := v.InstallPkg(ctx, pkg, version); err != nil {
		v.Log.Err("[%s] 安装失败", pkg)
		return err
	}
	v.Log.Ok("安装成功，手动重启服务或继续升级...")
	return nil
}

// Fsearch runs `vmc fsearch -v <version>` and parses the plain output.
func (v *VMC) Fsearch(ctx context.Context, version string) ([]vmc.Record, error) {
	out, _, err := v.vmcExec(ctx, "fsearch", "-v", version)
	if err != nil {
		return nil, err
	}
	return vmc.ParseSearch(out), nil
}

// Rollback searches historical versions and installs a selected one
// (vmc::rollback :1633-1736). exactCol is the package-name exact filter (from
// a remote-config branch or CLI "=name"), nameKw the fuzzy name substring.
// selectedPkg/selectedVer are resolved by the CLI's fzf/TUI picker; when they
// are empty this function performs the search and returns the candidate list.
func (v *VMC) Rollback(ctx context.Context, searchV, nameKw, exactCol string) ([]RollbackCandidate, error) {
	if searchV == "-" {
		searchV = ""
	}
	nameForSearch := nameKw
	if exactCol != "" {
		nameForSearch = exactCol
	}

	args := []string{"fsearch"}
	if nameForSearch != "" {
		args = append(args, "-n", nameForSearch)
	}
	if searchV != "" {
		args = append(args, "-v", searchV)
	}
	args = append(args, "-i", "100", "--verbose")
	out, _, err := v.vmcExec(ctx, args...)
	if err != nil {
		return nil, err
	}

	recs := vmc.ParseSearchVerbose(out)
	// Exact-column filter (md.sh:1702-1704).
	if exactCol != "" {
		recs = vmc.MatchPackage(recs, exactCol)
	}
	// Render to `time | ver | platform | name` rows (md.sh:1673-1698) and
	// sort descending by the version field.
	cands := renderCandidates(recs)
	if len(cands) == 0 {
		v.Log.Err("[ver:%s, name:%s] 未搜索到任何远程版本", unwrap(searchV), unwrap(nameForSearch))
		v.Log.Err("提示: 换更短版本关键字，或先用 md remote list 确认分支与包名")
		return nil, nil
	}
	return cands, nil
}

// RollbackCandidate is one rendered `time | ver | platform | name` row.
type RollbackCandidate struct {
	Time     string
	Version  string
	Platform string
	Name     string
}

// renderCandidates renders parsed records to display rows, sorted descending.
func renderCandidates(recs []vmc.Record) []RollbackCandidate {
	var out []RollbackCandidate
	for _, r := range recs {
		time := r.ReleaseTime
		out = append(out, RollbackCandidate{
			Time: time, Version: r.Version, Platform: r.Platform, Name: r.Name,
		})
	}
	// sort -r: descending by version string (md.sh:1698).
	for i := 0; i < len(out); i++ {
		for j := i + 1; j < len(out); j++ {
			if out[i].Version < out[j].Version {
				out[i], out[j] = out[j], out[i]
			}
		}
	}
	return out
}

// InstallRollback installs the user-selected candidate (md.sh:1721-1735).
func (v *VMC) InstallRollback(ctx context.Context, cand RollbackCandidate, clean func(context.Context) error) error {
	v.Log.Warn("确定回滚 [%s] 到版本: %s ?", cand.Name, cand.Version)
	_ = v.Svc.Manage(ctx, "stop", "soc1")
	_ = v.Svc.Manage(ctx, "stop", "soc2")
	if clean != nil {
		_ = clean(ctx)
	}
	if err := v.Finstall(ctx, cand.Version, cand.Name); err != nil {
		v.Log.Warn("回滚失败，服务已停止，执行 md start 恢复运行")
		return err
	}
	return nil
}

// dedupePkgs returns unique pkg names from upgradable items.
func (v *VMC) dedupePkgs(items []Upgradable) []Upgradable {
	seen := map[string]bool{}
	var out []Upgradable
	for _, it := range items {
		if !seen[it.Pkg] {
			seen[it.Pkg] = true
			out = append(out, it)
		}
	}
	return out
}

// optionsFor returns all upgradable items for a pkg.
func (v *VMC) optionsFor(items []Upgradable, pkg string) []Upgradable {
	var out []Upgradable
	for _, it := range items {
		if it.Pkg == pkg {
			out = append(out, it)
		}
	}
	return out
}

// promptAccept returns true for y/"" (md.sh `read -r -p`), false for n/N etc.
func promptAccept(response string) bool {
	return response != "n" && response != "N"
}

func unwrap(s string) string {
	if s == "" {
		return "*"
	}
	return s
}

// moduleSOC is a helper re-export so callers use the svc resolver for rollback
// soc args if needed. Kept minimal.
var _ = svc.ResolveSOCArg
