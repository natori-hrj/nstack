package workflow

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"
)

type mode uint8

const (
	implement mode = iota
	reviewOnly
	reviewFirst
)

type options struct {
	mode               mode
	repo, base, brief  string
	evidence, workRef  string
	writer, reviewer   Role
	remediations       int
	timeout            time.Duration
	gate               []string
	push, deliveryRef  string
	githubRepo, prBase string
	prTitle            string
	prNumber           int
}

// RoleDefaults supplies harness-specific model IDs and reasoning defaults.
type RoleDefaults struct {
	Writer, Reviewer Role
}

func parse(args []string, help io.Writer, defaults RoleDefaults) (options, error) {
	o := options{writer: Role{Name: "nstack_implement"}, reviewer: Role{Name: "nstack_review"}, remediations: 2}
	flags := flag.NewFlagSet("review", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	auth := flags.Bool("authorize-host", false, "Authorize this invocation under effective host policies")
	only := flags.Bool("review-only", false, "Review without opening a writer")
	first := flags.Bool("review-first", false, "Review HEAD before bounded remediation")
	flags.StringVar(&o.repo, "repo", "", "Checkout root")
	flags.StringVar(&o.base, "base", "", "Comparison revision")
	flags.StringVar(&o.brief, "brief", "", "Task brief")
	flags.StringVar(&o.evidence, "evidence", "", "New directory outside checkout")
	flags.StringVar(&o.workRef, "work-ref", "", "Authorize a new local refs/heads/ branch")
	flags.StringVar(&o.writer.Model, "implement-model", defaults.Writer.Model, "Writer model")
	flags.StringVar(&o.writer.Effort, "implement-effort", defaults.Writer.Effort, "Writer reasoning effort")
	flags.StringVar(&o.reviewer.Model, "review-model", defaults.Reviewer.Model, "Reviewer model")
	flags.StringVar(&o.reviewer.Effort, "review-effort", defaults.Reviewer.Effort, "Reviewer reasoning effort")
	timeout := 600
	decimal := func(name, usage string, target *int) {
		flags.Func(name, usage, func(value string) error {
			number, err := strconv.Atoi(strings.TrimSpace(value))
			if err == nil {
				*target = number
			}
			return err
		})
	}
	decimal("max-remediations", "Maximum remediation rounds (0 to 2, default 2)", &o.remediations)
	decimal("timeout", "Maximum seconds per adapter operation (default 600)", &timeout)
	flags.StringVar(&o.push, "push", "", "Authorized push destination")
	flags.StringVar(&o.deliveryRef, "delivery-ref", "", "Explicit remote refs/heads/ target")
	flags.StringVar(&o.githubRepo, "github-repo", "", "Explicit OWNER/REPO for PR delivery")
	flags.StringVar(&o.prBase, "pr-base", "", "Authorized PR base branch")
	flags.StringVar(&o.prTitle, "pr-title", "", "Draft PR title")
	decimal("pr-number", "Update this existing PR only", &o.prNumber)

	// flag accepts single-dash names and boolean assignments; neither is an
	// authorization form in the original CLI.
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			break
		}
		if !strings.HasPrefix(arg, "-") {
			return o, errors.New("the quality gate must follow --")
		}
		if arg == "-h" || arg == "--help" {
			fmt.Fprintln(help, "Usage: review --authorize-host --repo PATH --base REV --brief FILE --evidence PATH [options] -- GATE [ARG ...]")
			flags.SetOutput(help)
			flags.PrintDefaults()
			return o, flag.ErrHelp
		}
		name, _, assignment := strings.Cut(strings.TrimPrefix(arg, "--"), "=")
		if !strings.HasPrefix(arg, "--") || flags.Lookup(name) == nil {
			return o, fmt.Errorf("unrecognized argument: %s", arg)
		}
		if slices.Contains([]string{"authorize-host", "review-only", "review-first"}, name) {
			if assignment {
				return o, fmt.Errorf("--%s does not take a value", name)
			}
		} else if !assignment {
			i++
			if i == len(args) || strings.HasPrefix(args[i], "--") {
				return o, fmt.Errorf("--%s requires a value", name)
			}
		}
	}
	if err := flags.Parse(args); err != nil {
		return o, err
	}
	switch {
	case !*auth:
		return o, errors.New("--authorize-host is required")
	case o.repo == "" || o.base == "" || o.brief == "" || o.evidence == "":
		return o, errors.New("--repo, --base, --brief and --evidence are required")
	case *only && *first:
		return o, errors.New("--review-only and --review-first are mutually exclusive")
	case o.remediations < 0 || o.remediations > 2:
		return o, errors.New("--max-remediations must be 0, 1 or 2")
	case timeout <= 0 || int64(timeout) > int64(math.MaxInt64/time.Second):
		return o, errors.New("--timeout must be positive and representable")
	case (o.push == "") != (o.deliveryRef == ""):
		return o, errors.New("--push and --delivery-ref must be supplied together")
	}
	provided := map[string]bool{}
	flags.Visit(func(f *flag.Flag) { provided[f.Name] = true })
	if provided["pr-number"] && o.prNumber < 1 {
		return o, errors.New("--pr-number must be positive")
	}
	if provided["pr-number"] && provided["pr-title"] {
		return o, errors.New("--pr-title and --pr-number are mutually exclusive")
	}
	if provided["github-repo"] || provided["pr-base"] || provided["pr-title"] || provided["pr-number"] {
		if o.push == "" || o.githubRepo == "" || o.prBase == "" || (o.prTitle == "" && o.prNumber == 0) {
			return o, errors.New("PR delivery requires --push, --github-repo, --pr-base and --pr-title or --pr-number")
		}
	}
	o.gate = flags.Args()
	if len(o.gate) == 0 {
		return o, errors.New("a quality gate command is required")
	}
	o.timeout = time.Duration(timeout) * time.Second
	if *only {
		o.mode = reviewOnly
	} else if *first {
		o.mode = reviewFirst
	}
	return o, nil
}

