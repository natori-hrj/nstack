package workflow

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type testAdapter struct {
	preflight func(context.Context) (Evidence, error)
	gate      func() GateResult
	run       func(context.Context, TurnRequest) (TurnResult, error)
}

func (testAdapter) Name() string { return "test" }
func (a testAdapter) Preflight(ctx context.Context, _ string, _ Role, _ string) (Evidence, error) {
	if a.preflight != nil {
		return a.preflight(ctx)
	}
	return Evidence{"readOnly": true}, nil
}
func (a testAdapter) Gate(context.Context, GateRequest) (GateResult, error) {
	if a.gate != nil {
		return a.gate(), nil
	}
	code := 0
	return GateResult{ExitCode: &code}, nil
}
func (a testAdapter) Run(ctx context.Context, request TurnRequest) (TurnResult, error) {
	return a.run(ctx, request)
}

type checkoutFixture struct {
	gitRepo
	base, head, evidence, brief string
}

func testCheckout(t *testing.T) checkoutFixture {
	t.Helper()
	dir := t.TempDir()
	r := gitRepo{filepath.Join(dir, "repo")}
	if err := os.Mkdir(r.directory, 0o700); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	git := func(args ...string) string {
		t.Helper()
		value, err := r.git(ctx, args...)
		if err != nil {
			t.Fatalf("git %v: %v", args, err)
		}
		return value
	}
	git("init", "-q", "-b", "fixture")
	git("config", "core.hooksPath", "/dev/null")
	git("config", "user.name", "Fixture")
	git("config", "user.email", "fixture@example.invalid")
	git("config", "commit.gpgsign", "false")
	git("commit", "-qm", "base", "--allow-empty")
	base := git("rev-parse", "HEAD")
	git("commit", "-qm", "candidate", "--allow-empty")
	task := filepath.Join(dir, "task")
	if err := os.WriteFile(task, []byte("Review fixture"), 0o600); err != nil {
		t.Fatal(err)
	}
	return checkoutFixture{r, base, git("rev-parse", "HEAD"), filepath.Join(dir, "evidence"), task}
}

func (f checkoutFixture) args(extra ...string) []string {
	args := []string{"--authorize-host", "--repo", f.directory, "--base", f.base, "--brief", f.brief, "--evidence", f.evidence}
	return append(append(args, extra...), "--", "fixture-gate")
}

func (f checkoutFixture) blocked(t *testing.T, reason string) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(f.evidence, "status.json"))
	if err != nil {
		t.Fatal(err)
	}
	var result struct{ Status, Error string }
	if err := json.Unmarshal(raw, &result); err != nil {
		t.Fatal(err)
	}
	if result.Status != "blocked" || !strings.Contains(result.Error, reason) {
		t.Fatalf("status = %s", raw)
	}
}

func TestRunCLIRejectsUnverifiedOrCancelledReview(t *testing.T) {
	for _, name := range []string{"wrong-role", "missing-session", "cancelled"} {
		t.Run(name, func(t *testing.T) {
			f := testCheckout(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			adapter := testAdapter{run: func(ctx context.Context, req TurnRequest) (TurnResult, error) {
				if _, bounded := ctx.Deadline(); !bounded || !json.Valid(req.Schema) {
					t.Fatal("adapter did not receive a deadline and review schema")
				}
				result := TurnResult{Session: "review-1", Model: req.Role.Model, Effort: req.Role.Effort,
					Message: fmt.Sprintf(`{"candidate":%q,"verdict":"pass","findings":[]}`, f.head)}
				switch name {
				case "wrong-role":
					result.Model = "unexpected"
				case "missing-session":
					result.Session = ""
				case "cancelled":
					cancel() // Even a plausible result after cancellation is not success.
				}
				return result, nil
			}}
			var out, stderr bytes.Buffer
			code := RunCLI(ctx, f.args("--review-only"), &out, &stderr,
				func(time.Duration) (Adapter, error) { return adapter, nil })
			if code != 1 || out.Len() != 0 {
				t.Fatalf("exit=%d stdout=%q stderr=%q", code, &out, &stderr)
			}
			reason := "requested role or session"
			if name == "cancelled" {
				reason = "context canceled"
			}
			f.blocked(t, reason)
			raw, err := os.ReadFile(filepath.Join(f.evidence, "0-review.json"))
			if err != nil {
				t.Fatal(err)
			}
			var record struct{ Candidate, Base, Message, ValidationError string }
			if err := json.Unmarshal(raw, &record); err != nil || record.Candidate != f.head ||
				record.Base != f.base || !strings.Contains(record.Message, f.head) ||
				!strings.Contains(record.ValidationError, reason) {
				t.Fatalf("invalid attempt evidence: %v %s", err, raw)
			}
			if head, err := f.gitRepo.head(context.Background()); err != nil || head != f.head {
				t.Fatalf("HEAD changed: %q, %v", head, err)
			}
		})
	}
}

func TestTimeoutPreventsWriterAuthorizationFromTakingEffect(t *testing.T) {
	f := testCheckout(t)
	adapter := testAdapter{preflight: func(ctx context.Context) (Evidence, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}}
	var out, stderr bytes.Buffer
	code := RunCLI(context.Background(), f.args("--timeout", "1", "--work-ref", "refs/heads/new"), &out, &stderr,
		func(time.Duration) (Adapter, error) { return adapter, nil })
	if code != 1 || out.Len() != 0 {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, &out, &stderr)
	}
	f.blocked(t, "deadline exceeded")
	if ref, err := f.git(context.Background(), "for-each-ref", "--format=%(refname)", "refs/heads/new"); err != nil || ref != "" {
		t.Fatalf("writer ref exists or could not be checked: %q, %v", ref, err)
	}
}

