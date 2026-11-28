package distribution

import (
	"bytes"
	"io/fs"
	"os"
	"os/exec"
	"strings"
	"testing"
)

func TestBundledAssets(t *testing.T) {
	paths, err := exec.Command("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
		"skills", "adapters", "docs", "examples/agents",
		"LICENSE", "LICENSE-upstream", "README.md", "README.ja.md", manifest).Output()
	if err != nil {
		t.Fatal(err)
	}
	expected := make(map[string]bool)
	for _, path := range strings.Split(strings.TrimSuffix(string(paths), "\x00"), "\x00") {
		expected[path] = true
	}
	if err := fs.WalkDir(content, ".", func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		if !expected[path] {
			t.Errorf("untracked or unexpected embedded asset %s", path)
		}
		delete(expected, path)
		embedded, err := content.ReadFile(path)
		if err != nil {
			return err
		}
		actual, err := os.ReadFile(path)
		if err == nil && !bytes.Equal(embedded, actual) {
			t.Errorf("embedded contents differ: %s", path)
		}
		return err
	}); err != nil {
		t.Fatal(err)
	}
	if len(expected) != 0 {
		t.Fatalf("missing embedded assets: %v", expected)
	}
}
