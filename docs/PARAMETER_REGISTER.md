# Parameter Register — AI Trust Tracker v0.3.1

Every tunable, its role, its status (PRIOR = uncalibrated starting value),
and where it lives. Calibration changes arrive as proposals and are merged
by a human with a version bump — never edited silently.

## Rubric

| Parameter | Value | Status | Meaning |
| --- | --- | --- | --- |
| rubric.version | v0-lexicon | PRIOR | Deterministic lexicon scorer. LLM rubric replaces it after κ ≥ 0.7 per source on 400 hand-labelled items. |
| relevance_drop_below | 0.5 | PRIOR | Items below this relevance never enter aggregates. Subject-vs-mention rule: AI in title = 1.0; AI in body + trust marker = 0.7; AI in body alone = 0.3 (dropped). |
| confidence_review_below | 0.6 | PRIOR | Low-confidence items routed to review sample, not discarded. |

## Corrections (spec Section 4)

| Parameter | Value | Status | Meaning |
| --- | --- | --- | --- |
| reach_cap_percentile | 99 | PRIOR | log1p(reach) capped at the source-day 99th percentile. |
| author_max_items_per_day | 5 | PRIOR | One author contributes at most 5 items per day. |
| dedup_title_jaccard | 0.8 | PRIOR | Title-token Jaccard ≥ 0.8 → same cluster; cluster counts once, size recorded as amplification. |

## Combining (spec Section 5, Phase-1 form)

| Parameter | Value | Status | Meaning |
| --- | --- | --- | --- |
| source_max_lens_weight | 0.40 | PRIOR | No source exceeds 40% of a lens's weight; remainder renormalised. |
| bias_terms | 0 for all sources | PRIOR | Estimated against survey anchors from Phase 3; until then everything is PROVISIONAL. |
| provisional_band_multiplier | 2.0 | PRIOR | 90% bands doubled while bias terms are priors. |
| min_lens_coverage | 0.60 | PRIOR | Lens publishes only if ≥60% of its sources reported that day. |
| composite_min_lenses | 2 | PRIOR | Composite withheld if fewer than 2 lenses present (hard rule in code). |
| lens_weights.societal | public .45 / media .25 / business .15 / technical .15 | CHOICE | Stated stakeholder choice, not a statistical output. |
| lens_weights.investor | public .30 / media .15 / business .40 / technical .15 | CHOICE | As above. |

## Company scores

| Parameter | Value | Status | Meaning |
| --- | --- | --- | --- |
| window_days | 7 | PRIOR | Rolling window for company n_eff. |
| min_n_eff | 50 | PRIOR | Below → LOW_CONFIDENCE (labelled, still shown). |
| min_lenses | 2 | PRIOR | Company needs items in ≥2 lenses or LOW_CONFIDENCE. |

## Scale

Direction is −2..+2; display rescale `(d + 2) / 4 × 100`. The 0–100 composite
is a display convention; the survey-gap metric compares rescaled discourse
against anchors **within the same metric_family only** (question wording
differs across providers — cross-family comparison is invalid).

## Worked example (one day's mechanics)

Suppose the Technical lens has one source (Hacker News) reporting
wmean = −0.18, se = 0.07, n_eff = 189:
- Lens value = −0.18 → display 45.5/100. Coverage 1/1 → published.
- If Media (GDELT) also reports wmean = −0.30, se = 0.05: inverse-variance
  weights are 1/0.07² = 204 vs 1/0.05² = 400; after the 40% cap:
  HN 0.40 / GDELT 0.60 → lens blend uses capped weights, composite = 0.45×public
  + 0.25×media + … over present lenses only (renormalised).
- Band = ±1.645 × se × 2.0 (provisional multiplier).
- Survey gap: if rescaled Public discourse = 45 and the Edelman US anchor
  (trust-in-ai family) = 32, gap = +13 pts, labelled INDICATIVE until calibrated.

## Changelog

- v0.1.0 (2026-11-24): initial register. All parameters PRIOR except lens
  weights (CHOICE). No calibrated values yet.
