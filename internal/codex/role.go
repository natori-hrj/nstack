package codex

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/natori-hrj/nstack/internal/workflow"
)

func Defaults() workflow.RoleDefaults {
	return workflow.RoleDefaults{
		Writer:   workflow.Role{Model: "gpt-6.2-sol", Effort: "medium"},
		Reviewer: workflow.Role{Model: "gpt-6.2-astra", Effort: "medium"},
	}
}

const optionalRole = "nstack_security_daybreak"

type model struct {
	ID        string `json:"model"`
	Specialty string `json:"modelSpecialty"`
	Hidden    bool   `json:"hidden"`
	Programs  struct {
		Cyber []string `json:"cyber"`
	} `json:"availableAccessPrograms"`
	Efforts []struct {
		Effort string `json:"reasoningEffort"`
	} `json:"supportedReasoningEfforts"`
}

type modelPage struct {
	Data   []model `json:"data"`
	Cursor *string `json:"nextCursor"`
}

func checkModel(role workflow.Role, catalog []model, selected bool) error {
	if strings.TrimSpace(role.Model) == "" {
		return errors.New("resolve the inherited model in the active session before dispatch")
	}
	if role.Name == optionalRole && !selected {
		return errors.New("explicitly select the Daybreak route for an authorized defensive task")
	}
	for _, m := range catalog {
		if m.ID != role.Model {
			continue
		}
		if role.Name == optionalRole || m.Specialty == "cyber" {
			if role.Name != optionalRole {
				return fmt.Errorf("%s requires the optional defensive role", role.Model)
			}
			available := false
			for _, program := range m.Programs.Cyber {
				if program == "daybreakBlue" {
					available = true
				}
			}
			if !available {
				return fmt.Errorf("%s does not advertise Daybreak Blue for this account and client", role.Model)
			}
		} else if m.Hidden {
			return fmt.Errorf("%s is hidden in the active model catalog", role.Model)
		}
		if m.Efforts == nil {
			return fmt.Errorf("%s did not report supported reasoning efforts", role.Model)
		}
		if role.Effort == "" {
			return nil
		}
		for _, effort := range m.Efforts {
			if effort.Effort == role.Effort {
				return nil
			}
		}
		return fmt.Errorf("%s does not advertise reasoning effort %s", role.Model, role.Effort)
	}
	return fmt.Errorf("%s is absent from the active model catalog", role.Model)
}

func (s *server) checkRole(role workflow.Role) error {
	var cursor *string
	var catalog []model
	seen := map[string]bool{}
	for {
		var page modelPage
		if err := s.request("model/list", object{"modelProvider": "openai", "cursor": cursor, "includeHidden": true}, &page, nil); err != nil {
			return err
		}
		if page.Data == nil {
			return errors.New("Codex model catalog did not contain model data")
		}
		catalog = append(catalog, page.Data...)
		cursor = page.Cursor
		if cursor == nil || *cursor == "" {
			return checkModel(role, catalog, false)
		}
		if seen[*cursor] || len(seen) >= 128 {
			return errors.New("invalid Codex model catalog pagination")
		}
		seen[*cursor] = true
	}
}

func readRole(path, fallbackModel, fallbackEffort string) (workflow.Role, error) {
	// Resolve only exact top-level keys, as Python does. The TOML
	// decoder's Go struct mapping also accepts case-insensitive matches.
	var file map[string]any
	if _, err := toml.DecodeFile(path, &file); err != nil {
		return workflow.Role{}, err
	}
	role := workflow.Role{Model: fallbackModel, Effort: fallbackEffort}
	for _, field := range []struct {
		key string
		dst *string
	}{
		{"name", &role.Name},
		{"model", &role.Model},
		{"model_reasoning_effort", &role.Effort},
	} {
		if raw, exists := file[field.key]; exists {
			value, ok := raw.(string)
			if !ok {
				return workflow.Role{}, fmt.Errorf("role %s must be a string", field.key)
			}
			*field.dst = value
		}
	}
	if strings.TrimSpace(role.Name) == "" {
		return workflow.Role{}, errors.New("role name is required")
	}
	return role, nil
}

func readCatalog(in io.Reader) ([]model, error) {
	const limit = 8 << 20
	data, err := io.ReadAll(io.LimitReader(in, limit+1))
	if err != nil {
		return nil, err
	}
	if len(data) > limit {
		return nil, errors.New("model catalog exceeded size limit")
	}
	var envelope struct {
		Result json.RawMessage `json:"result"`
	}
	if err := decode(data, &envelope); err != nil {
		return nil, err
	}
	if len(envelope.Result) != 0 {
		data = envelope.Result
	}
	var page modelPage
	if err := unmarshalWire(data, &page); err != nil {
		return nil, err
	}
	if page.Cursor != nil && *page.Cursor != "" {
		return nil, errors.New("collect all model/list pages before checking a role")
	}
	if page.Data == nil {
		return nil, errors.New("model catalog did not contain model data")
	}
	return page.Data, nil
}

// CheckRoleCLI checks advertised capabilities only; it does not start Codex
// or select an access program.
func CheckRoleCLI(args []string, in io.Reader, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("check-role", flag.ContinueOnError)
	flags.SetOutput(stderr)
	inheritedModel := flags.String("inherited-model", "", "Effective active model")
	effort := flags.String("inherited-effort", "", "Effective active reasoning effort")
	selected := flags.Bool("daybreak-selected", false, "Verify explicit selection in a supplied catalog")
	err := flags.Parse(args)
	var path string
	if err == nil && flags.NArg() != 0 {
		path = flags.Arg(0)
		// A role path is allowed before, after, or between flags, as
		// in the Python command. Parse the remaining flags in place.
		err = flags.Parse(flags.Args()[1:])
	}
	if err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return 2
	}
	if path == "" || flags.NArg() != 0 {
		fmt.Fprintln(stderr, "check-role requires exactly one role TOML path")
		return 2
	}
	role, err := readRole(path, *inheritedModel, *effort)
	if err == nil {
		var catalog []model
		catalog, err = readCatalog(in)
		if err == nil {
			err = checkModel(role, catalog, *selected)
		}
	}
	if err != nil {
		fmt.Fprintf(stderr, "role unavailable: %v\n", err)
		return 1
	}
	fmt.Fprintf(stdout, "%s: %s advertised (provider response unverified)\n", role.Name, role.Model)
	return 0
}
