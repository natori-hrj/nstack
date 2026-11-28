package codex

import (
	"encoding/json"
	"errors"
	"strings"

	"github.com/natori-hrj/nstack/internal/workflow"
)

type turnState struct {
	ID     string          `json:"id"`
	Status string          `json:"status"`
	Error  json.RawMessage `json:"error"`
}

type turnStream struct {
	thread, turn, message string
	usage                 json.RawMessage
	completed             bool
}

func (t *turnStream) observe(f frame) error {
	switch f.Method {
	case "turn/completed", "item/completed", "thread/tokenUsage/updated":
	default:
		return nil
	}
	var event struct {
		ThreadID string    `json:"threadId"`
		TurnID   string    `json:"turnId"`
		Turn     turnState `json:"turn"`
		Item     struct {
			Type  string `json:"type"`
			Phase string `json:"phase"`
			Text  string `json:"text"`
		} `json:"item"`
		TokenUsage struct {
			Total json.RawMessage `json:"total"`
		} `json:"tokenUsage"`
	}
	if err := unmarshalWire(f.Params, &event); err != nil || event.ThreadID == "" {
		return unexpectedTurn("notification has no valid thread")
	}
	if event.ThreadID != t.thread {
		return nil
	}
	id := event.TurnID
	if f.Method == "turn/completed" {
		id = event.Turn.ID
	}
	if strings.TrimSpace(id) == "" {
		return unexpectedTurn("notification has no turn ID")
	}
	if id != t.turn {
		return nil
	}
	switch f.Method {
	case "turn/completed":
		if t.completed || event.Turn.Status != "completed" || string(event.Turn.Error) != "null" {
			return errors.New("Codex did not complete the turn unambiguously")
		}
		t.completed = true
	case "item/completed":
		if t.completed {
			return unexpectedTurn("item completed after the turn ended")
		}
		switch event.Item.Type {
		case "":
			return unexpectedTurn("completed item has no type")
		case "mcpToolCall", "collabAgentToolCall":
			return errors.New("unexpected Codex tool outside this workflow")
		case "agentMessage":
			if event.Item.Phase != "commentary" {
				t.message = event.Item.Text
			}
		}
	case "thread/tokenUsage/updated":
		if !t.completed {
			t.usage = event.TokenUsage.Total
		}
	}
	return nil
}

func (t *turnStream) run(s *server, req workflow.TurnRequest) error {
	var result struct {
		Turn turnState `json:"turn"`
	}
	var pending []frame
	var size int
	err := s.request("turn/start", object{
		"threadId": t.thread, "input": []object{{"type": "text", "text": req.Prompt, "text_elements": []any{}}},
		"outputSchema": req.Schema,
	}, &result, func(f frame) error {
		switch f.Method {
		case "turn/completed", "item/completed", "thread/tokenUsage/updated":
			size += len(f.Params)
			if size > 8<<20 || len(pending) >= 4096 {
				return unexpectedTurn("too many notifications before turn acknowledgement")
			}
			pending = append(pending, f)
		}
		return nil
	})
	if err != nil {
		return err
	}
	t.turn = result.Turn.ID
	if strings.TrimSpace(t.turn) == "" {
		return unexpectedTurn("missing turn ID")
	}
	for _, f := range pending {
		if err := t.observe(f); err != nil {
			return err
		}
	}
	for !t.completed {
		f, err := s.receive()
		if err != nil {
			return err
		}
		if f.Method == "" {
			return unexpectedTurn("unsolicited or duplicate response")
		}
		if err := t.observe(f); err != nil {
			return err
		}
	}
	if strings.TrimSpace(t.message) == "" {
		return errors.New("Codex completed without a final message")
	}
	// A trailing request flushes already queued frames before accepting the
	// verdict, so a duplicate turn response after completion is also rejected.
	var config object
	return s.request("config/read", object{"cwd": req.Directory}, &config, t.observe)
}
