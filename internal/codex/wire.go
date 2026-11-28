package codex

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
)

// unmarshalWire ignores unknown fields, but does not let encoding/json match
// case-insensitive aliases for protocol fields. Dynamic map keys keep their case.
func unmarshalWire(raw json.RawMessage, dst any) error {
	if err := checkWireNames(raw, reflect.TypeOf(dst).Elem()); err != nil {
		return err
	}
	return json.Unmarshal(raw, dst)
}

func checkWireNames(raw json.RawMessage, target reflect.Type) error {
	if !nonnull(raw) || target == reflect.TypeFor[json.RawMessage]() {
		return nil
	}
	switch target.Kind() {
	case reflect.Pointer:
		return checkWireNames(raw, target.Elem())
	case reflect.Struct, reflect.Map:
		if target.Kind() == reflect.Map && target.Elem().Kind() == reflect.Interface {
			return nil
		}
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			return err
		}
		for name, value := range fields {
			if target.Kind() == reflect.Map {
				if err := checkWireNames(value, target.Elem()); err != nil {
					return err
				}
				continue
			}
			for i := range target.NumField() {
				field := target.Field(i)
				canonical, _, _ := strings.Cut(field.Tag.Get("json"), ",")
				if canonical == "" {
					canonical = field.Name
				}
				if !strings.EqualFold(name, canonical) {
					continue
				}
				if name != canonical {
					return fmt.Errorf("noncanonical Codex field %q; expected %q", name, canonical)
				}
				if err := checkWireNames(value, field.Type); err != nil {
					return err
				}
				break
			}
		}
	case reflect.Slice:
		var items []json.RawMessage
		if err := json.Unmarshal(raw, &items); err != nil {
			return err
		}
		for _, item := range items {
			if err := checkWireNames(item, target.Elem()); err != nil {
				return err
			}
		}
	}
	return nil
}
