# Setting up the nightly trigger (Cloudflare Worker)

GitHub starts scheduled runs hours late (decision D23). The nightly run must write its predictions before the next
open, so a Cloudflare Worker starts it on time through GitHub's API (decision D36). The GitHub schedule in
`nightly.yml` (02:00 and 11:30 UTC, Tuesday to Saturday) stays as a backup. Order execution is disabled (D38): the
run writes and scores predictions only. The owner does these steps once; nothing here needs a paid plan.

## 1. A GitHub token that can only start this repository's workflows
1. GitHub → Settings → Developer settings → Fine-grained personal access tokens → Generate new token.
2. Repository access: **Only select repositories** → `ghostdesk`.
3. Permissions → Repository → **Actions: Read and write**. Nothing else.
4. Expiration: one year (put a reminder in your calendar). Copy the token.

## 2. The Worker
```bash
npm install -g wrangler        # or: npx wrangler ...
cd worker
wrangler login                 # opens the browser; a free Cloudflare account is enough
wrangler secret put GITHUB_TOKEN   # paste the token; it is stored by Cloudflare, never in git
wrangler deploy
```
`wrangler.toml` holds the repository name and the two cron lines (UTC): 01:30 Tuesday to Saturday (after each
weekday session) and 11:00 Tuesday to Saturday (a second chance before the open). The Worker starts `nightly.yml`.

## 3. Check it
- `wrangler tail` shows `dispatch 30 1 * * 2-6: HTTP 204` at the next cron time; a new `nightly` run appears in
  the Actions tab with mode `night`.
- To test at once: in the Cloudflare dashboard, Workers → ghostdesk-trigger → Settings → Triggers → the cron
  line → "Trigger" (or `wrangler dev --test-scheduled` and open `/__scheduled`).
- HTTP 401 or 403: the token is wrong or lacks Actions write. HTTP 404: wrong `REPO` or workflow file name.
  HTTP 422: the `mode` input is not accepted by the workflow on `main`.

## 4. Turning it off
`wrangler delete` removes the Worker; the GitHub schedule still starts the run, later. There is no order switch to
turn: `nightly.yml` fixes `TRADING` to `off` in the workflow itself and has no order mode, so the repository variable
has no effect.
