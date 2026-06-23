package runner

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"time"
)

type CommandRequest struct {
	Name    string
	Args    []string
	Dir     string
	Env     []string
	Timeout time.Duration
}

type CommandResult struct {
	Stdout   string
	Stderr   string
	ExitCode int
	Duration time.Duration
}

type OutputChunk struct {
	Stream string
	Data   []byte
}

type Runner interface {
	Run(ctx context.Context, req CommandRequest) (CommandResult, error)
	Stream(ctx context.Context, req CommandRequest) (<-chan OutputChunk, <-chan error)
}

type LocalRunner struct{}

func (LocalRunner) Run(ctx context.Context, req CommandRequest) (CommandResult, error) {
	runCtx := ctx
	var cancel context.CancelFunc
	if req.Timeout > 0 {
		runCtx, cancel = context.WithTimeout(ctx, req.Timeout)
		defer cancel()
	}

	start := time.Now()
	cmd := exec.CommandContext(runCtx, req.Name, req.Args...)
	cmd.Dir = req.Dir
	if len(req.Env) > 0 {
		cmd.Env = append(os.Environ(), req.Env...)
	}

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	result := CommandResult{
		Stdout:   stdout.String(),
		Stderr:   stderr.String(),
		ExitCode: 0,
		Duration: time.Since(start),
	}
	if err != nil {
		result.ExitCode = 1
		if exitErr, ok := err.(*exec.ExitError); ok {
			result.ExitCode = exitErr.ExitCode()
		}
	}
	return result, err
}

func (LocalRunner) Stream(ctx context.Context, req CommandRequest) (<-chan OutputChunk, <-chan error) {
	output := make(chan OutputChunk)
	errs := make(chan error, 1)
	go func() {
		defer close(output)
		defer close(errs)
		result, err := LocalRunner{}.Run(ctx, req)
		if result.Stdout != "" {
			output <- OutputChunk{Stream: "stdout", Data: []byte(result.Stdout)}
		}
		if result.Stderr != "" {
			output <- OutputChunk{Stream: "stderr", Data: []byte(result.Stderr)}
		}
		errs <- err
	}()
	return output, errs
}
