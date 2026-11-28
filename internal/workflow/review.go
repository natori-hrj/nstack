package workflow

import (
	"encoding/json"
	"errors"
	"io"
	"strings"
)

const reviewProperties = `
    "candidate":{"type":"string"},
    "verdict":{"type":"string","enum":["pass","changes_requested","blocked"]},
    "findings":{"type":"array","items":{"type":"object","additionalProperties":false,
        "required":["location","evidence","expected","impact"],
        "properties":{"location":{"type":"string"},"evidence":{"type":"string"},
            "expected":{"type":"string"},"impact":{"type":"string"}}}}`

const previousProperty = `
    "previous":{"type":"array","items":{"type":"object","additionalProperties":false,
        "required":["id","status","evidence"],"properties":{"id":{"type":"string"},
        "status":{"type":"string","enum":["resolved","recurring","uncertain"]},"evidence":{"type":"string"}}}}`

func reviewSchema(tracked bool) json.RawMessage {
	prefix := `{"type":"object","additionalProperties":false,`
	if tracked {
		return json.RawMessage(prefix + `"required":["candidate","verdict","findings","previous"],"properties":{` +
			reviewProperties + "," + previousProperty + "}}")
	}
	return json.RawMessage(prefix + `"required":["candidate","verdict","findings"],"properties":{` +
		reviewProperties + "}}")
}

type finding map[string]string
type findingRegistry map[string]recordedFinding

type recordedFinding struct {
	Location string `json:"initialLocation"`
	Contract string `json:"contract"`
	Failure  string `json:"failure"`
	Evidence string `json:"initialEvidence"`
}

type verdict struct {
	Status   string
	Findings []finding
	Previous []map[string]string
	Raw      json.RawMessage
}

// Keep candidate evidence unambiguous for consumers that decode duplicate
// member names differently.
func uniqueObject[T any](raw []byte) (map[string]T, bool) {
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return nil, false
	}
	fields := map[string]T{}
	for decoder.More() {
		key, err := decoder.Token()
		name, ok := key.(string)
		var value T
		if _, repeated := fields[name]; err != nil || !ok || repeated || decoder.Decode(&value) != nil {
			return nil, false
		}
		fields[name] = value
	}
	if _, err := decoder.Token(); err != nil {
		return nil, false
	}
	_, err = decoder.Token()
	return fields, errors.Is(err, io.EOF)
}

func validateVerdict(text, candidate string, registry findingRegistry) (verdict, error) {
	var result verdict
	fields, ok := uniqueObject[json.RawMessage]([]byte(text))
	if !ok {
		return result, errors.New("invalid structured review result")
	}
	tracked := registry != nil
	expected := 3
	if tracked {
		expected++
	}
	if len(fields) != expected || fields["candidate"] == nil || fields["verdict"] == nil ||
		fields["findings"] == nil || (tracked && fields["previous"] == nil) {
		return result, errors.New("invalid structured review result")
	}
	var reported string
	var findings []json.RawMessage
	if json.Unmarshal(fields["candidate"], &reported) != nil || reported != candidate ||
		json.Unmarshal(fields["verdict"], &result.Status) != nil ||
		(result.Status != "pass" && result.Status != "changes_requested" && result.Status != "blocked") ||
		json.Unmarshal(fields["findings"], &findings) != nil || findings == nil {
		return result, errors.New("review verdict does not match the candidate or findings")
	}
	for _, raw := range findings {
		f, ok := uniqueObject[string](raw)
		if !ok || len(f) != 4 || strings.TrimSpace(f["location"]) == "" || strings.TrimSpace(f["evidence"]) == "" ||
			strings.TrimSpace(f["expected"]) == "" || strings.TrimSpace(f["impact"]) == "" {
			return result, errors.New("incomplete independent review finding")
		}
		result.Findings = append(result.Findings, f)
	}
	if !tracked {
		if (result.Status == "pass") != (len(result.Findings) == 0) {
			return result, errors.New("review verdict does not match the findings")
		}
	} else if err := validatePrevious(fields["previous"], registry, &result); err != nil {
		return result, err
	}
	result.Raw = json.RawMessage(text)
	return result, nil
}

func validatePrevious(raw json.RawMessage, registry findingRegistry, result *verdict) error {
	var previous []json.RawMessage
	if json.Unmarshal(raw, &previous) != nil || previous == nil {
		return errors.New("review did not assess previous finding IDs")
	}
	seen := make(map[string]bool, len(registry))
	outstanding := len(result.Findings) != 0
	for _, raw := range previous {
		a, ok := uniqueObject[string](raw)
		id, status := a["id"], a["status"]
		_, registered := registry[id]
		if !ok || len(a) != 3 || !registered || seen[id] || strings.TrimSpace(a["evidence"]) == "" ||
			(status != "resolved" && status != "recurring" && status != "uncertain") {
			return errors.New("invalid or unexpected previous finding assessment")
		}
		seen[id] = true
		outstanding = outstanding || status != "resolved"
		result.Previous = append(result.Previous, a)
	}
	if len(seen) != len(registry) {
		return errors.New("review did not assess every previous finding ID")
	}
	if result.Status != "blocked" && (result.Status == "pass") == outstanding {
		return errors.New("review verdict does not match the finding assessments")
	}
	return nil
}