- v0.2.0 (2026-11-26): GDELT playbook upgrades. Timeline modes added
  (`timelinetone`, `timelinevolraw` — server-side over full coverage, no
  250-record ArtList cap) stored in `timeline_daily` and charted on the
  dashboard; ArtList queries use `sort=dateasc`; 429 backoff lengthened
  (20 s doubling). Dashboard gains Trend section (composite band + per-lens
  lines + GDELT tone panel) and per-company score-history sparklines.
  Tone is a word-list measure with a known negative lean — read day-to-day
  change, never the level. No parameter values changed.
- v0.2.1 (2026-11-26): robustness — GDELT serves HTTP 200 with a plain-text
  error body under load; non-JSON 200s now retry with the same backoff as 429
  (observed live on the CI runner). No parameter values changed.
- v0.3.0 (2026-11-26): **GDELT source switch — DOC API replaced by raw GKG
  files (Route B).** The DOC API hard-429s every IP class tested (sandbox,
  GitHub Actions runners, rotating residential proxies — 7/7 attempts across
  ≥4 residential exits, UA-independent, 2026-11-26), while the GKG file host
  serves the same blocked IPs without restriction. GKG is the underlying
  dataset: 15-minute batches, one row per article, with URL, domain,
  PAGE_TITLE, V2Tone (we use tone + word count), themes and entities.
  Consequences, stated not hidden:
  - **Match terms widened** (filtering is local and free; the relevance gate
    downstream drops passing mentions). Full list, matched case-insensitive
    with word boundaries over URL/title/themes/persons/organisations/names:
    artificial intelligence · chatgpt · openai · generative ai · ai safety ·
    anthropic · large language model(s) · llm(s) · deepseek · grok ·
    mistral ai · copilot · ai regulation · ai chatbot(s). Ambiguous tokens
    excluded deliberately: "claude", "gemini" alone (person/astronomy
    collisions).
  - **Method break:** GKG matching is title/URL/entity-based, not the DOC
    API's full-text index; volumes and tone levels are NOT comparable across
    the switchover. GKG tone series starts fresh 2026-11-26; deltas only, as
    before.
  - **Tone aggregation moves client-side:** hourly word-count-weighted mean
    of V2Tone (was: GDELT server-side timelinetone). `timeline_daily` schema
    unchanged; raw_json carries the hourly tone/volume points.
  - **Volume cap removed:** no 250-record ArtList cap; volume = everything
    GDELT saw matching the terms (~26h window ≈ 104 batches ≈ 500 MB/day on
    the runner; free on public repos).
  - DOC API code kept dormant; `GDELT_DOC_API=1` re-enables it.
  - Optional proxy support (`EVOMI_PROXY_URL`) added for GDELT calls, tested
    and found NOT to fix the DOC API block; dormant (unset = direct).
  - `scripts/backfill_gkg.py` + `backfill.yml` (manual dispatch): budget-
    bounded historical backfill, oldest-missing-day-first, safe to re-run.
    Backfilled days carry media + business lenses only.
  No parameter values changed.
- v0.3.1 (2026-11-26): **term widening + company-window bugfix.**
  - **Bare-'AI' term added** — matched case-sensitively against the GKG
    PAGE_TITLE only. Motivation: most headlines say "AI", not "artificial
    intelligence". Measured on live batch 20261126214500 (763 articles):
    current terms 10 matches; + bare AI case-insensitive over the full hay
    72 (mostly junk — "Ai" names, URL path tokens); + bare AI title-only
    case-sensitive 26, every sampled match a true positive. ~2.6x media
    volume uplift at clean precision. **Level break** in media/business
    volume and tone at the switch; deltas remain valid within each regime.
  - **Company-window future-leak fix.** The 7-day company window query had
    no upper bound (`day >= since` only), so any day scored while later
    data existed in the DB counted future items — backfilled days showed
    e.g. openai n_eff = 18,970 on a day with 1 actual openai item, and
    company scores were means over future discourse. Fixed to
    `day BETWEEN since AND day`; regression test added. **All company
    history from pre-v0.3.1 backfill passes is invalid and must be
    recomputed** — `backfill_gkg.py --force` re-runs days that already
    have data (oldest-first keeps each day's window correct).
  - Dashboard: Company trends overlay chart (multi-company, LOW CONF days
    dashed, selection persists in localStorage). Company history payload
    now carries the low_confidence flag per day.
  No parameter values changed.