func TestCLIRequiresExplicitAuthorizationAndDecimalPRNumber(t *testing.T) {
	f := testCheckout(t)
	for _, authorization := range []string{"-authorize-host", "--authorize-host=true"} {
		args := f.args("--review-only")
		args[0] = authorization
		var out, stderr bytes.Buffer
		if code := RunCLI(context.Background(), args, &out, &stderr, nil); code != 2 {
			t.Fatalf("%s: exit=%d stderr=%q", authorization, code, &stderr)
		}
	}
	pr := []string{"--push", "remote", "--delivery-ref", "refs/heads/feature",
		"--github-repo", "owner/repo", "--pr-base", "main", "--pr-number"}
	approved, err := parse(f.args(append(pr, "08")...), &bytes.Buffer{})
	if err != nil || approved.prNumber != 8 {
		t.Fatalf("decimal PR number not preserved: %#v, %v", approved, err)
	}
	if _, err := parse(f.args(append(pr, "0x8")...), &bytes.Buffer{}); err == nil {
		t.Fatal("accepted an undocumented authorization number")
	}
	if _, err := os.Stat(f.evidence); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unexpected evidence: %v", err)
	}
}

func TestMissingGateSeparatorNeverOpensWriter(t *testing.T) {
	f := testCheckout(t)
	args := f.args("--work-ref", "refs/heads/new")
	args = append(args[:len(args)-2], "true", "--review-only")
	var out, stderr bytes.Buffer
	if code := RunCLI(context.Background(), args, &out, &stderr, func(time.Duration) (Adapter, error) {
		t.Fatal("an ambiguous invocation dispatched the adapter")
		return nil, nil
	}); code != 2 || !strings.Contains(stderr.String(), "must follow --") {
		t.Fatalf("exit=%d stderr=%q", code, &stderr)
	}
	if _, err := os.Stat(f.evidence); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unexpected evidence: %v", err)
	}
}

func TestGateWithoutTerminalCodeDoesNotDispatchReview(t *testing.T) {
	f := testCheckout(t)
	adapter := testAdapter{
		gate: func() GateResult { return GateResult{Evidence: Evidence{"exitCode": 0}} },
		run: func(context.Context, TurnRequest) (TurnResult, error) {
			t.Fatal("review ran without an observed gate exit code")
			return TurnResult{}, nil
		},
	}
	var out, stderr bytes.Buffer
	code := RunCLI(context.Background(), f.args("--review-only"), &out, &stderr,
		func(time.Duration) (Adapter, error) { return adapter, nil })
	if code != 1 {
		t.Fatalf("exit=%d stderr=%q", code, &stderr)
	}
	f.blocked(t, "missing an exit code")
	raw, err := os.ReadFile(filepath.Join(f.evidence, "0-gate.json"))
	if err != nil || strings.Contains(string(raw), `"exitCode"`) || !strings.Contains(string(raw), `"validationError"`) {
		t.Fatalf("invalid gate evidence: %v %s", err, raw)
	}
}

