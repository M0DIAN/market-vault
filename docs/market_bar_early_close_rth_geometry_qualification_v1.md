# Market-Bar Early-Close RTH Geometry Qualification V1

## Status And Scope

This record is the approved design and evidence authority. The authorized
runtime implementation candidate now applies it through
`src/market_vault/normalization/rth_session_geometry.py` and remains pending
independent review, merge, and deployment. This status does not claim that
formal main or the production runtime accepts early-close responses yet.

The qualification is deliberately narrow:

- market: US equities;
- provider: Moomoo historical K-line through OpenD;
- symbol used for provider qualification: `US.SPY`;
- requested session: `RTH`;
- adjustment: `NONE`;
- intervals: `1m`, `5m`, `15m`, `30m`, and `60m`;
- qualified special-session profile: official 09:30-13:00
  `America/New_York` early close;
- provider SDK: `moomoo-api 10.9.6908`;
- OpenD: `10.10.7008`.

`Session.ALL`, Intraday Audit boundary certification, production collection,
and production migration remain out of scope.
Independent review approval is not claimed by this document.

## Two Independent Authorities

Support requires two distinct authorities. Neither may substitute for the
other.

### Exchange schedule authority

Exchange evidence proves the date, market timezone, official RTH open,
official RTH close, and special-session classification. Observed bars never
prove their own expected completeness.

The initial authority revision is:

```text
authority_version =
    us-rth-special-session-authority-v1
authority_model =
    MODEL_A_VERSIONED_BUNDLED_IMMUTABLE_SPECIAL_SESSION_TABLE
SPECIAL_SESSION_TABLE_IS_OVERRIDE_ALLOWLIST=true
ABSENT_DATE_MEANS_NORMAL_PROFILE=true
ABSENT_DATE_DOES_NOT_MEAN_RUNTIME_AUTHORITY_FAILURE=true
```

The future immutable table must contain exact date, market,
`America/New_York`, official open, official close, classification, authority
reference, authority capture metadata, authority review metadata, and the
explicit authority version.

The table is an explicit special-session override allowlist, not an exhaustive
calendar of ordinary dates. If `requested_trade_date` is present, runtime must
use that entry's exact official RTH geometry and corresponding sealed,
qualified Moomoo provider profile, then compare the complete observed endpoint
sequence exactly. If the date is absent, runtime must retain the existing
normal RTH profile of 09:30-16:00 America/New_York and perform the same exact
full-sequence comparison. Absence therefore does not mean that ordinary
runtime authority is missing.

An unlisted real early-close date remains fail closed: the normal profile
expects endpoints through 16:00, the provider response ends at 13:00, and the
exact sequence comparison rejects the mismatch. Runtime must not infer an
override from row count, the last observed bar, or a continuous prefix.

