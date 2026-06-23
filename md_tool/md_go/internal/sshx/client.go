package sshx

import (
	"context"
	"errors"

	"golang.org/x/crypto/ssh"
)

var ErrNotImplemented = errors.New("ssh client is not implemented yet")

type ClientConfig struct {
	User    string
	Host    string
	Port    int
	KeyPath string
}

type Client struct {
	Config ClientConfig
}

func NewClient(cfg ClientConfig) *Client {
	return &Client{Config: cfg}
}

func (c *Client) Dial(ctx context.Context) (*ssh.Client, error) {
	_ = ctx
	_ = c
	return nil, ErrNotImplemented
}
