# AI Trust Tracker

Tracks trust in AI — the field as a whole and individual companies — from free
news and social sources only. No paid APIs.

**Throughline:** surveys anchor the *Public* lens level; discourse supplies daily
movement in every lens. Media, Business and Technical lenses are **discourse
indices** (provisional) until per-lens anchors exist. Sources within a lens are
blended by inverse variance with a 40% cap; lenses combine by stated weights.
Every series is stored separately; the composite is one view, never the only one.

## Sources (all free)

| Source | Lens | Access | Notes |
| --- | --- | --- | --- |
| GDELT 2.0 DOC API | Media | Free, no key, 1 req/5s | Two queries/day: field + financial-press domain slice |
| Hacker News (Algolia) | Technical | Free | Stories + comments, last 26h |
| Bluesky public search | Public | Free, **live-only** | No history — daily capture is the only option |
| Reddit | Public | Free tier (OAuth) or public JSON | **Terms review pending**; set `REDDIT_CLIENT_ID/SECRET` |
| Surveys (Edelman, Ipsos, Pew…) | Anchor | Free summaries | Manually entered into `config/surveys.yaml`, ~1 hr/wave |

Sources fail soft: an unavailable source is recorded in `source_status`, drops
out of its lens, and the lens publishes only if ≥60% of its sources reported.

## Layout

```
config/parameters.yaml   all thresholds, weights, PRIOR flags
config/companies.yaml    AI universe (~45 entities) + match aliases
config/surveys.yaml      survey anchors with metric families
src/store.py             SQLite schema (the contract — commit DB changes here)
src/rubric.py            scorer v0-lexicon (PRIOR stand-in for the LLM rubric)
src/collectors.py        one collector per source, fail-soft
src/aggregate.py         dedup, reach caps, author caps, weighted series
src/combine.py           lens blending, composite, survey gap
scripts/daily_update.py  collect → score → correct → aggregate → combine
scripts/build_dashboard.py  static docs/index.html (GitHub Pages-ready)
tests/test_core.py       16 tests
```

## Run

```bash
python3 scripts/daily_update.py              # collect today + score + combine
python3 scripts/daily_update.py --reuse      # re-run pipeline on stored items
python3 scripts/build_dashboard.py           # -> docs/index.html
python3 -m pytest tests/ -q
```

## Known limitations (v0, stated not hidden)

1. **Lexicon scorer is a prior.** v0-lexicon cannot detect sarcasm, quotes of
   third parties, or subtle stance; `stance_type` is `unscored`. Replace with the
   LLM rubric only after per-source κ ≥ 0.7 on 400 hand-labelled items, and
   re-score a 30-day overlap window at switch.
2. **Bias terms are b = 0 priors.** All outputs PROVISIONAL; bands widened ×2.
   First survey calibration back-applies revised terms to history.
3. **Non-coverage:** with X excluded, the Public lens lacks a right-leaning US
   platform. Post-stratification cannot fix absent groups — the Public band is
   permanently wider, not corrected.
4. **Only Public is survey-anchored.** Other lenses are discourse indices.
5. **Bluesky has no history.** Day-one capture is mandatory; gaps are permanent.
6. GDELT ArtList carries no audience figures: each outlet counts as one voice
   (reach = 1) until a better reach proxy is wired in.

## Automation

`.github/workflows/daily.yml` runs tests + the pipeline at 06:00 UTC daily,
on every push to `src/`, `scripts/`, `config/` or `tests/`, and on manual
dispatch (the dashboard's "Update data now" button links there). The bot
commits the rebuilt dashboard and DB snapshot; GitHub Pages serves `/docs`.