| Date | Classification | Official RTH open | Official RTH close | Venue-aligned exact-date authority | Independent corroboration |
|---|---|---|---|---|---|
| 2025-11-28 | `EARLY_CLOSE` | 09:30 America/New_York | 13:00 America/New_York | [NYSE official 2025 Trading Calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf) | [Nasdaq Trader Alert #2025-92](https://m.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-92) |
| 2025-12-24 | `EARLY_CLOSE` | 09:30 America/New_York | 13:00 America/New_York | [NYSE official 2025 Trading Calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf) | [Nasdaq Trader Alert #2025-101](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-101) |
| 2025-12-26 | `NORMAL` control | 09:30 America/New_York | 16:00 America/New_York | [NYSE official 2025 Trading Calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2025_Yearly_Trading_Calendar.pdf) | [Nasdaq Trader Alert #2025-101](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-101) |

The NYSE official 2025 calendar marks both 2025-11-28 and 2025-12-24 as
13:00 ET early market closes. The official
[NYSE Holidays and Trading Hours](https://www.nyse.com/trade/hours-calendars)
scope applies the holiday schedule to all NYSE markets, explicitly includes
NYSE Arca Equities, and defines its Core Trading Session as 09:30-16:00 ET.
NYSE's official [Rule 608 appendix](https://www.nyse.com/publicdocs/nyse/regulation/nyse/Fourth_Amendment_to_Rule_608.pdf)
identifies SPY's primary exchange as NYSE Arca. This makes NYSE's 2025 schedule
the venue-aligned date authority for the probe symbol.

Nasdaq Trader Alert #2025-92 independently corroborates the 13:00 ET close on
2025-11-28. Alert #2025-101 independently corroborates the 13:00 ET close on
2025-12-24 and the regular schedule on 2025-12-26. These Nasdaq alerts remain
cross-market corroboration, not the sole venue authority. Their URLs in the
sealed probe manifest and all sealed evidence bytes remain unchanged.

Future runtime code must not infer a special session or official close from
row count, the last observed bar, `trade_date_type`, a continuous prefix, or
generic recurring hours.

### Provider geometry authority

Provider evidence proves how
`request_history_kline(..., session=Session.RTH, ...)` labels bars after an
independent exchange schedule has established expected session geometry.
Exchange hours alone do not prove Moomoo endpoint conventions.

The live probe captured all 15 provider-native responses before analysis.
It did not call MarketVault normalization, collection, Parquet, Catalog,
manifest, report, or Safe Purge code.

```text
probe_version =
    market-vault-early-close-rth-provider-probe-v1
probe_formal_main =
    1e8cca3058269c87a3a25d3b7d6338c5c582e471
probe_manifest_sha256 =
    b82628b3b8810c7717c23af02e531f6af79f0c9409682074a71062088b52535b
python =
    3.12.14
moomoo_sdk =
    10.9.6908
opend =
    10.10.7008
symbol =
    US.SPY
session =
    RTH
adjustment =
    NONE
```

The sealed manifest and responses are in
[`evidence/early_close_rth_geometry_v1/`](evidence/early_close_rth_geometry_v1/).

## Observed Provider Geometry

Both official 13:00 early-close dates produced identical ordered timestamp
sequences for every interval. Every response had zero duplicate `time_key`
values and was strictly monotonic.

| Date | Interval | Rows | First Raw `time_key` | Last Raw `time_key` | Convention |
|---|---:|---:|---:|---:|---|
| 2025-11-28 | 1m | 210 | 09:31 | 13:00 | interval end |
| 2025-11-28 | 5m | 42 | 09:35 | 13:00 | interval end |
| 2025-11-28 | 15m | 14 | 09:45 | 13:00 | interval end |
| 2025-11-28 | 30m | 7 | 10:00 | 13:00 | interval end |
| 2025-11-28 | 60m | 4 | 10:30 | 13:00 | interval end; official-close truncation |
| 2025-12-24 | 1m | 210 | 09:31 | 13:00 | interval end |
| 2025-12-24 | 5m | 42 | 09:35 | 13:00 | interval end |
| 2025-12-24 | 15m | 14 | 09:45 | 13:00 | interval end |
| 2025-12-24 | 30m | 7 | 10:00 | 13:00 | interval end |
| 2025-12-24 | 60m | 4 | 10:30 | 13:00 | interval end; official-close truncation |
| 2025-12-26 | 1m | 390 | 09:31 | 16:00 | interval end |
| 2025-12-26 | 5m | 78 | 09:35 | 16:00 | interval end |
| 2025-12-26 | 15m | 26 | 09:45 | 16:00 | interval end |
| 2025-12-26 | 30m | 13 | 10:00 | 16:00 | interval end |
| 2025-12-26 | 60m | 7 | 10:30 | 16:00 | interval end; final 30m segment |

The exact qualified early-close mappings are:

| Interval | Exact provider endpoint model | Exact canonical starts |
|---|---|---|
| 1m | 09:31 through 13:00, every minute | 09:30 through 12:59 |
| 5m | 09:35 through 13:00, every 5 minutes | 09:30 through 12:55 |
| 15m | 09:45 through 13:00, every 15 minutes | 09:30 through 12:45 |
| 30m | 10:00 through 13:00, every 30 minutes | 09:30 through 12:30 |
| 60m | 10:30, 11:30, 12:30, 13:00 | 09:30, 10:30, 11:30, 12:30 |

For 60m, the final provider bar spans 12:30-13:00 and is truncated to 30
minutes at the independently authoritative official close.

The 2025-12-26 control exactly reproduced the existing qualified normal-day
model. Therefore:

```text
EARLY_CLOSE_1M_CONSISTENT=true
EARLY_CLOSE_5M_CONSISTENT=true
EARLY_CLOSE_15M_CONSISTENT=true
EARLY_CLOSE_30M_CONSISTENT=true
EARLY_CLOSE_60M_CONSISTENT=true
NORMAL_CONTROL_COMPATIBLE=true
PROVIDER_GEOMETRY_DRIFT=false
```

## Future Runtime Design

The smallest future authority interface is a deterministic value such as:

```text
RTHSessionGeometry(
    trade_date,
    market,
    timezone,
    open_time,
    close_time,
    classification,
    authority_version,
)
```

No database or service abstraction is required. The authority belongs in
versioned bundled source so normalization remains deterministic, offline, and
auditable.

The future runtime algorithm must:

1. consult the bundled special-session override allowlist for the exact
   requested date;
2. when listed, use only that entry's official geometry and sealed, qualified
   provider profile; fail closed when the entry is malformed, ambiguous,
   conflicting, superseded by an emergency notice, or unsupported;
3. when absent, use the unchanged normal 09:30-16:00 America/New_York RTH
   profile rather than treating table absence as an authority failure;
4. generate the complete expected provider endpoint sequence: begin at
   `open + interval`, include full nominal endpoints through the official
   close, and append the official close only when the final interval is
   boundary-truncated;
5. compare the complete observed sequence exactly, including count, order,
   duplicates, first endpoint, and final endpoint;
6. reject every mismatch without tolerance;
7. only after exact equality, map the provider endpoints to canonical
   interval starts.

The generation rule is authorized only for provider profiles supported by
sealed evidence. It is not permission to extrapolate arbitrary close times,
dates, intervals, sessions, markets, or provider versions.

Normal-day geometry remains unchanged. A normal date truncated at 13:00 or
any arbitrary time cannot be accepted as an early close because the
independent date authority classifies it as normal. The same exact comparison
rejects a missing final bar, a continuous prefix, a missing middle bar, a
duplicate, a nonmonotonic response, a wrong final endpoint, or an endpoint
after the official close.

The authority uses `America/New_York` and timezone-aware instants. UTC values
must derive from `ZoneInfo` for the exact requested date; fixed UTC offsets
are forbidden.

Authority revisions are immutable once released. A later official emergency
or schedule notice requires a reviewed authority update. Normalization must
never perform a network lookup.

## Compatibility Decisions

```text
SOURCE_SCHEMA_VERSION_CHANGE_REQUIRED=false
BAR_AVAILABLE_AT_CHANGE_REQUIRED=false
SESSION_LABEL_CHANGE_REQUIRED=false
INTRADAY_AUDIT_BOUNDARY_CONTRACT_CHANGED=false
SESSION_ALL_BOUNDARY_CONTRACT_UNCHANGED=true
NEW_CATALOG_TABLE_REQUIRED=false
NEW_CATALOG_COLUMN_REQUIRED=false
NEW_PRODUCTION_COLLECTION_REQUIRED=false
```

`10.9-mv-ts2` reserved unsupported and ambiguous geometry for future
qualification and failed closed instead of assigning incompatible canonical
timestamps. Supporting this qualified profile completes that existing
contract; it does not reinterpret accepted normal-day snapshots.

`bar_available_at = interval start + nominal interval` remains a conservative
not-before bound. For the 12:30-13:00 truncated 60m bar it is later than the
actual close, not earlier, so it remains leakage-safe.

Early-close RTH rows remain `REGULAR`; the date's 13:00 official close does
not turn those rows into `AFTER_HOURS`.

Intraday Audit's `boundary_coverage.evaluated=false` contract is unchanged.
This authority initially qualifies TS2 RTH normalization only. `Session.ALL`
special-session geometry also remains unqualified.

## Mandatory Implementation Tests

A later implementation PR must prove:

- normal RTH 1m, 5m, 15m, 30m, and 60m compatibility;
- early-close RTH 1m, 5m, 15m, 30m, and 60m exact mapping;
- fixtures for both 2025-11-28 and 2025-12-24;
- the 2025-12-26 normal control;
- an arbitrary ordinary date absent from the special-session table uses the
  existing normal profile and passes an exact normal sequence;
- an unlisted early-close-shaped response is rejected against the normal
  profile;
- a listed qualified 13:00 date passes only its exact qualified sequence;
- a listed special date with the wrong sequence is rejected;
- missing-last normal response refusal;
- continuous-prefix normal response refusal;
- middle-gap normal and early-close response refusal;
- wrong early-close final endpoint refusal;
- extra endpoint after official close refusal;
- malformed, ambiguous, or conflicting listed authority refusal;
- unsupported special date and provider profile refusal;
- duplicate and nonmonotonic endpoint refusal;
- provider-native Raw timestamps remain unchanged;
- canonical starts equal the exact mappings in this record;
- `Session.ALL` behavior remains unchanged;
- legacy `10.9` behavior remains unchanged;
- existing normal `10.9-mv-ts2` geometry remains unchanged.

## Evidence File Seal

`PROBE_MANIFEST.json` has SHA-256
`b82628b3b8810c7717c23af02e531f6af79f0c9409682074a71062088b52535b`.
It seals these 15 byte-preserved provider evidence files:

| Evidence file | SHA-256 |
|---|---|
| `2025-11-28_US.SPY_RTH_1m.json` | `1f08020bfb561a5a617199fa02701ee446c697471d0651d879a52d422e9d90c3` |
| `2025-11-28_US.SPY_RTH_5m.json` | `554f16b85df2c6b565dec1db15d5c0ea152271562d97c03e59cc47634d0e274b` |
| `2025-11-28_US.SPY_RTH_15m.json` | `5ad2294f7141c89cc5b23702573b3e3bd55f7111cb661a16ee1445e43c44b83b` |
| `2025-11-28_US.SPY_RTH_30m.json` | `d0658143a50e9f4610dfc560a9ad0caf3d785fa4dc19f77e3a280e77a4ba6647` |
| `2025-11-28_US.SPY_RTH_60m.json` | `7fb5aea67a53281bb2cb8cd49ce868a3dce592ac245ac87920a59da59fd36bc1` |
| `2025-12-24_US.SPY_RTH_1m.json` | `5805a656d44230f4068457e97538d0c5f2f0d334e267cb180c45e23ef7f7a471` |
| `2025-12-24_US.SPY_RTH_5m.json` | `39551182ce181aa8a20f4dbc29f0977db9a677663064418fb9e9e27b90c8790d` |
| `2025-12-24_US.SPY_RTH_15m.json` | `d8888c452592dc3f56593288bc85051223ed32b2583431ac1401006258f1f3f5` |
| `2025-12-24_US.SPY_RTH_30m.json` | `6e9379d2fced116bbf304d1af1adc01e71a518c20b0fc067a339474399aebbf6` |
| `2025-12-24_US.SPY_RTH_60m.json` | `264520e2060879f0eebe5ffd1a5cb5476695c4efe6de3f7d4b4ead09fccf90a0` |
| `2025-12-26_US.SPY_RTH_1m.json` | `32bc6ad428adcf1bf3b3f58fadc5be6be27e9ed34cb62d08b3991dd52feadcea` |
| `2025-12-26_US.SPY_RTH_5m.json` | `a2aaa8010cc0b4b21e611b37b2cf470914c640253b3f63c4785850671e69ff91` |
| `2025-12-26_US.SPY_RTH_15m.json` | `a368b6d3aaed0d0dfa146e7bd50172010f278add09e1f25d97138e9991e207e5` |
| `2025-12-26_US.SPY_RTH_30m.json` | `bcda212289eea3aba4f2efbc1b5c96e0b654606cc013423fb1fea01f00fbe011` |
| `2025-12-26_US.SPY_RTH_60m.json` | `a2ffba081c887f0aa93b57eb4af9ee73ff8d8181a51a0ea52de755d62e9663b4` |

The JSON contains only the authorized request identity, provider timestamp
geometry, row ordinals, capture metadata, and evidence hashes. It does not
fabricate OHLCV values.

## Implementation Gate

Runtime implementation remains unauthorized by this design candidate until
independent review and merge. A future implementation must start from a base
that already contains this approved authority record, preserve the evidence
bytes and all compatibility decisions above, and fail closed outside the
exact qualified scope.
