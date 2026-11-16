# Decision log

One entry per choice between real alternatives. Format: context, decision, consequences. Newest last; never edit
the decision of an old entry — add a new entry that replaces it.

### D1 — One project, three parts (2026-11-15)
- **Context:** three separate repos (filings Q&A, execution RL, Bitcoin options) did not form a whole; an outside
  quant review found that a slow filing signal and minute-level RL do not combine into P&L at a small order size.
- **Decision:** one US-stocks project. The filing signal is the research result; RL execution is a separate study
  of cost against order size; live paper trading is the engineering result. Static GitHub Pages only, no servers.
- **Consequences:** the old repos were deleted; the tested parts were copied in. The Q&A code (claim verifier,
  retrieval chunks) was removed on 2026-11-16 because the plan does not use it.

### D2 — Learned world model only behind gates (2026-11-15)
- **Decision:** a learned market simulator is tried only after Step 4, and kept only if it passes three gates
  written before the try: realistic (stylised-fact ratios in [2/3, 3/2], discriminator AUC < 0.80 on held-out
  days), useful (PPO trained with it beats PPO without it on real held-out days, 95% interval below 0), and cheap.
- **Consequences:** `execution/realism.py` is kept for the gate; the old Bitcoin world model was removed (in git
  history).

### D3 — Study period 2016-2025 (2026-11-16, owner's choice)
- **Context:** Alpaca's free history starts in 2016; reports start in 2009.
- **Alternatives:** (a) build on 2016-2019 with one price source; (b) add a second free daily source for 2010-2015
  (needs delisted companies, and a join at 2016).
- **Decision:** (a). Build 2016-2019, check 2020-2021, test 2022-2025 once.
- **Consequences:** 4 build years, not 10, so build-period estimates are less certain. Reports of 2010-2015 are
  kept as the earlier report of the first pairs.

### D4 — Point-in-time anchor is the SEC acceptance time (2026-11-15)
- **Decision:** a report is tradeable at the first NYSE open strictly after `acceptanceDateTime` (verified to be
  UTC against the EDGAR index header). Numbers come from each report's own XBRL, first reported value only.
- **Rejected:** filing date (one day too coarse; after-hours reports), companyfacts API (holds restated values).

### D5 — Universe identity by CIK with evidence, never guessed (2026-11-16)
- **Decision:** each membership interval is mapped to a CIK only with evidence (filing check, names with dates,
  "Date added", SEC name changes). Ambiguous intervals stay unmapped and are counted.
- **Consequences:** 96.8% of 2010-2025 member-days mapped; the 3.2% lost is concentrated in 2010-2015 and is
  not random (bought or failed companies). Results are reported by year.

### D6 — Long SEC jobs on GitHub Actions, not the owner's Mac (2026-11-16)
- **Alternatives:** local run (about 4 h, not allowed), Kaggle CPU (secret set in its UI), GitHub Actions.
- **Decision:** GitHub Actions, 6 shards sharing 7.8 requests/s, manual start, inputs from a private release,
  outputs as private artifacts, no failing steps.
- **Consequences:** about 1,300 of the 2,000 free private minutes per month per full run.

### D7 — Text measures: CMN baselines first; sentence-then-word edit similarity (2026-11-16)
- **Decision:** cosine, Jaccard and edit similarity on the full text (primary) and on risk factors and MD&A
  (secondary). The edit measure aligns sentences, then words inside changed blocks, because a word-level diff of
  two 50,000-word reports is too slow. Embedding similarity is a later variant only.

### D8 — Prices follow the company; vendor errors are removed, not repaired (2026-11-16)
- **Decision:** prices by the company's current symbol (Alpaca stores history under it); intervals without a
  confirmed CIK get no prices. Spin-off days that the vendor adjusts as splits get a NaN return.
- **Rejected:** repairing those days from corporate-action data (more sources, few days: 8 in 10 years).

