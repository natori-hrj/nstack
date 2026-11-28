package workflow

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

type gitRepo struct{ directory string }

// Keep Git and gh subprocesses in their own process groups so cancellation
// also stops their local helpers. The adapter owns its own subprocesses.
func command(ctx context.Context, cwd, binary string, argv ...string) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	cmd := exec.CommandContext(ctx, binary, argv...)
	cmd.Dir = cwd
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		if errors.Is(err, syscall.ESRCH) {
			return os.ErrProcessDone
		}
		return err
	}
	cmd.WaitDelay = time.Second
	out, err := cmd.Output()
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	return strings.TrimSpace(string(out)), err
}

func (r gitRepo) git(ctx context.Context, args ...string) (string, error) {
	return r.configured(ctx, nil, args...)
}

func (r gitRepo) configured(ctx context.Context, config []string, args ...string) (string, error) {
	result, err := command(ctx, r.directory, "git", append(append([]string{}, config...), args...)...)
	if err != nil {
		// The argv can include credentials in a locally configured remote URL.
		return "", fmt.Errorf("git %s: %w", args[0], err)
	}
	return result, nil
}

func (r gitRepo) head(ctx context.Context) (string, error) {
	return r.git(ctx, "rev-parse", "HEAD")
}

func (r gitRepo) ref(ctx context.Context) (string, error) {
	ref, err := r.git(ctx, "symbolic-ref", "--quiet", "HEAD")
	var exit *exec.ExitError
	if errors.As(err, &exit) && exit.ExitCode() == 1 {
		return "", nil // Detached HEAD.
	}
	return ref, err
}

func (r gitRepo) checkIndex(ctx context.Context) error {
	entries, err := r.git(ctx, "ls-files", "-v", "-z")
	if err != nil {
		return err
	}
	for _, entry := range strings.Split(entries, "\x00") {
		if entry != "" && (entry[0] == 'S' || entry[0] >= 'a' && entry[0] <= 'z') {
			return fmt.Errorf("checkout has index flags that can hide tracked changes: %s", r.directory)
		}
	}
	return nil
}

func (r gitRepo) cleanAt(ctx context.Context, candidate string) error {
	if err := r.checkIndex(ctx); err != nil {
		return err
	}
	head, err := r.head(ctx)
	if err != nil {
		return err
	}
	status, err := r.git(ctx, "status", "--porcelain", "--untracked-files=all")
	if err != nil {
		return err
	}
	if head != candidate || status != "" {
		return fmt.Errorf("dirty checkout or changed candidate: %s", r.directory)
	}
	return nil
}

func (r gitRepo) checkWork(ctx context.Context, ref, candidate, original, start string) error {
	current, err := r.ref(ctx)
	if err != nil {
		return err
	}
	head, err := r.head(ctx)
	if err != nil {
		return err
	}
	if current != ref || head != candidate {
		return errors.New("authorized work ref or candidate changed")
	}
	if original != "" {
		oid, err := r.git(ctx, "rev-parse", "--verify", original)
		if err != nil {
			return err
		}
		if oid != start {
			return errors.New("original ref changed")
		}
	}
	return r.checkIndex(ctx)
}

func (r gitRepo) branchRef(ctx context.Context, ref string) error {
	if !strings.HasPrefix(ref, "refs/heads/") {
		return errors.New("authorization requires an explicit refs/heads/ branch")
	}
	_, err := r.git(ctx, "check-ref-format", ref)
	return err
}

func (r gitRepo) cloneAt(ctx context.Context, directory, candidate string) (gitRepo, error) {
	clone := gitRepo{directory}
	if _, err := r.git(ctx, "clone", "--quiet", "--no-local", "--no-checkout", "--", r.directory, directory); err != nil {
		return clone, err
	}
	if _, err := clone.git(ctx, "checkout", "--quiet", "--detach", candidate); err != nil {
		return clone, err
	}
	return clone, clone.cleanAt(ctx, candidate)
}

func (r gitRepo) lock(ctx context.Context) (*os.File, error) {
	path, err := r.git(ctx, "rev-parse", "--path-format=absolute", "--git-path", "nstack-review.lock")
	if err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Clean(path), os.O_CREATE|os.O_WRONLY|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		if errors.Is(err, syscall.EWOULDBLOCK) {
			return nil, errors.New("another nstack review workflow owns this checkout")
		}
		return nil, err
	}
	return f, nil
}

var objectID = regexp.MustCompile(`^(?:[0-9a-f]{40}|[0-9a-f]{64})$`)
