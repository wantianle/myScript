package app

import (
	"mdrive/md/internal/config"
	"mdrive/md/internal/runner"
)

type Session struct {
	Config config.Config
	Runner runner.Runner
}

func NewSession(cfg config.Config) *Session {
	return &Session{
		Config: cfg,
		Runner: runner.LocalRunner{},
	}
}