### D9 — Signal ranked within form; composite of three measures (2026-11-16)
- **Context:** in 2016-2019, raw similarity ranks mixed forms (the most-changed quintile was 11% 10-Ks, the least
  changed 37%), because a 10-Q changes more from year to year than a 10-K. An outside review found the same risk.
- **Decision:** each measure is ranked within (month, form); the primary signal is the mean of the three full-text
  ranks. No single measure is chosen on the data (cosine was the strongest in the build period).
- **Consequences:** fixed in `docs/preregistration.md`.

### D10 — Costs on a fixed grid; window 120 days (2026-11-16)
- **Context:** the outside review: Corwin-Schultz is too noisy at large-cap spreads; a 92-day signal window misses
  the gap between a Q3 10-Q and the next 10-K.
- **Decision:** net returns at 2, 5 (primary) and 10 bps per unit of weight traded; Corwin-Schultz as a secondary
  estimate. Signal window 120 days, with `signal_age` recorded. Dollar-volume-weighted returns as a check.
- **Rejected for now:** the review's other changes (pre-2016 comparison, LLM measures, demoting the RL study,
  external timestamp) need the owner's decision; they are listed in status.md.

### D11 — No pre-2016 comparison with free data (2026-11-16)
- **Context:** the outside review's first suggestion was a pre-publication period (2010-2015) to measure decay.
- **Check:** the only large free source (Kaggle "Huge Stock Market Dataset") is a 2017 snapshot. It has no company
  that stopped trading before late 2017: 10.0% of 2010-2015 member-days, exactly the bought and failed companies.
- **Decision:** not used; a biased pre-period would carry the bias that this project exists to remove. Decay is
  addressed by the trend inside 2016-2025 and a comparison with the published estimates; a clean pre-2016 test
  needs CRSP (future work).

### D12 — The RL execution study is a test of what PPO learns, not a claim that it wins (2026-11-16)
- **Context:** in a square-root-impact simulator whose prices are a martingale, Almgren-Chriss is near-optimal, so
  PPO can at best match it (outside review).
- **Decision:** keep the study (an agent that learns to trade is a goal of the project), but give the simulator real
  intraday volume and spread profiles from minute bars and ask: does PPO learn them, and match the best fixed
  schedules (VWAP, Almgren-Chriss) at each order size? Add a capacity analysis: the assets under management at which
  the impact cost of the signal's turnover equals its gross return.
- **Rejected:** a headline of "RL beats Almgren-Chriss" (not true in this model).

### D13 — Pre-registration timestamped outside git (2026-11-16)
- **Decision:** OpenTimestamps proof `docs/preregistration.md.ots` (only the SHA-256 hash leaves the machine; no
  account), in addition to the GitHub push time of commit `e4d66bb`. Verify with `ots verify
  docs/preregistration.md.ots` after the Bitcoin confirmation (`ots upgrade` completes the proof).
- The proof is for the file as committed in `e4d66bb` (SHA-256 `b32c95a4…9a17`). The deviation log was added after
  the test, so verify that version: `git show e4d66bb:docs/preregistration.md > /tmp/p.md && ots verify -f /tmp/p.md
  docs/preregistration.md.ots`.

### D14 — Execution study design; a validation split after an early look at 2024 (2026-11-16)
- **Design (fixed before results):** replay of real first-hour minute bars (12 x 5 minutes), Almgren et al. (2005)
  impact, sizes 0.1/1/5% of ADV, 10 large and 10 smaller stocks, train 2023, test 2024, paired differences
  against the best fixed schedule with day-clustered intervals.
- **Process error and fix:** the first PPO version was evaluated directly on 2024 (PPO worse than VWAP at all
  sizes; kept in `data/execution_results_test_v1.json` and reported). Later design changes were chosen on a
  validation split inside 2023 only; 2024 was then used once more for the final run (3 seeds).
- **Changes from validation:** training reward = the order's own cost (`reward="impact"`; the market move is
  noise of about 50 bps per hour against impact differences of about 1 bp), reward scaled by order size, and a
  smaller initial exploration noise (log std -1). The action is a log multiplier of the TWAP pace.
