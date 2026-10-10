# US equity RTH calendar V1 (Q27)

## Goal and authority

The bundled `nyse-us-equities-2025-2027-v1` calendar covers 2025-01-01 through
2027-12-31. It distinguishes normal core sessions, 13:00 early closes, full
closures (including weekends), and dates outside its coverage. It is separate
from the sealed Moomoo timestamp qualification in
[Early-Close RTH Geometry V1](../market_bar_early_close_rth_geometry_qualification_v1.md).

Schedule facts were checked on 2026-10-10 against these primary sources:

- [NYSE 2025–2027 calendar, published 2024-11-08](https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx).
- [NYSE emergency closure notice, published 2024-12-30](https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx).
- [Current NYSE hours/calendar](https://www.nyse.com/trade/hours-calendars),
  corroborating the 2026–2027 schedule and 09:30–16:00 equity core session.

The emergency notice makes 2025-01-09 a full closure. Early closes are exactly
2025-07-03, 2025-11-28, 2025-12-24, 2026-11-27, 2026-12-24, and 2027-11-26.
2026-07-02 and 2027-12-31 remain normal sessions; 2027-12-24 is fully closed.
These are equity core-session facts, not bond, option or extended-hours rules.

## Runtime defaults

`resolve_exchange_rth_session(date)` returns an immutable record containing
classification, open/close (absent for closed or unsupported dates), reason,
timezone, calendar version, source publication date and retrieval date. It
does not imply that a provider response for that date is qualified.

`resolve_rth_session_geometry(date)` is the conversion gate used by
`normalize_bars` for Moomoo `10.9-mv-ts2` intraday RTH:

| Exchange state | Provider authority | Conversion |
|---|---|---|
| Covered normal weekday | Existing normal profile | Exact normal sequence only |
| 2025-11-28 or 2025-12-24 | Existing sealed exact-date special profile | Exact qualified special sequence only |
| Other published early close | Missing exact-date qualification | `PROVIDER_UNVERIFIED`, with date, expected hours and source |
| Holiday, emergency closure or weekend | No RTH session | `calendar CLOSED`, with date and reason |
| Outside 2025–2027 | No bundled date coverage | `calendar UNSUPPORTED`, with supported range |

Q27 supersedes the old absence-means-normal fallback at the **calendar** layer.
The provider allowlist, evidence bytes and hashes remain unchanged. A known
but unqualified early close is no longer misclassified as a normal day or
reported merely as a 390-versus-210 mismatch. It still cannot be converted.
An apparently complete normal sequence on a closed or unqualified special
date is rejected before any timestamp mapping.

All conversions still compare the full ordered sequence exactly. Neither row
count nor the last observed bar grants calendar or provider authority. UTC
conversion still uses `America/New_York`, including daylight saving time.
Collection records these detailed exceptions in its normal per-symbol failure
result before Raw/Curated publication.

## Compatibility and non-goals

- Existing archives are not rewritten. Legacy `10.9`, daily bars, `Session.ALL`,
  session labels, `bar_available_at`, Dataset/Feature identities and replay
  formats are unchanged.
- This change does not claim new live OpenD qualification, production
  deployment, support for arbitrary years, options or other markets.
- In particular, 2025-07-03 is now correctly known to the calendar but remains
  unqualified for Moomoo conversion. New exact-date live evidence is required
  before extending the sealed provider allowlist. Future dates cannot have
  historical-response evidence at the time of this change.
- Later emergency notices require a reviewed calendar revision. Runtime
  normalization performs no network lookup and does not silently reinterpret
  old saved outputs using a newer schedule.

## Acceptance

Tests exercise published special dates across all three years; normal dates,
observed holidays, the emergency closure, weekends and coverage limits; actual
normalization refusal with a complete-looking response; and the original
sealed normal/special mappings, truncated final bars, malformed authority,
duplicate/missing endpoints, ALL and legacy compatibility. The previous
July-3 rejection assertion changes only to require the explicit qualification
reason; rejection itself remains mandatory.
