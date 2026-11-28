package install

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io/fs"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/natori-hrj/nstack"
)

func TestOpenCodeLifecycle(t *testing.T) {
	root := t.TempDir()
	codex := filepath.Join(root, "codex")
	opencode := filepath.Join(root, "opencode")
	files := fixtureAssets(t)
	apply(t, codex, "stage", "codex", files)
	apply(t, codex, "activate", "codex", files)
	if err := os.MkdirAll(filepath.Join(opencode, "skills"), 0700); err != nil {
		t.Fatal(err)
	}
	config := filepath.Join(opencode, "opencode.jsonc")
	settings := []byte("{ /* user configuration */ }\n")
	if err := os.WriteFile(config, settings, 0600); err != nil {
		t.Fatal(err)
	}
	install := func(action, id string, want int) {
		t.Helper()
		var out, stderr bytes.Buffer
		if code := RunCLI([]string{"--harness", "opencode", "--home", opencode, action, id}, &out, &stderr); code != want {
			t.Fatalf("%s %s: exit %d, want %d: %s", action, id, code, want, &stderr)
		}
	}
	install("stage", "first", 0)
	if _, err := os.Lstat(filepath.Join(opencode, "skills", activeLink)); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("staging changed discovery: %v", err)
	}
	install("activate", "first", 0)
	install("stage", "second", 0)
	flat := filepath.Join(opencode, "skills", "natori-mode.md")
	if err := os.WriteFile(flat, []byte("user-owned collision"), 0600); err != nil {
		t.Fatal(err)
	}
	install("activate", "second", 1)
	active(t, opencode, "first")
	if got, err := os.ReadFile(flat); err != nil || string(got) != "user-owned collision" {
		t.Fatalf("collision changed: %q, %v", got, err)
	}
	if err := os.Remove(flat); err != nil {
		t.Fatal(err)
	}
	install("activate", "second", 0)
	install("activate", "second", 0)
	active(t, opencode, "second")
	install("activate", "first", 0)
	active(t, opencode, "first")
	active(t, codex, "codex")
	if got, err := os.ReadFile(config); err != nil || !bytes.Equal(got, settings) {
		t.Fatalf("user configuration changed: %q, %v", got, err)
	}
}

func TestRollbackToSealedPreviousRelease(t *testing.T) {
	home := t.TempDir()
	current := fixtureAssets(t)
	previous := maps.Clone(current)
	for path := range previous {
		if rollbackOptionalDoc(path, true) {
			delete(previous, path)
		}
	}
	apply(t, home, "stage", "previous", previous)
	newSnapshot := apply(t, home, "stage", "current", current)
	apply(t, home, "activate", "current", current)
	apply(t, home, "activate", "previous", current)
	active(t, home, "previous")
	if err := os.Remove(filepath.Join(newSnapshot, "docs", "opencode.md")); err != nil {
		t.Fatal(err)
	}
	if _, err := run(home, "activate", "current", current, nil, false); err == nil {
		t.Fatal("accepted a sealed snapshot with a deleted file")
	}
	active(t, home, "previous")
}

func fixtureAssets(t *testing.T) map[string][]byte {
	t.Helper()
	bundle, err := distribution.Bundled()
	if err != nil {
		t.Fatal(err)
	}
	return bundle.Files
}

func apply(t *testing.T, home, action, id string, files map[string][]byte) string {
	t.Helper()
	path, err := run(home, action, id, files, nil, false)
	if err != nil {
		t.Fatalf("%s %s: %v", action, id, err)
	}
	return path
}

func active(t *testing.T, home, want string) {
	t.Helper()
	path := filepath.Join(home, "skills", activeLink)
	target, err := os.Readlink(path)
	if err != nil || target != filepath.Join(home, "nstack", "snapshots", want, "skills") {
		t.Fatalf("active snapshot: %q, %v; want %s", target, err, want)
	}
	if data, err := os.ReadFile(filepath.Join(path, "natori-mode", "SKILL.md")); err != nil || len(data) == 0 {
		t.Fatalf("active snapshot is incomplete: %v", err)
	}
}

// A real child executes the installer, then blocks at a filesystem checkpoint.
func TestInstallerChild(t *testing.T) {
	home := os.Getenv("NSTACK_INSTALL_TEST_HOME")
	if home == "" {
		return
	}
	_, err := run(home, os.Getenv("NSTACK_INSTALL_TEST_ACTION"), os.Getenv("NSTACK_INSTALL_TEST_ID"),
		fixtureAssets(t), func(phase string) {
			if phase == os.Getenv("NSTACK_INSTALL_TEST_STOP") {
				os.Stdout.WriteString(phase + "\n")
				var ignored [1]byte
				os.Stdin.Read(ignored[:])
			}
		}, false)
	if err != nil {
		t.Fatal(err)
	}
}

