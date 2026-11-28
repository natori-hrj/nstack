// Package codex implements the native Codex app-server adapter.
package codex

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"
)

type object = map[string]any

var disabledFeatures = []string{"apps", "plugins", "hooks", "memories", "multi_agent", "multi_agent_v2"}

type server struct {
	ctx    context.Context
	cmd    *exec.Cmd
	input  io.WriteCloser
	output io.ReadCloser
	log    *os.File
	lines  *bufio.Scanner
	nextID int
}

func startServer(ctx context.Context, cwd, evidence string, overrides ...string) (*server, error) {
	args := []string{"app-server", "--listen", "stdio://"}
	for _, name := range disabledFeatures {
		args = append(args, "--disable", name)
	}
	args = append(args,
		"-c", "sandbox_workspace_write.exclude_slash_tmp=true",
		"-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
		"-c", "sandbox_workspace_write.network_access=false",
		"-c", `shell_environment_policy.set.PYTHONDONTWRITEBYTECODE="1"`,
		"-c", `web_search="disabled"`,
	)
	cmd := exec.CommandContext(ctx, "codex", append(args, overrides...)...)
	cmd.Dir = cwd
	for _, entry := range os.Environ() {
		key, _, _ := strings.Cut(entry, "=")
		switch key {
		case "OPENAI_API_KEY", "CODEX_API_KEY", "PYTHONDONTWRITEBYTECODE":
			continue
		}
		cmd.Env = append(cmd.Env, entry)
	}
	cmd.Env = append(cmd.Env, "PYTHONDONTWRITEBYTECODE=1")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.WaitDelay = time.Second
	log, err := os.OpenFile(evidence+".stderr", os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, err
	}
	cmd.Stderr = log
	input, err := cmd.StdinPipe()
	if err != nil {
		log.Close()
		return nil, err
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		input.Close()
		log.Close()
		return nil, err
	}
	cmd.Cancel = func() error {
		err := killGroup(cmd.Process.Pid)
		// Closing our pipes also wakes blocked I/O if an inherited descriptor
		// survived in a process outside the server group.
		_ = input.Close()
		_ = output.Close()
		return err
	}
	if err := cmd.Start(); err != nil {
		input.Close()
		output.Close()
		log.Close()
		return nil, fmt.Errorf("start Codex app-server: %w", err)
	}
	lines := bufio.NewScanner(output)
	lines.Buffer(make([]byte, 64<<10), 8<<20)
	lines.Split(func(data []byte, atEOF bool) (int, []byte, error) {
		if atEOF && len(data) != 0 && !bytes.Contains(data, []byte{'\n'}) {
			return 0, nil, errors.New("partial Codex frame at EOF")
		}
		return bufio.ScanLines(data, atEOF)
	})
	s := &server{ctx: ctx, cmd: cmd, input: input, output: output, lines: lines, log: log}
	var initialized object
	if err := s.request("initialize", object{"clientInfo": object{"name": "nstack-review", "version": "0.3.0"}}, &initialized, nil); err != nil {
		s.close()
		return nil, err
	}
	if err := s.send(object{"method": "initialized"}); err != nil {
		s.close()
		return nil, err
	}
	return s, nil
}

func killGroup(pid int) error {
	err := syscall.Kill(-pid, syscall.SIGKILL)
	if errors.Is(err, syscall.ESRCH) {
		return os.ErrProcessDone
	}
	return err
}

func (s *server) close() {
	// Reap even after cancellation or EOF. The private group can still
	// contain helpers after the app-server itself stops.
	_ = killGroup(s.cmd.Process.Pid)
	_ = s.input.Close()
	_ = s.cmd.Wait()
	_ = s.output.Close()
	_ = s.log.Close()
}

func (s *server) send(value object) error {
	if err := s.ctx.Err(); err != nil {
		return err
	}
	err := json.NewEncoder(s.input).Encode(value)
	if s.ctx.Err() != nil {
		return s.ctx.Err()
	}
	if err != nil {
		return fmt.Errorf("write Codex app-server frame: %w", err)
	}
	return nil
}

