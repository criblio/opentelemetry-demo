// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System;
using System.Diagnostics;
using OpenTelemetry;

namespace cart.telemetry;

// Mirrors the contrib BaggageSpanProcessor pattern available in
// Python/JS/Java but absent from OpenTelemetry .NET as of SDK 1.11.
// Copies allow-listed baggage entries from the current context onto every
// activity at start time, so APM backends can group/filter by them.
public class BaggageSpanProcessor : BaseProcessor<Activity>
{
    private readonly Func<string, bool> _keyPredicate;

    public BaggageSpanProcessor(Func<string, bool> keyPredicate)
    {
        _keyPredicate = keyPredicate;
    }

    public override void OnStart(Activity activity)
    {
        foreach (var entry in Baggage.Current)
        {
            if (_keyPredicate(entry.Key))
            {
                activity.SetTag(entry.Key, entry.Value);
            }
        }
    }
}
