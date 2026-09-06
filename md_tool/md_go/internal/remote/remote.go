// Package remote implements the md.sh vmc::remote command: managing the
// ~/.md_remotes file that lists remote (branch/platform) targets for the vmc
// package manager. It is pure file I/O with no ssh or sudo dependency
// (md.sh:1245-1289).
//
// The file is a set of `name branch platform` rows (platform may be empty, in
// which case the row carries a trailing space). Duplicate detection matches
// the whole line including the trailing space, exactly like Bash's
// `grep -Fxq "$entry"`.
package remote

import (
	"fmt"
	"os"
	"strings"
)

// DefaultFile is the default path of the remotes file (~/.md_remotes).
const DefaultFile = "~/.md_remotes"

// Entry is one parsed `name branch platform` row.
type Entry struct {
	Name     string
	Branch   string
	Platform string
}

// String renders the row exactly as md.sh appends it: `name branch platform`
// with a trailing space when platform is empty (md.sh:1249-1252).
func (e Entry) String() string {
	if e.Platform == "" {
		return e.Name + " " + e.Branch + " "
	}
	return e.Name + " " + e.Branch + " " + e.Platform
}

// NameValid reports whether name can be used as a remote target (md.sh:1248:
// non-empty, no spaces, not starting with '#').
func NameValid(name string) bool {
	return name != "" && !strings.ContainsAny(name, " \t") && !strings.HasPrefix(name, "#")
}

// Add appends a `name branch platform` row to the file (md.sh md::remote add).
// branch defaults to "-" when empty. It returns erro=false when the exact row
// (including trailing space) already exists, in which case no write happens.
func Add(path, name, branch, platform string) (added bool, err error) {
	if !NameValid(name) {
		return false, fmt.Errorf("用法: md remote add <name> <branch|-> [platform]")
	}
	if branch == "" {
		branch = "-"
	}
	entry := Entry{Name: name, Branch: branch, Platform: platform}
	line := entry.String()

	if exists, err := lineExists(path, line); err != nil {
		return false, err
	} else if exists {
		return false, nil // md.sh logs "配置 [...] 已存在" warning; caller decides
	}
	if err := appendLine(path, line); err != nil {
		return false, err
	}
	return true, nil
}

// Del removes all rows whose name matches, mirroring md.sh's
// `awk '$1 != name'` (md.sh:1263-1278). It errors when the file does not exist
// or contains no matching name.
func Del(path, name string) (removed bool, err error) {
	if name == "" {
		return false, fmt.Errorf("请指定要删除的包名")
	}
	content, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return false, fmt.Errorf("远程配置中不存在包名: %s", name)
		}
		return false, err
	}
	lines := strings.Split(strings.TrimSuffix(string(content), "\n"), "\n")
	var kept []string
	found := false
	for _, line := range lines {
		fields := strings.SplitN(line, " ", 2)
		if len(fields) > 0 && fields[0] == name {
			found = true
			continue
		}
		kept = append(kept, line)
	}
	if !found {
		return false, fmt.Errorf("远程配置中不存在包名: %s", name)
	}
	if err := writeLines(path, kept); err != nil {
		return false, err
	}
	return true, nil
}

// List returns the file contents as lines, or nil when the file does not yet
// exist (md.sh remote list prints "暂无分支" in that case). Trailing blank
// lines are trimmed.
func List(path string) ([]string, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	lines := strings.Split(strings.TrimSuffix(string(content), "\n"), "\n")
	// Drop a single trailing empty row that a final newline produces.
	if len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	return lines, nil
}

// lineExists reports whether an exact line occurs in the file (grep -Fxq).
func lineExists(path, line string) (bool, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, err
	}
	for _, l := range strings.Split(string(content), "\n") {
		if l == line {
			return true, nil
		}
	}
	return false, nil
}

func appendLine(path, line string) error {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err := f.WriteString(line + "\n"); err != nil {
		return err
	}
	return nil
}

func writeLines(path string, lines []string) error {
	content := strings.Join(lines, "\n")
	if content != "" {
		content += "\n"
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(content), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
