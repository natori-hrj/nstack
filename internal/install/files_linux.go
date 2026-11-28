package install

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"unsafe"
)

// A directory handle pins the verified directory. Child opens do not follow
// symlinks; mutations through procfs stay relative to the pinned descriptor.
type directory struct{ *os.File }

// Resolve the requested home like a non-strict realpath, before creating
// anything. In particular `link/..` is relative to the link's target.
func resolveHome(path string) (string, error) {
	if !filepath.IsAbs(path) {
		cwd, err := os.Getwd()
		if err != nil {
			return "", err
		}
		path = cwd + "/" + path
	}
	resolved := "/"
	links := 0
	for parts := strings.Split(path, "/"); len(parts) != 0; {
		part := parts[0]
		parts = parts[1:]
		switch part {
		case "", ".":
			continue
		case "..":
			resolved = filepath.Dir(resolved)
			continue
		}
		next := filepath.Join(resolved, part)
		target, err := os.Readlink(next)
		switch {
		case err == nil:
			links++
			if links > 255 {
				return "", syscall.ELOOP
			}
			if filepath.IsAbs(target) {
				resolved = "/"
			}
			parts = append(strings.Split(target, "/"), parts...)
		case errors.Is(err, syscall.EINVAL), errors.Is(err, os.ErrNotExist):
			resolved = next
		default:
			return "", err
		}
	}
	return resolved, nil
}

// The resolved home is now a literal path: walk it without following links
// newly introduced between resolution and creation.
func createHome(path string) (directory, error) {
	const flags = syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC
	fd, err := syscall.Open("/", flags, 0)
	if err != nil {
		return directory{}, err
	}
	defer func() { _ = syscall.Close(fd) }()
	for _, part := range strings.Split(strings.TrimPrefix(path, "/"), "/") {
		if part == "" {
			continue
		}
		next, err := syscall.Openat(fd, part, flags, 0)
		if err == syscall.ENOENT {
			if err = syscall.Mkdirat(fd, part, 0755); err != nil && err != syscall.EEXIST {
				return directory{}, err
			}
			next, err = syscall.Openat(fd, part, flags, 0)
		}
		if err != nil {
			return directory{}, fmt.Errorf("open resolved Codex home %s: %w", path, err)
		}
		_ = syscall.Close(fd)
		fd = next
	}
	return openDirectory(fd, ".")
}

func (d directory) path(name string) string {
	return fmt.Sprintf("/proc/self/fd/%d/%s", d.Fd(), name)
}

func openDirectory(parent int, name string) (directory, error) {
	fd, err := syscall.Openat(parent, name, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return directory{}, fmt.Errorf("open managed directory %s: %w", name, err)
	}
	file := os.NewFile(uintptr(fd), name)
	var stat syscall.Stat_t
	if err := syscall.Fstat(fd, &stat); err != nil {
		file.Close()
		return directory{}, err
	}
	if int(stat.Uid) != os.Geteuid() || stat.Mode&0022 != 0 {
		file.Close()
		return directory{}, fmt.Errorf("managed directory %s must be owned by this user and not writable by others", name)
	}
	return directory{file}, nil
}

func (d directory) open(name string, create bool) (directory, error) {
	if create {
		if err := syscall.Mkdirat(int(d.Fd()), name, 0755); err != nil && err != syscall.EEXIST {
			return directory{}, fmt.Errorf("create managed directory %s: %w", name, err)
		}
	}
	return openDirectory(int(d.Fd()), name)
}

func matches(file *os.File, path string) bool {
	expected, err := file.Stat()
	if err != nil {
		return false
	}
	current, err := os.Lstat(path)
	return err == nil && os.SameFile(expected, current)
}

func lock(state directory) (*os.File, error) {
	fd, err := syscall.Openat(int(state.Fd()), "lock", syscall.O_CREAT|syscall.O_RDWR|
		syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0600)
	if err != nil {
		return nil, fmt.Errorf("open installer lock: %w", err)
	}
	file := os.NewFile(uintptr(fd), "lock")
	var stat syscall.Stat_t
	if err := syscall.Fstat(fd, &stat); err != nil {
		file.Close()
		return nil, err
	}
	if stat.Mode&syscall.S_IFMT != syscall.S_IFREG || int(stat.Uid) != os.Geteuid() ||
		stat.Mode&0022 != 0 || stat.Nlink != 1 {
		file.Close()
		return nil, fmt.Errorf("unsafe installer lock")
	}
	for {
		err = syscall.Flock(fd, syscall.LOCK_EX)
		if err != syscall.EINTR {
			break
		}
	}
	if err != nil || !matches(file, state.path("lock")) {
		file.Close()
		return nil, fmt.Errorf("installer lock unavailable or replaced: %v", err)
	}
	return file, nil
}

func temp(parent directory, prefix string) (string, directory, func(), error) {
	path, err := os.MkdirTemp(parent.path("."), prefix)
	if err != nil {
		return "", directory{}, nil, err
	}
	name := filepath.Base(path)
	child, err := parent.open(name, false)
	if err != nil {
		return "", directory{}, nil, err
	}
	cleanup := func() {
		if matches(child.File, parent.path(name)) {
			_ = os.RemoveAll(parent.path(name))
		}
		_ = child.Close()
	}
	return name, child, cleanup, nil
}

// renameNew is Linux renameat2(RENAME_NOREPLACE). The Go syscall package
// does not expose it on amd64. These are the supported Linux target ABIs.
func renameNew(from directory, old string, to directory, name string) error {
	var number uintptr
	switch runtime.GOARCH {
	case "amd64":
		number = 316
	case "arm64":
		number = 276
	default:
		return syscall.ENOSYS
	}
	src, err := syscall.BytePtrFromString(old)
	if err != nil {
		return err
	}
	dst, err := syscall.BytePtrFromString(name)
	if err != nil {
		return err
	}
	const noReplace = 1
	_, _, errno := syscall.Syscall6(number, from.Fd(), uintptr(unsafe.Pointer(src)), to.Fd(), uintptr(unsafe.Pointer(dst)), noReplace, 0)
	runtime.KeepAlive(from)
	runtime.KeepAlive(to)
	if errno != 0 {
		return errno
	}
	return nil
}