func child(t *testing.T, home, action, id, stop string) *exec.Cmd {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	t.Cleanup(cancel)
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestInstallerChild$")
	cmd.Env = append(os.Environ(), "NSTACK_INSTALL_TEST_HOME="+home, "NSTACK_INSTALL_TEST_ACTION="+action,
		"NSTACK_INSTALL_TEST_ID="+id, "NSTACK_INSTALL_TEST_STOP="+stop)
	cmd.Stderr = os.Stderr
	return cmd
}

func stopped(t *testing.T, home, action, id, phase string) (*exec.Cmd, func()) {
	t.Helper()
	cmd := child(t, home, action, id, phase)
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	output, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		cmd.Process.Kill()
		if cmd.ProcessState == nil {
			_ = cmd.Wait()
		}
	})
	scanner := bufio.NewScanner(output)
	if !scanner.Scan() || scanner.Text() != phase {
		t.Fatalf("child did not reach %s: %s (%v)", phase, scanner.Text(), scanner.Err())
	}
	return cmd, func() { _ = input.Close() }
}

func TestInterruptedInstall(t *testing.T) {
	files := fixtureAssets(t)
	for _, test := range []struct {
		phase, action, want string
	}{
		{"staging", "stage", "old"},
		{"before-activate", "activate", "old"},
		{"after-activate", "activate", "new"},
	} {
		t.Run(test.phase, func(t *testing.T) {
			home := t.TempDir()
			apply(t, home, "stage", "old", files)
			apply(t, home, "activate", "old", files)
			if test.action == "activate" {
				apply(t, home, "stage", "new", files)
			}
			cmd, _ := stopped(t, home, test.action, "new", test.phase)
			if err := cmd.Process.Kill(); err != nil {
				t.Fatal(err)
			}
			if err := cmd.Wait(); err == nil {
				t.Fatal("interrupted child reported success")
			}
			active(t, home, test.want)
			if test.action == "stage" {
				if _, err := os.Lstat(filepath.Join(home, "nstack", "snapshots", "new")); !errors.Is(err, fs.ErrNotExist) {
					t.Fatalf("staging exposed partial data: %v", err)
				}
			}
			apply(t, home, "stage", "new", files)
			apply(t, home, "activate", "new", files)
			active(t, home, "new")
		})
	}
}

func TestConcurrentInstall(t *testing.T) {
	home := t.TempDir()
	first, resume := stopped(t, home, "stage", "same", "staging")
	second := child(t, home, "stage", "same", "")
	if err := second.Start(); err != nil {
		t.Fatal(err)
	}
	wait := make(chan error, 1)
	go func() { wait <- second.Wait() }()
	select {
	case err := <-wait:
		t.Fatalf("concurrent writer bypassed state lock: %v", err)
	case <-time.After(200 * time.Millisecond):
	}
	resume()
	if err := first.Wait(); err != nil {
		t.Fatal(err)
	}
	if err := <-wait; err != nil {
		t.Fatal(err)
	}
	apply(t, home, "activate", "same", fixtureAssets(t))
	active(t, home, "same")
}

func TestPublicationDoesNotOverwrite(t *testing.T) {
	files := fixtureAssets(t)
	t.Run("new snapshot", func(t *testing.T) {
		home := t.TempDir()
		target := filepath.Join(home, "nstack", "snapshots", "new")
		_, err := run(home, "stage", "new", files, func(phase string) {
			if err := os.Mkdir(target, 0700); err != nil {
				t.Fatal(err)
			}
		}, false)
		if !errors.Is(err, fs.ErrExist) {
			t.Fatalf("stage should fail on competing destination: %v", err)
		}
		if items, err := os.ReadDir(target); err != nil || len(items) != 0 {
			t.Fatalf("unexpected modification of competing destination: %v, %v", items, err)
		}
	})
	for _, preexisting := range []bool{false, true} {
		t.Run(map[bool]string{false: "first activation", true: "existing activation"}[preexisting], func(t *testing.T) {
			home := t.TempDir()
			apply(t, home, "stage", "new", files)
			target := filepath.Join(home, "skills", activeLink)
			if preexisting {
				apply(t, home, "stage", "old", files)
				apply(t, home, "activate", "old", files)
			}
			_, err := run(home, "activate", "new", files, func(phase string) {
				if phase != "before-activate" {
					return
				}
				if preexisting {
					if err := os.Remove(target); err != nil {
						t.Fatal(err)
					}
				}
				if err := os.WriteFile(target, []byte("user-owned"), 0600); err != nil {
					t.Fatal(err)
				}
			}, false)
			if err == nil {
				t.Fatal("activation should reject a competing destination")
			}
			data, err := os.ReadFile(target)
			if err != nil || string(data) != "user-owned" {
				t.Fatalf("user path changed: %q, %v", data, err)
			}
		})
	}
}