// checkValue validates JSON shapes without accepting duplicate member names.
func checkValue(d *json.Decoder) error {
	value, err := d.Token()
	if err != nil {
		return err
	}
	switch value {
	case json.Delim('{'):
		seen := map[string]bool{}
		for d.More() {
			key, err := d.Token()
			name, ok := key.(string)
			if err != nil || !ok || seen[name] {
				return errors.New("invalid or duplicate JSON field")
			}
			seen[name] = true
			if err := checkValue(d); err != nil {
				return err
			}
		}
	case json.Delim('['):
		for d.More() {
			if err := checkValue(d); err != nil {
				return err
			}
		}
	default:
		return nil
	}
	_, err = d.Token()
	return err
}

func decode(raw []byte, dst any) error {
	if !utf8.Valid(raw) {
		return errors.New("invalid JSON UTF-8")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err := checkValue(d); err != nil {
		return err
	}
	if _, err := d.Token(); !errors.Is(err, io.EOF) {
		return errors.New("trailing JSON data")
	}
	return unmarshalWire(raw, dst)
}

type frame struct {
	Method string
	Params json.RawMessage
	Result json.RawMessage
	Error  json.RawMessage
	ID     json.RawMessage
}

func nonnull(raw json.RawMessage) bool { return len(raw) != 0 && string(raw) != "null" }

func (s *server) receive() (frame, error) {
	var f frame
	if err := s.ctx.Err(); err != nil {
		return f, err
	}
	if !s.lines.Scan() {
		if err := s.ctx.Err(); err != nil {
			return f, err
		}
		if err := s.lines.Err(); err != nil {
			return f, fmt.Errorf("read Codex app-server frame: %w", err)
		}
		return f, errors.New("Codex app-server stopped (EOF); see the private stderr log")
	}
	if err := s.ctx.Err(); err != nil {
		return f, err
	}
	var fields map[string]json.RawMessage
	if err := decode(s.lines.Bytes(), &fields); err != nil || fields == nil {
		return f, errors.New("invalid Codex JSON-RPC frame")
	}
	if rpc, ok := fields["jsonrpc"]; ok {
		var version string
		if json.Unmarshal(rpc, &version) != nil || version != "2.0" {
			return f, errors.New("invalid Codex JSON-RPC version")
		}
	}
	f.ID, f.Result, f.Error, f.Params = fields["id"], fields["result"], fields["error"], fields["params"]
	method, hasMethod := fields["method"]
	if !hasMethod {
		if !nonnull(f.ID) || len(f.Params) != 0 || (len(f.Result) != 0) == (len(f.Error) != 0) {
			return f, errors.New("invalid Codex JSON-RPC response")
		}
		return f, nil
	}
	if json.Unmarshal(method, &f.Method) != nil || strings.TrimSpace(f.Method) == "" {
		return f, errors.New("invalid Codex JSON-RPC method")
	}
	if len(f.ID) != 0 {
		return f, fmt.Errorf("unsupported Codex server request: %s", f.Method)
	}
	if len(f.Result) != 0 || len(f.Error) != 0 {
		return f, errors.New("invalid Codex notification")
	}
	switch f.Method {
	case "model/rerouted":
		return f, errors.New("Codex reported a model reroute")
	case "error":
		return f, errors.New("Codex reported a turn error")
	}
	return f, nil
}

func (s *server) request(method string, params object, dst any, observe func(frame) error) error {
	s.nextID++
	id := s.nextID
	if err := s.send(object{"id": id, "method": method, "params": params}); err != nil {
		return err
	}
	for {
		f, err := s.receive()
		if err != nil {
			return err
		}
		if f.Method != "" {
			if observe != nil {
				if err := observe(f); err != nil {
					return err
				}
			}
			continue
		}
		var responseID int
		if err := json.Unmarshal(f.ID, &responseID); err != nil || responseID != id {
			return fmt.Errorf("unexpected or duplicate Codex response ID while waiting for %s", method)
		}
		if len(f.Error) != 0 {
			return fmt.Errorf("Codex %s failed; see the private stderr log", method)
		}
		if !nonnull(f.Result) {
			return fmt.Errorf("invalid Codex result for %s", method)
		}
		if err := unmarshalWire(f.Result, dst); err != nil {
			return fmt.Errorf("invalid Codex result for %s: %w", method, err)
		}
		return nil
	}
}
