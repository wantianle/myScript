package export

import (
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
)

// ReverseTunnelPorts detects the reverse-ssh tunnel ports listening on the
// vehicle and owned by the current process tree (md.sh
// sys::_current_reverse_tunnel_ports :378-395). It walks the process tree from
// the current PID up to init, then scans `ss -H -tlnp` for listening ports
// bound by any ancestor, returning them de-duplicated and ascending.
//
// On a machine without `ss` it returns nil (the Bash version also returns 0).
func ReverseTunnelPorts() []string {
	if _, err := exec.LookPath("ss"); err != nil {
		return nil
	}
	pids := currentSessionPids()
	if len(pids) == 0 {
		return nil
	}
	out, err := exec.Command("ss", "-H", "-tlnp").Output()
	if err != nil {
		return nil
	}
	seen := map[string]bool{}
	var ports []string
	for _, line := range strings.Split(string(out), "\n") {
		for _, pid := range pids {
			if !strings.Contains(line, "pid="+pid+",") {
				continue
			}
			fields := strings.Fields(line)
			if len(fields) < 4 {
				break
			}
			port := portFromAddr(fields[3])
			if port != "" && !seen[port] {
				seen[port] = true
				ports = append(ports, port)
			}
			break
		}
	}
	sort.Slice(ports, func(i, j int) bool {
		pi, _ := strconv.Atoi(ports[i])
		pj, _ := strconv.Atoi(ports[j])
		return pi < pj
	})
	return ports
}

// portFromAddr extracts the numeric port from an ss local-address field
// (e.g. "[::]:2222", "0.0.0.0:22", "127.0.0.1:12345").
func portFromAddr(addr string) string {
	idx := strings.LastIndex(addr, ":")
	if idx < 0 {
		return ""
	}
	p := addr[idx+1:]
	if p == "" || !allDigits(p) {
		return ""
	}
	return p
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// currentSessionPids returns the PID chain from the current process up to (but
// excluding) PID 1, mirroring sys::_current_session_pids :367-375. It walks
// /proc/<pid>/stat field 4 (ppid). Because the comm field is in parentheses and
// may itself contain spaces, the ppid is the 2nd token AFTER the final ')'.
func currentSessionPids() []string {
	var pids []string
	pid := strconv.Itoa(os.Getpid())
	visited := map[string]bool{}
	for pid != "" && pid != "1" && !visited[pid] {
		visited[pid] = true
		stat, err := os.ReadFile("/proc/" + pid + "/stat")
		if err != nil {
			break
		}
		pids = append(pids, pid)
		ppid, ok := ppidFromStat(string(stat))
		if !ok || ppid == pid || ppid == "" || ppid == "0" {
			break
		}
		pid = ppid
	}
	return pids
}

// ppidFromStat parses the parent PID from a /proc/<pid>/stat line. The format
// is `pid (comm) state ppid ...`; the comm is parenthesised and may contain
// spaces, so we take the fields after the last ')'.
func ppidFromStat(stat string) (string, bool) {
	close := strings.LastIndex(stat, ")")
	if close < 0 {
		return "", false
	}
	rest := strings.Fields(stat[close+1:]) // fields: state ppid ...
	if len(rest) < 2 {
		return "", false
	}
	ppid := rest[1]
	if !allDigits(ppid) {
		return "", false
	}
	return ppid, true
}
