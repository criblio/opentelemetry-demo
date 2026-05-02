// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System;
using System.Diagnostics;
using OpenTelemetry;

namespace cart.telemetry;

// Mirrors the contrib BaggageSpanProcessor pattern available in
// Python/JS/Java but absent from OpenTelemetry .NET as of SDK 1.11.
// Copies allow-listed baggage entries from the current context onto every
// activity, so APM backends can group/filter by them.
//
// Why OnEnd, not OnStart: in OpenTelemetry .NET's AspNetCore instrumentation
// the inbound server Activity is created by ASP.NET Core *before* the
// HttpInListener observes the diagnostic event and extracts baggage from
// headers into Baggage.Current. So at OnStart, Baggage.Current is still
// empty for the server span. By OnEnd, the propagator has run and
// (for child activities created during the request) AsyncLocal context
// has had a chance to restore from sync Redis-style thread hops too.
public class BaggageSpanProcessor : BaseProcessor<Activity>
{
    private readonly Func<string, bool> _keyPredicate;

    public BaggageSpanProcessor(Func<string, bool> keyPredicate)
    {
        _keyPredicate = keyPredicate;
    }

    public override void OnEnd(Activity activity)
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
