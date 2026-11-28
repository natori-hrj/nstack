package codex

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

const lifecycleFixtureArgument = "--lifecycle-fixture"

func trackFixtureProcess(t *testing.T, pid int) int {
	t.Helper()
	fd, err := openProcessFD(pid)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		// Emergency cleanup only. pidfd retains this exact process identity.
		_ = signalProcessFD(fd, syscall.SIGKILL)
		_ = syscall.Close(fd)
	})
	return fd
}

func assertReaped(t *testing.T, fd int) {
	t.Helper()
	info, err := os.ReadFile(fmt.Sprintf("/proc/self/fdinfo/%d", fd))
	if err != nil || !strings.Contains(string(info), "\nPid:\t-1\n") {
		t.Fatalf("owned process still exists (including zombies): %s (%v)", info, err)
	}
}

func TestPidfdRejectsNonChild(t *testing.T) {
	// The supervisor may observe a stale numeric PID in procfs. Even if
	// pidfd_open succeeds, its caller must not signal a non-child.
	if err := stopChild(os.Getpid()); err != nil {
		t.Fatal(err)
	}
}

func TestExternalExecServerCannotBeSupervised(t *testing.T) {
	t.Setenv("CODEX_EXEC_SERVER_URL", "ws://fixture.invalid/")
	_, err := startServer(context.Background(), t.TempDir(), filepath.Join(t.TempDir(), "evidence"))
	if err == nil || !strings.Contains(err.Error(), "local supervised execution") ||
		strings.Contains(err.Error(), "fixture.invalid") {
		t.Fatalf("expected a local process boundary error, got %v", err)
	}
}

func runLifecycleFixture(dir, node string) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	start := func(name string, attributes syscall.SysProcAttr) error {
		child := exec.Command(exe, lifecycleFixtureArgument, dir, name)
		child.SysProcAttr = &attributes
		return child.Start()
	}
	signal.Ignore(syscall.SIGTERM)
	marker := filepath.Join(dir, node)
	if err := os.WriteFile(marker+".tmp", []byte(strconv.Itoa(os.Getpid())), 0600); err != nil {
		return err
	}
	if err := os.Rename(marker+".tmp", marker); err != nil {
		return err
	}
	switch node {
	case "server":
		if err := start("group", syscall.SysProcAttr{Setpgid: true}); err != nil {
			return err
		}
	case "group":
		if err := start("session", syscall.SysProcAttr{Setsid: true}); err != nil {
			return err
		}
	case "session":
		if err := start("leaf", syscall.SysProcAttr{}); err != nil {
			return err
		}
	}
	for deadline := time.Now().Add(15 * time.Second); time.Now().Before(deadline); {
		if _, err := os.Stat(marker + ".exit"); err == nil {
			return nil
		}
		if node == "session" {
			// Keep creating descendants until shutdown, without retaining
			// a large number of processes if the test itself fails.
			for i := 0; i < 6; i++ {
				if _, err := os.Stat(filepath.Join(dir, "fork")); err != nil {
					break
				}
				child := exec.Command("/bin/true")
				if err := child.Start(); err != nil {
					return err
				}
				if err := os.WriteFile(filepath.Join(dir, "fork-started"), nil, 0600); err != nil {
					return err
				}
				_ = child.Wait()
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	return errors.New("lifecycle fixture reached emergency deadline")
}

func TestSupervisorReapsDescendants(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	unrelated := exec.Command("/bin/sleep", "15")
	if err := unrelated.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_ = unrelated.Process.Kill()
		_ = unrelated.Wait()
	}()
	for _, mode := range []string{"cancel with reparented child", "app-server exits", "cancel during fork", "immediate cancel"} {
		t.Run(mode, func(t *testing.T) {
			dir := t.TempDir()
			r, w, err := os.Pipe()
			if err != nil {
				t.Fatal(err)
			}
			defer r.Close()
			defer w.Close()
			cmd := exec.Command(exe, SupervisorArgument, exe, lifecycleFixtureArgument, dir, "server")
			cmd.ExtraFiles = []*os.File{r}
			cmd.Stderr = os.Stderr
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			r.Close()
			done := make(chan error, 1)
			go func() { done <- cmd.Wait() }()
			finished := false
			defer func() {
				if !finished {
					w.Close()
					<-done
				}
			}()
			ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
			defer cancel()
			nodes, pids := make(map[string]int), make(map[string]int)
			if mode != "immediate cancel" {
				for _, node := range []string{"server", "group", "session", "leaf"} {
					pid, err := waitForPID(ctx, filepath.Join(dir, node))
					if err != nil {
						t.Fatal(err)
					}
					pids[node] = pid
					nodes[node] = trackFixtureProcess(t, pid)
				}
			}
			switch mode {
			case "cancel with reparented child":
				fixtureWrite(filepath.Join(dir, "group.exit"), "")
				status := fmt.Sprintf("/proc/%d/status", pids["session"])
				waitLifecycleFixture(t, ctx, func() bool {
					data, err := os.ReadFile(status)
					return err == nil && strings.Contains(string(data), fmt.Sprintf("\nPPid:\t%d\n", cmd.Process.Pid))
				})
				w.Close()
			case "app-server exits":
				fixtureWrite(filepath.Join(dir, "server.exit"), "")
			case "cancel during fork":
				fixtureWrite(filepath.Join(dir, "fork"), "")
				waitLifecycleFixture(t, ctx, func() bool {
					_, err := os.Stat(filepath.Join(dir, "fork-started"))
					return err == nil
				})
				w.Close()
			default:
				w.Close()
			}
			select {
			case err := <-done:
				finished = true
				if err != nil {
					t.Fatal(err)
				}
			case <-ctx.Done():
				t.Fatal(ctx.Err())
			}
			for _, fd := range nodes {
				assertReaped(t, fd)
			}
			if err := unrelated.Process.Signal(syscall.Signal(0)); err != nil {
				t.Fatalf("unrelated process affected: %v", err)
			}
		})
	}
}

func waitLifecycleFixture(t *testing.T, ctx context.Context, ready func() bool) {
	t.Helper()
	for !ready() {
		select {
		case <-ctx.Done():
			t.Fatal(ctx.Err())
		case <-time.After(5 * time.Millisecond):
		}
	}
}
