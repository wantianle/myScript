package sshx

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/pem"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/crypto/ssh"
)

// mustWriteTestKey generates a throwaway ed25519 key, writes it as a PEM file
// with the given permissions and returns its path. mode defaults to 0600,
// matching what md.sh's sys::nopasswd produces.
func mustWriteTestKey(t *testing.T) string {
	t.Helper()
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	block, err := ssh.MarshalPrivateKey(priv, "md test key")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "id_ed25519")
	if err := os.WriteFile(path, pem.EncodeToMemory(block), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// TestLoadSigner covers the ErrAuthFailed classification matrix of the key
// loading step: md.sh's ssh would print "No such file or directory", "Bad
// permissions" or "invalid format"; this layer maps all of them onto
// ErrAuthFailed so a later stage can route to sys::nopasswd-style repair.
func TestLoadSigner(t *testing.T) {
	valid := mustWriteTestKey(t)

	// Valid key with over-permissive permissions: OpenSSH refuses keys that
	// are group/world readable, so the loader must too (md.sh repairs with
	// chmod 600 before dialing).
	perm := filepath.Join(t.TempDir(), "loose_key")
	data, err := os.ReadFile(valid)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(perm, data, 0o644); err != nil {
		t.Fatal(err)
	}

	garbage := filepath.Join(t.TempDir(), "not_a_key")
	if err := os.WriteFile(garbage, []byte("this is not a private key"), 0o600); err != nil {
		t.Fatal(err)
	}

	cases := []struct {
		name    string
		path    string
		wantErr error
	}{
		{name: "valid key loads", path: valid, wantErr: nil},
		{name: "missing key is auth failure", path: filepath.Join(t.TempDir(), "nope"), wantErr: ErrAuthFailed},
		{name: "unparsable key is auth failure", path: garbage, wantErr: ErrAuthFailed},
		{name: "world-readable key is auth failure", path: perm, wantErr: ErrAuthFailed},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := loadSigner(tc.path)
			if tc.wantErr == nil {
				if err != nil {
					t.Fatalf("loadSigner(%s) = %v, want nil", tc.path, err)
				}
				return
			}
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("loadSigner(%s) = %v, want %v", tc.path, err, tc.wantErr)
			}
		})
	}
}
