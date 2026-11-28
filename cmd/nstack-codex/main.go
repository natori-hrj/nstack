// Command nstack-codex runs the review workflow against the Codex app-server.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/natori-hrj/nstack/internal/codex"
	"github.com/natori-hrj/nstack/internal/workflow"
)

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: nstack-codex {review|check-role} [arguments]")
		return 2
	}
	switch os.Args[1] {
	case "review":
		return workflow.RunCLI(ctx, os.Args[2:], os.Stdout, os.Stderr, codex.Defaults(), codex.New)
	case "check-role":
		return codex.CheckRoleCLI(os.Args[2:], os.Stdin, os.Stdout, os.Stderr)
	default:
		fmt.Fprintln(os.Stderr, "expected review or check-role")
		return 2
	}
}

func main() { os.Exit(run()) }
