package install

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"
)

func skillName(path string, staged bool) (string, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return "", err
	}
	file := os.NewFile(uintptr(fd), path)
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() {
		return "", fmt.Errorf("skill description must be a regular file: %s", path)
	}
	const limit = 1 << 20
	lines := bufio.NewScanner(io.LimitReader(file, limit+1))
	lines.Buffer(make([]byte, 4096), limit)
	if !lines.Scan() {
		if staged && lines.Err() == nil {
			return "", fmt.Errorf("staged skill has no frontmatter: %s", path)
		}
		return "", lines.Err()
	}
	if !utf8.ValidString(lines.Text()) {
		return "", fmt.Errorf("invalid UTF-8 skill description: %s", path)
	}
	if strings.TrimPrefix(lines.Text(), "\uFEFF") != "---" {
		if staged {
			return "", fmt.Errorf("staged skill has no frontmatter: %s", path)
		}
		return "", nil
	}
	var front strings.Builder
	for lines.Scan() {
		line := lines.Text()
		if line == "---" {
			var document any
			if err := yaml.Unmarshal([]byte(front.String()), &document); err != nil {
				return "", fmt.Errorf("invalid skill frontmatter %s: %w", path, err)
			}
			var raw, desc any
			switch fields := document.(type) {
			case map[string]any:
				raw, desc = fields["name"], fields["description"]
			case map[any]any:
				raw, desc = fields["name"], fields["description"]
			}
			name, _ := raw.(string)
			description, _ := desc.(string)
			if staged && (strings.TrimSpace(name) == "" || strings.TrimSpace(description) == "") {
				return "", fmt.Errorf("staged skill is missing its name or description: %s", path)
			}
			if !staged {
				return name, nil
			}
			for lines.Scan() {
				if !utf8.ValidString(lines.Text()) {
					return "", fmt.Errorf("invalid UTF-8 skill instructions: %s", path)
				}
				if strings.TrimSpace(lines.Text()) != "" {
					return name, nil
				}
			}
			if err := lines.Err(); err != nil {
				return "", err
			}
			return "", fmt.Errorf("staged skill has no instructions: %s", path)
		}
		front.WriteString(line)
		front.WriteByte('\n')
	}
	return "", fmt.Errorf("unclosed or oversized skill frontmatter: %s", path)
}

func snapshotNames(skills directory) (map[string]bool, error) {
	entries, err := skills.ReadDir(-1)
	if err != nil {
		return nil, err
	}
	declared := make(map[string]bool)
	names := make(map[string]bool)
	for _, entry := range entries {
		folder := entry.Name()
		if !entry.IsDir() {
			return nil, fmt.Errorf("unexpected staged skill: %s", folder)
		}
		skill, err := skills.open(folder, false)
		if err != nil {
			return nil, err
		}
		name, err := skillName(skill.path("SKILL.md"), true)
		skill.Close()
		if err != nil {
			return nil, fmt.Errorf("%s: %w", folder, err)
		}
		if declared[name] {
			return nil, fmt.Errorf("duplicate staged skill name: %s", name)
		}
		declared[name] = true
		names[name], names[folder] = true, true
	}
	return names, nil
}

// Existing directory symlinks participate in Codex discovery. Follow them
// only for read-only duplicate checks, using the directory inode to stop cycles.
func checkCollisions(skills directory, names map[string]bool) error {
	type inode struct{ dev, ino uint64 }
	visited := make(map[inode]bool)
	var visit func(path string, top bool) error
	visit = func(path string, top bool) error {
		info, err := os.Stat(path)
		if err != nil {
			return err
		}
		stat := info.Sys().(*syscall.Stat_t)
		key := inode{uint64(stat.Dev), uint64(stat.Ino)}
		description := filepath.Join(path, "SKILL.md")
		if _, err := os.Lstat(description); err == nil {
			actual, err := skillName(description, false)
			if err != nil {
				return err
			}
			if names[filepath.Base(path)] || names[actual] {
				return fmt.Errorf("move existing skill out of discovery first: %s", description)
			}
		} else if !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		if visited[key] {
			return nil
		}
		visited[key] = true
		entries, err := os.ReadDir(path)
		if err != nil {
			return err
		}
		for _, item := range entries {
			name := item.Name()
			if top && name == activeLink {
				continue
			}
			child := filepath.Join(path, name)
			if name == "SKILL.md" {
				continue
			}
			isDir := item.IsDir()
			if item.Type()&fs.ModeSymlink != 0 {
				info, err := os.Stat(child)
				if errors.Is(err, fs.ErrNotExist) || errors.Is(err, syscall.ELOOP) {
					continue
				}
				if err != nil {
					return err
				}
				isDir = info.IsDir()
			}
			if isDir {
				if err := visit(child, false); err != nil {
					return err
				}
			}
		}
		return nil
	}
	return visit(skills.path("."), true)
}

func activate(state, skills directory, snapshotsPath, id string, names map[string]bool, check func() error, observe checkpoint) error {
	current := skills.path(activeLink)
	previous, err := os.Lstat(current)
	var target string
	switch {
	case errors.Is(err, fs.ErrNotExist):
	case err != nil:
		return err
	case previous.Mode()&fs.ModeSymlink == 0:
		return errors.New("unmanaged skill path: nstack-managed")
	default:
		target, err = os.Readlink(current)
		if err != nil {
			return err
		}
		oldID := filepath.Base(filepath.Dir(target))
		if !snapshotID.MatchString(oldID) || target != filepath.Join(snapshotsPath, oldID, "skills") {
			return errors.New("unmanaged skill path: nstack-managed")
		}
	}
	if err := checkCollisions(skills, names); err != nil {
		return err
	}
	next := filepath.Join(snapshotsPath, id, "skills")
	// The temporary link must be outside skill discovery, even if killed.
	name, scratch, cleanup, err := temp(state, ".activate-")
	if err != nil {
		return err
	}
	defer cleanup()
	if err := os.Symlink(next, scratch.path("link")); err != nil {
		return err
	}
	observe.at("before-activate")
	if err := check(); err != nil {
		return err
	}
	if !matches(scratch.File, state.path(name)) {
		return errors.New("activation directory changed before publication")
	}
	if previous == nil {
		err = renameNew(scratch, "link", skills, activeLink)
	} else {
		info, statErr := os.Lstat(current)
		now, linkErr := os.Readlink(current)
		if statErr != nil || linkErr != nil || !os.SameFile(previous, info) || now != target {
			return errors.New("active skill path changed during activation")
		}
		if target == next {
			return nil
		}
		err = syscall.Renameat(int(scratch.Fd()), "link", int(skills.Fd()), activeLink)
	}
	if err != nil {
		return err
	}
	observe.at("after-activate")
	return nil
}