func canonical(path string) (string, error) {
	if !filepath.IsAbs(path) {
		cwd, err := os.Getwd()
		if err != nil {
			return "", err
		}
		path = cwd + string(filepath.Separator) + path
	}
	return resolvePath(path)
}

func resolvePath(path string) (string, error) {
	if _, err := os.Lstat(path); err == nil {
		return filepath.EvalSymlinks(path)
	} else if !os.IsNotExist(err) {
		return "", err
	}
	// Do not clean away ".." before resolving a symlink in a parent.
	trimmed := strings.TrimRight(path, string(filepath.Separator))
	last := strings.LastIndexByte(trimmed, filepath.Separator)
	parent, leaf := trimmed[:last+1], trimmed[last+1:]
	resolved, err := resolvePath(parent)
	if err != nil {
		return "", err
	}
	return filepath.Join(resolved, leaf), nil
}

// RunCLI owns validation, exit codes and the terminal evidence record. No
// production adapter is selected implicitly by the core.
func RunCLI(ctx context.Context, args []string, stdout, stderr io.Writer, defaults RoleDefaults, factory AdapterFactory) int {
	o, err := parse(args, stdout, defaults)
	if errors.Is(err, flag.ErrHelp) {
		return 0
	}
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	start := time.Now()
	o.repo, err = canonical(o.repo)
	if err == nil {
		o.evidence, err = canonical(o.evidence)
	}
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	relative, err := filepath.Rel(o.repo, o.evidence)
	if err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		fmt.Fprintln(stderr, "evidence directory must be outside the checkout")
		return 2
	}
	top, err := gitRepo{o.repo}.git(ctx, "rev-parse", "--show-toplevel")
	if err == nil && top != o.repo {
		err = errors.New("repo must be the checkout root")
	}
	if err == nil {
		err = os.Mkdir(o.evidence, 0o700)
	}
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	candidate, err := runLocked(ctx, o, factory)
	if err == nil {
		err = ctx.Err()
	}
	record := Evidence{"status": "pass", "candidate": candidate, "elapsedSeconds": time.Since(start).Seconds()}
	if err != nil {
		record["error"] = err.Error()
		var requested *changesRequested
		if errors.As(err, &requested) {
			record["status"] = "changes_requested"
			record["candidate"] = requested.candidate
		} else {
			record["status"] = "blocked"
			delete(record, "candidate")
		}
	}
	if writeErr := writeEvidence(filepath.Join(o.evidence, "status.json"), record); writeErr != nil {
		fmt.Fprintf(stderr, "workflow blocked: cannot record status: %v (evidence: %s)\n", errors.Join(err, writeErr), o.evidence)
		return 1
	}
	if err != nil {
		if record["status"] == "blocked" {
			fmt.Fprint(stderr, "workflow blocked: ")
		}
		fmt.Fprintf(stderr, "%v (evidence: %s)\n", err, o.evidence)
		return 1
	}
	fmt.Fprintf(stdout, "review passed for %s (evidence: %s)\n", candidate, o.evidence)
	return 0
}
