# History request session capability (Q43)

## Request meaning

The collector selects the request parameters once, before its first history
page. It inspects the installed callable's explicit keyword-capable parameters;
the SDK version string is recorded, not used as a capability heuristic.
`**kwargs` alone does not prove session support. Failure to inspect an intraday
callable fails with `MoomooDependencyError` before requesting a history page.

| Request | Explicit `session` and matching SDK enum | Only explicit `extended_time` |
|---|---|---|
| RTH | `Session.RTH` | `False` |
| ETH | `Session.ETH` | `True` |
| ALL | `Session.ALL` | Refuse before a history request |

RTH is regular US trading hours. ETH includes regular, pre-market and
after-hours trading. ALL also includes overnight history. Therefore legacy
`extended_time=True` cannot silently satisfy ALL. If the callable exposes
`session` but the SDK lacks the required enum member, the dependency is
inconsistent and the collector refuses the request. Unsupported session names
are not aliases. Positional-only parameters are not keyword capabilities.

Daily intervals keep their existing behavior: neither session parameter is
sent. Evidence identifies `DAILY_DEFAULT` / `SDK_DAILY_DEFAULT`, with capability
flags null because intraday capabilities were not inspected. This does not
claim that a requested intraday scope was applied to a daily bar.

Every page uses the same selected meaning. Pagination, return-code checking,
DataFrame validation, request pauses and the existing batch retry policy stay
in place. An execution or unpacking `TypeError` propagates; the collector does
not interpret it as permission to retry with different parameters.

## Persisted request evidence

`MoomooHistoryCollector.last_request_evidence` is cleared at the start of each
fetch, including before connection. It is populated only after all pages and
the resulting DataFrame have succeeded. It contains:

- symbol, interval, requested session and effective request session;
- request mode (`SESSION`, `EXTENDED_TIME`, or `DAILY_DEFAULT`);
- explicit session / extended-time keyword capabilities;
- actual loaded SDK module and SDK version, which may be unknown/null;
- `validation_scope=REQUEST_PARAMETER_CAPABILITY_ONLY` and
  `response_session_coverage_verified=false`.

After a symbol's Raw/Curated pair is successfully archived and registered,
collection persists this dictionary in a `history_request_evidence` quality
record. PASS means the request evidence was recorded under this contract;
it does not prove full-session returned coverage, correct timestamps or market
accuracy. The SDK version is never substituted with `source_schema_version`.

Failed symbols retain the existing per-symbol failure records. No new run-wide
FAIL is added for such a symbol: the Catalog's run-wide quality gate must not
exclude unrelated successful symbols merely because another request failed.
Basic data quality failures keep their existing effect. Raw recovery makes no
new SDK request and emits no new `history_request_evidence` record; its existing
recovery lineage identifies the original archived run.

## Sources and acceptance boundary

The official [history API](https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html)
defines `extended_time` as pre/post-market inclusion and requires ALL for 24-hour
US history. The [Session definitions](https://openapi.moomoo.com/moomoo-api-doc/en/quote/quote.html)
distinguish RTH, ETH and ALL. These semantics were checked on 2026-10-11.

Offline tests exercise the actual collector with controlled SDK contexts and
the actual collection/archive/report/recovery path. They qualify this adapter's
parameter behavior, not live OpenD availability, a provider response's coverage,
or any new session's research/timestamp admission. No source cohort, calendar,
timestamp rule, package version, dependency or archive schema is changed.
