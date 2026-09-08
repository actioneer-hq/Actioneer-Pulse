package main

import "regexp"

// sanitize mirrors db/session.py _sanitize: lowercase, and any char outside [a-z0-9_] -> _.
var nonSchemaChar = regexp.MustCompile(`[^a-z0-9_]`)

func sanitizeSlug(slug string) string {
	if slug == "" {
		slug = "default"
	}
	return nonSchemaChar.ReplaceAllString(toLowerASCII(slug), "_")
}

// schemaName is the tenant schema for an org slug: t_<sanitized>. Matches org_schema().
func schemaName(slug string) string { return "t_" + sanitizeSlug(slug) }

func toLowerASCII(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + ('a' - 'A')
		}
	}
	return string(b)
}
