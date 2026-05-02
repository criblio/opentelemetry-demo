// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Threading;
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
// even at OnEnd. Worse, the Redis instrumentation batches its
// profiler-entry-to-Activity conversion via a Timer (default
// FlushInterval = 10s), so the Redis Activity is created and OnEnd
// fires *seconds after* the originating request has already completed.
// Program.cs's EnrichWithHttpRequest captures session.id into a per-
// trace-id table at server-span start; this OnEnd looks it up. The
// table is sized by a TTL longer than the Redis flush window so the
// entry is still there when the deferred Redis spans land.
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
    }
}

internal static class SessionScope
{
    // TTL must comfortably exceed StackExchange.Redis instrumentation's
    // FlushInterval (default 10s) plus typical request handler duration,
    // since Redis Activity OnEnd runs on the flush timer, not when the
    // Redis call completes.
    private static readonly TimeSpan _ttl = TimeSpan.FromMinutes(1);
    private static readonly ConcurrentDictionary<ActivityTraceId, (string Value, DateTimeOffset Expires)> _byTrace = new();
    private static readonly Timer _sweep = new(_ => Sweep(), null, _ttl, _ttl);

    public static void Capture(ActivityTraceId traceId, string sessionId)
    {
        _byTrace[traceId] = (sessionId, DateTimeOffset.UtcNow + _ttl);
    }

    public static string Lookup(ActivityTraceId traceId)
    {
        return _byTrace.TryGetValue(traceId, out var entry) && entry.Expires > DateTimeOffset.UtcNow
            ? entry.Value
            : null;
    }

    private static void Sweep()
    {
        var now = DateTimeOffset.UtcNow;
        foreach (var kvp in _byTrace)
        {
            if (kvp.Value.Expires <= now)
            {
                _byTrace.TryRemove(kvp.Key, out _);
            }
        }
    }
}
