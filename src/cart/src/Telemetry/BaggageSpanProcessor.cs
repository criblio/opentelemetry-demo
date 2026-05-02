// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System;
using System.Collections.Concurrent;
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
// empty for the server span. By OnEnd, the propagator has run.
//
// Why the SessionScope fallback: StackExchange.Redis dispatches commands
// via a ConnectionMultiplexer that uses worker threads outside the
// request's AsyncLocal flow. Baggage.Current is empty in those threads
// even at OnEnd. Program.cs's EnrichWithHttpRequest callback captures
// session.id into a per-trace-id table on server-span start; Redis child
// spans look it up here by their TraceId.
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

        if (_keyPredicate("session.id") && activity.GetTagItem("session.id") == null)
        {
            var sid = SessionScope.Lookup(activity.TraceId);
            if (sid != null)
            {
                activity.SetTag("session.id", sid);
            }
        }

        if (activity.Parent == null)
        {
            SessionScope.Release(activity.TraceId);
        }
    }
}

internal static class SessionScope
{
    private static readonly ConcurrentDictionary<ActivityTraceId, string> _byTrace = new();

    public static void Capture(ActivityTraceId traceId, string sessionId)
    {
        _byTrace[traceId] = sessionId;
    }

    public static string Lookup(ActivityTraceId traceId)
    {
        return _byTrace.TryGetValue(traceId, out var v) ? v : null;
    }

    public static void Release(ActivityTraceId traceId)
    {
        _byTrace.TryRemove(traceId, out _);
    }
}
