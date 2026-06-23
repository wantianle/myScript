package transfer

import (
	"context"
	"errors"
	"io"

	"github.com/pkg/sftp"
)

var ErrNotImplemented = errors.New("sftp transport is not implemented yet")

type CopyOptions struct {
	Overwrite bool
	Progress  func(written int64, total int64)
}

type Transport interface {
	MkdirAll(ctx context.Context, path string) error
	CopyFile(ctx context.Context, src string, dst string, opts CopyOptions) error
	CopyDir(ctx context.Context, src string, dst string, opts CopyOptions) error
}

type SFTPTransport struct {
	Client *sftp.Client
}

func NewSFTPTransport(client *sftp.Client) *SFTPTransport {
	return &SFTPTransport{Client: client}
}

func (t *SFTPTransport) MkdirAll(ctx context.Context, path string) error {
	_ = ctx
	_ = path
	_ = t
	return ErrNotImplemented
}

func (t *SFTPTransport) CopyFile(ctx context.Context, src string, dst string, opts CopyOptions) error {
	_ = ctx
	_ = src
	_ = dst
	_ = opts
	_ = t
	return ErrNotImplemented
}

func (t *SFTPTransport) CopyDir(ctx context.Context, src string, dst string, opts CopyOptions) error {
	_ = ctx
	_ = src
	_ = dst
	_ = opts
	_ = t
	return ErrNotImplemented
}

func copyWithProgress(dst io.Writer, src io.Reader, total int64, progress func(int64, int64)) error {
	buffer := make([]byte, 128*1024)
	var written int64
	for {
		n, readErr := src.Read(buffer)
		if n > 0 {
			if _, err := dst.Write(buffer[:n]); err != nil {
				return err
			}
			written += int64(n)
			if progress != nil {
				progress(written, total)
			}
		}
		if readErr == io.EOF {
			return nil
		}
		if readErr != nil {
			return readErr
		}
	}
}