func TestPublicationRejectsReplacedParent(t *testing.T) {
	home, outside := t.TempDir(), t.TempDir()
	parent := filepath.Join(home, "nstack", "snapshots")
	_, err := run(home, "stage", "new", fixtureAssets(t), func(string) {
		if err := os.Rename(parent, parent+"-old"); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(outside, parent); err != nil {
			t.Fatal(err)
		}
	}, false)
	if err == nil || !strings.Contains(err.Error(), "paths changed") {
		t.Fatalf("replaced parent should fail closed: %v", err)
	}
	for _, dir := range []string{outside, parent + "-old"} {
		if entries, err := os.ReadDir(dir); err != nil || len(entries) != 0 {
			t.Fatalf("unexpected publication under %s: %v, %v", dir, entries, err)
		}
	}
}

func TestRejectIncompleteAndRedirected(t *testing.T) {
	files := fixtureAssets(t)
	home := t.TempDir()
	apply(t, home, "stage", "old", files)
	apply(t, home, "activate", "old", files)
	path := apply(t, home, "stage", "new", files)
	if err := os.Remove(filepath.Join(path, "LICENSE-upstream")); err != nil {
		t.Fatal(err)
	}
	if _, err := run(home, "activate", "new", files, nil, false); err == nil || !strings.Contains(err.Error(), "incomplete snapshot") {
		t.Fatalf("incomplete snapshot accepted: %v", err)
	}
	active(t, home, "old")
	outside := t.TempDir()
	for _, name := range []string{"nstack", "skills", "nstack/lock", "nstack/snapshots"} {
		t.Run(name, func(t *testing.T) {
			other := t.TempDir()
			target := filepath.Join(other, name)
			if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(outside, target); err != nil {
				t.Fatal(err)
			}
			if _, err := run(other, "stage", "new", files, nil, false); err == nil {
				t.Fatal("installer accepted a redirected managed path")
			}
			if entries, err := os.ReadDir(outside); err != nil || len(entries) != 0 {
				t.Fatalf("outside path modified: %v, %v", entries, err)
			}
		})
	}
	for _, id := range []string{"../escape", "nested/x", "é", ".", "..", ".staging", "/absolute"} {
		if _, err := run(home, "stage", id, files, nil, false); err == nil {
			t.Errorf("accepted invalid snapshot ID %q", id)
		}
	}
}

func TestHomeResolvesSymlinkBeforeParent(t *testing.T) {
	workspace := t.TempDir()
	child := filepath.Join(workspace, "real", "child")
	wanted := filepath.Join(workspace, "real", "codex")
	other := filepath.Join(workspace, "codex")
	for _, dir := range []string{child, wanted, other} {
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
	}
	link := filepath.Join(workspace, "link")
	if err := os.Symlink(child, link); err != nil {
		t.Fatal(err)
	}
	path := apply(t, link+"/../codex", "stage", "first", fixtureAssets(t))
	if path != filepath.Join(wanted, "nstack", "snapshots", "first") {
		t.Fatalf("staged in the wrong home: %s", path)
	}
	if entries, err := os.ReadDir(other); err != nil || len(entries) != 0 {
		t.Fatalf("wrong home was modified: %v, %v", entries, err)
	}
	path = apply(t, link+"/missing/../../codex", "stage", "second", fixtureAssets(t))
	if path != filepath.Join(wanted, "nstack", "snapshots", "second") {
		t.Fatalf("missing component changed physical home: %s", path)
	}
	if _, err := os.Lstat(filepath.Join(child, "missing")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("discarded component was created: %v", err)
	}
}

func TestRejectDamagedSnapshots(t *testing.T) {
	files := fixtureAssets(t)
	const coreSkill = "skills/natori-mode/SKILL.md"
	header, _, found := strings.Cut(string(files[coreSkill]), "\n---\n")
	if !found {
		t.Fatal("fixture skill has no frontmatter boundary")
	}
	for _, test := range []struct {
		label, path, replacement string
		legacy                   bool
	}{
		{"truncated skill", coreSkill, "-", false},
		{"truncated README", "README.md", "# nstack\n", false},
		{"truncated optional legacy doc", "docs/behavior-v0.3.0.md", "# truncated\n", false},
		{"truncated legacy skill", coreSkill, "-", true},
		{"legacy skill with metadata only", coreSkill, header + "\n---\n\n", true},
	} {
		t.Run(test.label, func(t *testing.T) {
			home := t.TempDir()
			apply(t, home, "stage", "old", files)
			apply(t, home, "activate", "old", files)
			snapshot := apply(t, home, "stage", "new", files)
			if test.legacy {
				if err := syscall.Removexattr(snapshot, integrityAttribute); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.WriteFile(filepath.Join(snapshot, test.path), []byte(test.replacement), 0644); err != nil {
				t.Fatal(err)
			}
			if _, err := run(home, "activate", "new", files, nil, false); err == nil {
				t.Fatal("corrupted snapshot was accepted")
			}
			active(t, home, "old")
		})
	}
}
