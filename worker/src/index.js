// Cloudflare Worker: the main trigger of the nightly run (decision D36). GitHub's own schedule starts runs hours
// late (D23), so this Worker's cron calls GitHub's workflow_dispatch API at the right time, and live.yml's schedule
// stays only as a backup. A rerun is harmless: the run does nothing for a session that is done.
//
// Secrets and variables (set by the owner, never in git):
//   GITHUB_TOKEN  fine-grained token, this repository only, permission "Actions: read and write"
//   REPO          "owner/name", WORKFLOW "live.yml", REF "main"
//
// Cron (UTC, see wrangler.toml): 01:30 Tue-Sat = 20:30 EST / 21:30 EDT after each weekday session, inside Alpaca's
// market-on-open window (19:00-09:28 New York); 11:00 Tue-Sat = 06:00 EST / 07:00 EDT, a second chance before 09:28.

const API = "https://api.github.com";

export async function dispatch(env, mode = "night", fetchFn = fetch) {
  const url = `${API}/repos/${env.REPO}/actions/workflows/${env.WORKFLOW || "live.yml"}/dispatches`;
  const res = await fetchFn(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ghostdesk-trigger",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.REF || "main", inputs: { mode } }),
  });
  return { status: res.status, ok: res.status === 204 };
}

export default {
  async scheduled(event, env, ctx) {
    // Up to 3 tries: a GitHub 5xx or a network error must not lose the night (the backup cron also exists).
    for (let i = 0; i < 3; i++) {
      try {
        const r = await dispatch(env);
        console.log(`dispatch ${event.cron}: HTTP ${r.status}`);
        if (r.ok || (r.status >= 400 && r.status < 500)) return; // 4xx: a token or input problem; retrying will not help
      } catch (e) {
        console.log(`dispatch ${event.cron}: ${e}`);
      }
      await new Promise((ok) => setTimeout(ok, 5000 * (i + 1)));
    }
  },
  async fetch() {
    // No secrets and no action here: only says the Worker is deployed.
    return new Response("ghostdesk trigger: ok\n", { headers: { "content-type": "text/plain" } });
  },
};
