// This is a black-box test launcher, not a production harness adapter.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/natori-hrj/nstack/internal/workflow"
)

type fixture struct {
	script, profile string
	timeout         time.Duration
}

func (f fixture) Name() string {
	if f.profile == "protocol" {
		return "codex-app-server"
	}
	return "portable-fixture"
}

func (f fixture) invoke(ctx context.Context, op string, request any, result any) error {
	payload, err := json.Marshal(request)
	if err != nil {
		return err
	}
	cmd := exec.CommandContext(ctx, "python3", "-B", f.script, f.profile, op, strconv.FormatInt(int64(f.timeout/time.Second), 10))
	cmd.Stdin = bytes.NewReader(payload)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if f.profile == "protocol" {
			// The bridge must unwind the Python adapter's private app-server
			// group, which is separate from the bridge's process group.
			return cmd.Process.Signal(syscall.SIGTERM)
		}
		err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return os.ErrProcessDone
		}
		return err
	}
	cmd.WaitDelay = 3 * time.Second
	out, err := cmd.Output()
	if err != nil {
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			return fmt.Errorf("fixture bridge: %w: %s", err, exit.Stderr)
		}
		return err
	}
	var reply struct {
		Result json.RawMessage
		Error  string
	}
	if err := json.Unmarshal(out, &reply); err != nil {
		return err
	}
	if reply.Error != "" {
		return errors.New(reply.Error)
	}
	return json.Unmarshal(reply.Result, result)
}

func (f fixture) Preflight(ctx context.Context, directory string, reviewer workflow.Role, evidence string) (workflow.Evidence, error) {
	var result workflow.Evidence
	err := f.invoke(ctx, "preflight", map[string]any{"Directory": directory, "Role": reviewer, "Evidence": evidence}, &result)
	return result, err
}

func (f fixture) Gate(ctx context.Context, request workflow.GateRequest) (workflow.GateResult, error) {
	var result workflow.GateResult
	err := f.invoke(ctx, "gate", request, &result.Evidence)
	if err == nil {
		code, ok := result.Evidence["exitCode"].(float64)
		if !ok || code != float64(int(code)) {
			return result, errors.New("fixture returned no valid exit code")
		}
		exitCode := int(code)
		result.ExitCode = &exitCode
	}
	return result, err
}

func (f fixture) Run(ctx context.Context, request workflow.TurnRequest) (workflow.TurnResult, error) {
	var result workflow.TurnResult
	if err := f.invoke(ctx, "run", request, &result.Evidence); err != nil {
		return result, err
	}
	result.Session, _ = result.Evidence["session"].(string)
	result.Model, _ = result.Evidence["model"].(string)
	result.Effort, _ = result.Evidence["effort"].(string)
	result.Message, _ = result.Evidence["message"].(string)
	return result, nil
}

func main() {
	if len(os.Args) < 3 || (os.Args[2] != "portable" && os.Args[2] != "protocol") {
		fmt.Fprintln(os.Stderr, "Usage: go-review FIXTURE_BRIDGE.py portable|protocol REVIEW_ARGS...")
		os.Exit(2)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	result := workflow.RunCLI(ctx, os.Args[3:], os.Stdout, os.Stderr, func(timeout time.Duration) (workflow.Adapter, error) {
		return fixture{os.Args[1], os.Args[2], timeout}, nil
	})
	cancel()
	os.Exit(result)
}