func TestBlankRoleCannotAuthorizeWorkflow(t *testing.T) {
	cases := []struct {
		name string
		args []string
	}{
		{"review-model", []string{"--review-only", "--review-model="}},
		{"review-effort", []string{"--review-only", "--review-effort= "}},
		{"writer-model", []string{"--work-ref", "refs/heads/new", "--implement-model="}},
		{"writer-effort", []string{"--work-ref", "refs/heads/new", "--implement-effort= "}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := testCheckout(t)
			ctx := context.Background()
			remote := filepath.Join(filepath.Dir(f.directory), "remote.git")
			if _, err := f.git(ctx, "clone", "--bare", "--no-local", f.directory, remote); err != nil {
				t.Fatal(err)
			}
			adapter := testAdapter{run: func(_ context.Context, req TurnRequest) (TurnResult, error) {
				return TurnResult{Session: "echoed", Model: req.Role.Model, Effort: req.Role.Effort,
					Message: fmt.Sprintf(`{"candidate":%q,"verdict":"pass","findings":[]}`, f.head)}, nil
			}}
			args := f.args(append(tc.args, "--push", remote, "--delivery-ref", "refs/heads/delivered")...)
			var out, stderr bytes.Buffer
			if code := RunCLI(ctx, args, &out, &stderr, func(time.Duration) (Adapter, error) {
				return adapter, nil
			}); code != 1 || out.Len() != 0 {
				t.Fatalf("exit=%d stdout=%q stderr=%q", code, &out, &stderr)
			}
			f.blocked(t, "model and reasoning effort must not be blank")
			if ref, err := (gitRepo{remote}).git(ctx, "for-each-ref", "--format=%(refname)", "refs/heads/delivered"); err != nil || ref != "" {
				t.Fatalf("unexpected delivery ref: %q, %v", ref, err)
			}
			if ref, err := f.ref(ctx); err != nil || ref != "refs/heads/fixture" {
				t.Fatalf("unexpected writer ref: %q, %v", ref, err)
			}
		})
	}
}

func TestRejectsEvidenceInsideCheckoutThroughSymlink(t *testing.T) {
	f := testCheckout(t)
	subdir := filepath.Join(f.directory, "inside")
	if err := os.Mkdir(subdir, 0o700); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(filepath.Dir(f.directory), "link")
	if err := os.Symlink(subdir, link); err != nil {
		t.Fatal(err)
	}
	f.evidence = link + "/../evidence"
	var out, stderr bytes.Buffer
	if code := RunCLI(context.Background(), f.args("--review-only"), &out, &stderr, nil); code != 2 {
		t.Fatalf("exit=%d stderr=%q", code, &stderr)
	}
	if _, err := os.Stat(filepath.Join(f.directory, "evidence")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("unexpected checkout evidence: %v", err)
	}
}

func TestCheckoutLockPreventsSecondDispatch(t *testing.T) {
	f := testCheckout(t)
	ctx := context.Background()
	lock, err := f.lock(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Close()
	var out, stderr bytes.Buffer
	code := RunCLI(ctx, f.args("--review-only"), &out, &stderr, func(time.Duration) (Adapter, error) {
		t.Fatal("adapter was dispatched under an existing lock")
		return nil, nil
	})
	if code != 1 {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, &out, &stderr)
	}
	f.blocked(t, "another nstack review workflow owns this checkout")
}

func TestVerdictValidationRejectsAmbiguousOrIncompleteEvidence(t *testing.T) {
	candidate := strings.Repeat("a", 40)
	pass := fmt.Sprintf(`{"candidate":%q,"verdict":"pass","findings":[]}`, candidate)
	if _, err := validateVerdict(pass, candidate, nil); err != nil {
		t.Fatal(err)
	}
	cases := map[string]string{
		"wrong candidate": strings.Replace(pass, candidate, strings.Repeat("b", 40), 1),
		"duplicate":       strings.TrimSuffix(pass, "}") + `,"candidate":"wrong"}`,
		"trailing":        pass + ` {}`,
		"null findings":   strings.Replace(pass, "[]", "null", 1),
		"false pass":      strings.Replace(pass, "[]", `[{"location":"source","evidence":"failure","expected":"ok","impact":"blocked"}]`, 1),
		"bad finding": strings.Replace(strings.Replace(pass, `"pass"`, `"changes_requested"`, 1), "[]",
			`[{"location":"source","evidence":"one","evidence":"two","expected":"ok","impact":"blocked"}]`, 1),
	}
	for name, raw := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := validateVerdict(raw, candidate, nil); err == nil {
				t.Fatalf("accepted %s", raw)
			}
		})
	}
	if _, err := validateVerdict(strings.TrimSuffix(pass, "}")+`,"previous":[]}`, candidate, findingRegistry{"F1": {}}); err == nil {
		t.Fatal("accepted an omitted prior finding")
	}
}
