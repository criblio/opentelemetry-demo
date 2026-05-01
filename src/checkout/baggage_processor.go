// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package main

import (
	"context"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/baggage"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// baggageSpanProcessor copies a single baggage entry onto every span it sees
// at start time. Mirrors the contrib BaggageSpanProcessor pattern available
// in Python/JS/Java but absent from Go contrib as of OTel SDK 1.37.
type baggageSpanProcessor struct {
	key string
}

func newBaggageSpanProcessor(key string) *baggageSpanProcessor {
	return &baggageSpanProcessor{key: key}
}

func (b *baggageSpanProcessor) OnStart(ctx context.Context, span sdktrace.ReadWriteSpan) {
	if v := baggage.FromContext(ctx).Member(b.key).Value(); v != "" {
		span.SetAttributes(attribute.String(b.key, v))
	}
}

func (b *baggageSpanProcessor) OnEnd(_ sdktrace.ReadOnlySpan)               {}
func (b *baggageSpanProcessor) Shutdown(_ context.Context) error            { return nil }
func (b *baggageSpanProcessor) ForceFlush(_ context.Context) error          { return nil }
