package sshx

import (
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/crypto/ssh"
)

// loadSigner reads and parses the private key at path, mirroring the
// `-i "$KEY_PATH"` behaviour of md.sh (KEY_PATH defaults to
// $HOME/.ssh/id_ed25519, md.sh:15).
//
// Any problem here is classified as ErrAuthFailed because no session can be
// established without a usable credential. OpenSSH also refuses keys with
// group/world permissions ("Bad permissions ..."); ssh.ParsePrivateKey does
// not enforce that, so this function checks it explicitly — md.sh repairs the
// permission with chmod 600 before dialing (sys::nopasswd), and a later stage
// can do the same once it sees ErrAuthFailed.
func loadSigner(path string) (ssh.Signer, error) {
	info, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("%w: key file %s not found (generate one with ssh-keygen -t ed25519)", ErrAuthFailed, path)
		}
		return nil, fmt.Errorf("%w: cannot stat key file %s: %v", ErrAuthFailed, path, err)
	}
	if info.Mode().Perm()&0o077 != 0 {
		return nil, fmt.Errorf("%w: key file %s has group/world permissions (%v); run chmod 600", ErrAuthFailed, path, info.Mode().Perm())
	}
	pem, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("%w: cannot read key file %s: %v", ErrAuthFailed, path, err)
	}
	signer, err := ssh.ParsePrivateKey(pem)
	if err != nil {
		return nil, fmt.Errorf("%w: cannot parse key file %s: %v", ErrAuthFailed, path, err)
	}
	return signer, nil
}

// defaultKeyPath returns $HOME/.ssh/id_ed25519, the same default md.sh
// hard-codes in KEY_PATH.
func defaultKeyPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("%w: cannot determine home directory for default key path: %v", ErrAuthFailed, err)
	}
	return filepath.Join(home, ".ssh", "id_ed25519"), nil
}
