// Package workflow coordinates implementation, independent review, and
// authorized delivery. Host-specific permissions are enforced by the adapter.
package workflow

import (
	"context"
	"encoding/json"
	"time"
)

type Role struct {
	Name   string `json:"name"`
	Model  string `json:"model"`
	Effort string `json:"effort"`
}

type Evidence map[string]any

type GateRequest struct {
	Directory string
	Argv      []string
	Scratch   string
	Evidence  string
}

type GateResult struct {
	// Nil means the adapter did not observe a terminal exit code.
	ExitCode *int
	Evidence Evidence
}

type TurnRequest struct {
	Directory string
	Role      Role
	Prompt    string
	Evidence  string
	// A schema requests a fresh, isolated, read-only independent review.
	Schema json.RawMessage
}

type TurnResult struct {
	Session  string
	Model    string
	Effort   string
	Message  string
	Evidence Evidence
}

// HarnessAdapter owns the lifecycle of its sessions and processes. Preflight
// must verify the requested role, read-only isolation, and quality-gate policy.
// Run must verify the effective role and permissions, and return only after a
// completed turn. A nonempty schema requires native schema enforcement.
// Missing capabilities, reroutes and uncertain terminal states must return
// errors. Cancellation must stop owned work before returning.
type HarnessAdapter interface {
	Name() string
	Preflight(ctx context.Context, directory string, reviewer Role, evidence string) (Evidence, error)
	Run(context.Context, TurnRequest) (TurnResult, error)
}

// GateRunner enforces the allowed scratch/workspace writes and network policy
// and stops owned commands on cancellation.
type GateRunner interface {
	Gate(context.Context, GateRequest) (GateResult, error)
}

type Adapter interface {
	HarnessAdapter
	GateRunner
}

type AdapterFactory func(timeout time.Duration) (Adapter, error)
