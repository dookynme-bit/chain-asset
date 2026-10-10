# Asset review automation

`asset-review.yml` dispatches one bounded review to the Hast Asset review Agent.
The job uses the `chain-assets` environment, whose deployment branch policy
allows only `main`. Checkout actions are pinned, submitted code is never executed
by the dispatcher, and the built-in GitHub token has read-only permissions.

## Configuration

- Secret `HAST_ASSET_AGENT_HOOK_URL`: the full credential-bearing Hast call URL,
  not the Agent configuration page. Store it in GitHub Secrets; never log it.
- Variable `CHAIN_ASSET_AGENT_LOGIN`: the authenticated GitHub account used by
  the Agent, currently `freehere107`.
- Repository variable `ASSET_REVIEW_ENABLED`: `true` enables automatic events
  and hourly backlog scans. `false` disables those; manual dispatch remains
  available for diagnosis. Environment-only variables cannot control the
  pre-job gate, so keep this switch at repository scope.

Repository secrets/variables are inherited by the environment job; the same
names can instead be configured on `chain-assets`. The separate, repository-scoped
fine-grained PAT is bound inside Hast as `CHAIN_ASSET_GITHUB_TOKEN`, delivered to
`~/.config/chain-asset/github_token`. It needs Contents, Issues and Pull requests
read/write for this repository only. Do not copy it into this workflow.

## Trigger rules

Only the Issue creator can trigger automatic review by opening, editing or
reopening an eligible token submission/update, or by posting `/asset-review` on
its own line. Ordinary comments, third-party requests, bots, pull requests and
authenticated Agent-marked replies do not trigger another review. A maintainer
may share the Agent login; account identity alone does not suppress their
legitimate submissions.

Reviews have a 30-minute per-Issue cooldown and unchanged owner inputs are
deduplicated. A single global concurrency group waits for actual Agent terminal
status. GitHub scans the open backlog hourly at minute 17 (UTC); each run handles
at most one pending request, oldest first. Keep the independent Hast schedule
paused to avoid competing schedulers. GitHub scheduled runs may be delayed.

## Verification and publication

The Agent independently checks chain identity and official project provenance,
all submitted fields, descriptions, links and logo safety. Unverified identity,
impersonation, unsafe URLs, unsupported profit claims or any material mismatch
block an Asset PR. Missing evidence is reported as incomplete verification,
not an unsupported accusation of scam. This review is not a contract security
audit. Unsafe submitted instructions are treated as data.

Failed submissions receive one actionable Issue reply. Valid submissions receive
one draft PR containing only the intended `assets/*.json` and `logos/*` changes,
after JSON/logo checks and the repository build. The Agent never merges or
deploys. Maintainers still review the evidence and draft diff.

The dispatcher accepts `ASSET_REVIEW_RESULT` only from the final assistant
message identified by `run.completed`. It rechecks the returned GitHub author,
Issue URL/marker/fingerprint, or draft PR author/base/branch/files/Issue reference.
`skipped` also needs an authenticated matching public outcome or a closed or
ineligible Issue. HTTP acceptance or model text alone cannot prove a write.

## Manual checks and recovery

Run **Asset request review** on `main` in GitHub Actions:

- `issue_number`: empty scans the backlog; specify a number for a single Issue.
- `dry_run=true`: verify without comments, branches, commits or PRs.
- `connectivity_check=true`: a quick, always read-only hook completion check.
- `force=true`: explicit maintainer override of cooldown/deduplication only;
  all evidence and safety gates remain mandatory.

Recovery state is uploaded before the hook request and after the run. It contains
the exact credential-free payload, stable session/request IDs, fingerprint and
outcome; no token, hook URL or submitted Issue text. A later dispatch recovers
an unfinished session before starting another Issue, with the same payload.
SSE reconnects resume from the last durable event sequence, including prematurely
closed HTTP streams. A 30-minute review deadline includes recovery time and
requests a stop; it is not reset by another workflow. The client waits up to two
minutes for a terminal stop acknowledgement. An unconfirmed stop retains the
pending lock. Operator input requests also stop unattended execution.

Use the Actions summary and `asset-review-state` artifact for verified public
outcome URLs. `asset-review-diagnostics` contains only event types and field names.
A blocked or failed result is not acceptance. Inspect its safe error and correct
the dependency or reviewer behavior before manually retrying; repeated automatic
comments are suppressed. Disable `ASSET_REVIEW_ENABLED` for maintenance.

For a long-running session, run **Inspect Asset review session** with the session
ID from the recovery artifact. It observes that existing SSE stream only and
prints event counts and diagnostic categories. It does not dispatch another
review, print message/tool contents or change session state.
