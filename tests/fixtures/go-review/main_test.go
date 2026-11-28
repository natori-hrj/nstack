package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/natori-hrj/nstack/internal/workflow"
)

func TestCancelledPortableGateLeavesNoRunningChild(t *testing.T) {
	bridge, err := filepath.Abs("../go_review_bridge.py")
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("NSTACK_CONTRACT_SCENARIO", "pass")
	dir := t.TempDir()
	started := filepath.Join(dir, "started")
	completed := filepath.Join(dir, "completed")
	ctx, stop := context.WithTimeout(context.Background(), 10*time.Second)
	defer stop()
	f := fixture{script: bridge, profile: "portable", timeout: 10 * time.Second}
	done := make(chan error, 1)
	go func() {
		_, err := f.Gate(ctx, workflow.GateRequest{
			Directory: dir, Scratch: dir, Evidence: filepath.Join(dir, "evidence"),
			Argv: []string{"python3", "-c", `import sys, time
from pathlib import Path
Path(sys.argv[1]).touch()
time.sleep(0.5)
Path(sys.argv[2]).touch()`, started, completed},
		})
		done <- err
	}()
	ticker := time.NewTicker(5 * time.Millisecond)
	defer ticker.Stop()
	for {
		if _, err := os.Stat(started); err == nil {
			break
		}
		select {
		case <-ticker.C:
		case err := <-done:
			t.Fatalf("gate exited before its child started: %v", err)
		case <-ctx.Done():
			t.Fatal("gate child did not start")
		}
	}
	stop()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("cancelled gate reported success")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("adapter failed to stop")
	}
	// A surviving child would finish its delayed write during this interval.
	time.Sleep(650 * time.Millisecond)
	if _, err := os.Stat(completed); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("cancelled child completed after its adapter stopped: %v", err)
	}
}
