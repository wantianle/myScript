package sshx

import (
	"time"
)

// keepaliveConn is the subset of *ssh.Client the keepalive loop needs. It is
// isolated behind an interface so tests can inject SendRequest failures
// without a real connection.
type keepaliveConn interface {
	SendRequest(name string, wantReply bool, payload []byte) (bool, []byte, error)
	Close() error
}

// keepaliveLoop mirrors OpenSSH's ServerAliveInterval / ServerAliveCountMax
// (md.sh SSH_OPTS, md.sh:26-27). Every interval it sends a
// keepalive@openssh.com global request; a transport error or a reply that
// does not arrive within one interval counts as one consecutive failure, and
// after countMax consecutive failures it closes the connection. In-flight
// operations then fail fast (x/crypto closes their channels) instead of
// hanging on a dead peer, and the next operation redials once.
//
// The reply wait is bounded by a goroutine + select because x/crypto has no
// per-request deadline: an unresponsive-but-open peer must not block the
// keepalive goroutine forever. The goroutine exits as soon as the connection
// is closed (SendRequest unblocks when the mux tears down).
func keepaliveLoop(conn keepaliveConn, stop, done chan struct{}, interval time.Duration, countMax int) {
	defer close(done)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	failures := 0
	for {
		select {
		case <-stop:
			return
		case <-ticker.C:
		}

		rc := make(chan error, 1)
		go func() {
			_, _, err := conn.SendRequest("keepalive@openssh.com", true, nil)
			rc <- err
		}()
		select {
		case err := <-rc:
			if err != nil {
				failures++
			} else {
				failures = 0
			}
		case <-time.After(interval):
			failures++
		case <-stop:
			return
		}

		if failures >= countMax {
			_ = conn.Close()
			return
		}
	}
}
