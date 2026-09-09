# Adding a "Policy Evaluation" link to the live flywheel dashboard

This side (`hp-roscon-eval-dashboard`) is already wired for this — it reads
`LIVE_DASHBOARD_URL` and renders it as the "← Back to Live Flywheel" link in
the header (`src/eval_dashboard/web/app.py`, `dashboard.js`). Nothing to do
here.

The other direction — a "Policy Evaluation" link on the live flywheel
dashboard that opens this one — lives in a repo not checked out alongside
this one (`hp-roscon-flywheel`), so it can't be applied directly from here.
Hand this to whoever owns `gitops/flywheel/dashboard.yaml` (Jeremy):

1. **Add an env var to the `dashboard` Deployment** in
   `gitops/flywheel/dashboard.yaml`, pointing at wherever the eval dashboard
   is actually running (a laptop over Tailscale, so this has no fixed
   production value — pick a sane dev default):

   ```yaml
   env:
     - name: EVAL_DASHBOARD_URL
       value: "http://localhost:8080"
   ```

2. **Render a nav link from it** in the ConfigMap's `index.html`, next to
   the existing title, so the two dashboards read as tabs rather than the
   eval dashboard being undiscoverable:

   ```html
   <div id="header-left">
     <span class="tab active">Live Flywheel</span>
     <a class="tab" id="eval-dashboard-link" href="#" target="_blank" rel="noopener">Policy Evaluation</a>
   </div>
   ```

   ```js
   document.getElementById('eval-dashboard-link').href = EVAL_DASHBOARD_URL; // however config is threaded through today
   ```

3. Apply and redeploy `gitops/flywheel/dashboard.yaml`.

Once that's live, set this dashboard's `LIVE_DASHBOARD_URL` to match
whatever `10.0.0.49:30801` actually resolves to for you, if it isn't the
default — see the README's "Where it lives" section.

Check first whether this has already been done: search
`gitops/flywheel/dashboard.yaml` for `EVAL_DASHBOARD_URL` before writing
the patch by hand.
