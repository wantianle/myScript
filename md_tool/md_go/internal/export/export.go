// Package export implements the `md e` (export) flow: it detects the target
// computer to push data back to (via the SSH source IP on a LAN, or a
// reverse-ssh tunnel port), then copies selected items from the vehicle's
// MDRIVE_DATA_ROOT to that target over SFTP (or to a local directory in the
// offline transport used by tests).
//
// The Bash source of truth is md.sh sys::prepare_export_ssh (:398-497) and
// sys::export (:585-634). This package keeps target resolution pure and
// unit-testable: ResolveTarget takes the SSH_CONNECTION string and the set of
// reverse-tunnel ports (from the `ss` process-tree scan in target_ports.go)
// and decides where to push, isolating the OS-specific port detection from the
// decision logic.
package export

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
)

// Target describes where an `md e` push lands.
type Target struct {
	IP     string // LAN source IP, or 127.0.0.1 for a reverse tunnel
	Port   string // "22" for LAN, or the reverse-tunnel port
	User   string // the computer's SSH username ("" until resolved)
	Source string // "lan" or "tunnel" — for logging/decisions
}

// Errors returned by ResolveTarget. Cancel and ambiguity are non-fatal states
// the caller handles (prompt / abort) rather than hard failures.
var (
	// ErrNoTunnel: neither a private LAN source nor any reverse-tunnel port,
	// and no operator port was supplied.
	ErrNoTunnel = errors.New("未检测到本地 SSH 连接 IP，请通过 ssh 直连(局域网)或带 -R 端口反向隧道登录车端后执行 md export")
	// ErrAmbiguous: more than one reverse-tunnel port exists and none was chosen.
	ErrAmbiguous = errors.New("回传端口不唯一")
	// ErrCanceled: the operator aborted a port prompt (q).
	ErrCanceled = errors.New("已取消导出")
)

// IsPrivateIP reports whether ip falls in the private ranges the Bash version
// accepts (md.sh sys::_is_private_ip :342-348): 10.*, 192.168.*,
// 172.{16..31}.*.
func IsPrivateIP(ip string) bool {
	return strings.HasPrefix(ip, "10.") ||
		strings.HasPrefix(ip, "192.168.") ||
		rePrivate172.MatchString(ip)
}

var rePrivate172 = regexp.MustCompile(`^172\.(1[6-9]|2[0-9]|3[0-1])\.`)

// IsLocalhostIP reports whether ip is a loopback (md.sh _is_localhost_ip :351-354).
func IsLocalhostIP(ip string) bool {
	return ip == "127.0.0.1" || ip == "localhost" || ip == "::1"
}

// ResolveTarget decides the export destination from the ssh source IP and the
// available reverse-tunnel ports (md.sh prepare_export_ssh :398-444).
//
// sshConn is the value of $SSH_CONNECTION (whitespace fields: client-ip
// client-port server-ip server-port). reversePorts is the sorted unique list
// of reverse-tunnel ports detected on the vehicle (may be empty). When the
// session is not a LAN direct connection and there is not exactly one reverse
// port, selectedPort is the port the operator chose ("" to auto-detect). It
// returns ErrCanceled only when the operator explicitly aborts.
func ResolveTarget(sshConn string, reversePorts []string, selectedPort string) (Target, error) {
	src := sshSourceIP(sshConn)
	if src != "" && IsPrivateIP(src) && !IsLocalhostIP(src) {
		return Target{IP: src, Port: "22", Source: "lan"}, nil
	}

	// Not a LAN direct connection: use the reverse tunnel.
	var port string
	switch {
	case len(reversePorts) == 1:
		port = reversePorts[0]
	case len(reversePorts) > 1:
		if selectedPort == "" {
			return Target{}, ErrAmbiguous
		}
		port = selectedPort
	case len(reversePorts) == 0:
		if selectedPort == "" {
			return Target{}, ErrNoTunnel
		}
		port = selectedPort
	}

	if !validPort(port) {
		return Target{}, fmt.Errorf("回传端口非法: %s", port)
	}
	return Target{IP: "127.0.0.1", Port: port, Source: "tunnel"}, nil
}

// sshSourceIP extracts the first field of $SSH_CONNECTION (the client IP).
func sshSourceIP(sshConn string) string {
	if sshConn == "" {
		return ""
	}
	f := strings.Fields(sshConn)
	if len(f) == 0 {
		return ""
	}
	return strings.TrimRight(f[0], "\r")
}

var validPortRe = regexp.MustCompile(`^[0-9]+$`)

func validPort(s string) bool {
	if !validPortRe.MatchString(s) {
		return false
	}
	n := atoi(s)
	return n >= 1 && n <= 65535
}

func atoi(s string) int {
	n := 0
	for _, c := range s {
		n = n*10 + int(c-'0')
	}
	return n
}
