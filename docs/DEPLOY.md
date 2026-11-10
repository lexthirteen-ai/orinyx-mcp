# Deploying the MCP service (Fly.io)

Two apps, one database that only the API holds:

| App | Repository | Holds |
|---|---|---|
| `orinyx-api` | orinyx-engine (private) | the API, the rules, Postgres, the OAuth authorization server |
| `orinyx-mcp` | this one | the MCP endpoint at `https://orinyx-mcp.fly.dev/mcp`; no database, no key |

The MCP app reaches the API over Fly's private network (`<the API's private address>`,
encrypted by the platform, never the public internet), which is why `fly.toml` sets
`ORINYX_API_ALLOW_HTTP=true`. Agents are sent to the API's public origin for sign-in
(`ORINYX_ISSUER_URL`). The API must list this endpoint as an allowed resource.

```bash
fly apps create orinyx-mcp                      # once; the name is global on Fly
fly secrets set ORINYX_HOP_SECRET=<the same value the API has> -a orinyx-mcp
```

## Release provenance (gate B8)

Lex deploys from a clean `main` at the approved release commit. One Machine is enough;
there is no state to share. Fetch and fast-forward `main`, confirm its HEAD is the approved
release commit, then require a clean tree (including untracked files):

```bash
git switch main
git pull --ff-only
test -z "$(git status --porcelain)" || exit 1
release_sha=$(git rev-parse HEAD)
```

Before deploying, record the current Fly release, image digest and commit as the rollback
target using `fly releases -a orinyx-mcp` and `fly image show -a orinyx-mcp`. Keep the
registry image reference by digest, not just a mutable tag.

Deploy with the full release SHA as the image label and OCI revision label. The required
form is `fly deploy --image-label <sha> --label org.opencontainers.image.revision=<sha>`;
the same SHA must also be supplied to the Docker build so `/health` reports that commit:

```bash
fly deploy --ha=false -a orinyx-mcp \
  --image-label "$release_sha" \
  --label "org.opencontainers.image.revision=$release_sha" \
  --build-arg "COMMIT_SHA=$release_sha"
fly image show -a orinyx-mcp
```

**`fly image show` must succeed before the smoke test.** Confirm the deployed image label
and `org.opencontainers.image.revision` match `release_sha`, and record its immutable
`sha256` digest. Stop if the label, revision or digest cannot be confirmed. Docker also
bakes `COMMIT_SHA` into `ORINYX_COMMIT_SHA` and the OCI revision label. Do not override
`ORINYX_COMMIT_SHA` in Fly environment settings or secrets; it identifies the built image.
An unstamped local build returns `commitSha: null`, which is not release provenance.

Before the remaining smoke checks, require the deployed health SHA to match that same
release SHA. A missing, null or different SHA fails this check:

```bash
curl --fail --silent --show-error https://orinyx-mcp.fly.dev/health | \
  python3 -c 'import json, sys; body = json.load(sys.stdin); sys.exit(0 if body.get("commitSha") == sys.argv[1] else 1)' "$release_sha"
```

Only after the image and SHA checks pass, run the external smoke checks:

```bash
curl -i https://orinyx-mcp.fly.dev/health
curl -i https://orinyx-mcp.fly.dev/mcp                     # 401 with a resource_metadata challenge
curl https://orinyx-mcp.fly.dev/.well-known/oauth-protected-resource/mcp
ORINYX_API_KEY=<a tester key> python evals/mcp_local_check.py --url https://orinyx-mcp.fly.dev/mcp
```

For every Fly release, including a rollback, a DEPLOYED line is written in the deploy
record with the app, release number, image label, full commit SHA, immutable image
digest, deploy time and smoke-test result. Lex supplies the verified provenance; a deploy
command completing alone is not evidence that the running image matches the commit.
Apply the same image-label and OCI revision-label practice to `orinyx-api` and the dashboard
at their next deployments, using each application's own release commit. Those deployments
and live DEPLOYED records are separate from this repository change.

## Rollback (gate B16)

Lex rolls back to the previous known-good image, without rebuilding:

1. Run `fly releases -a orinyx-mcp`. Identify the previous known-good release and recover
   its exact image digest and commit from the recorded provenance. Use the digest captured
   before the new deploy; do not assume the current image is the rollback target.
2. Deploy that existing image by its immutable digest (replace `<digest>` with the
   recorded SHA-256 digest):

   ```bash
   fly deploy --ha=false -a orinyx-mcp \
     --image 'registry.fly.io/orinyx-mcp@sha256:<digest>'
   fly image show -a orinyx-mcp
   ```

3. Require `fly image show` to confirm the selected digest and its original revision before
   smoke testing. Compare `/health.commitSha` with the rollback image's recorded commit,
   then repeat the smoke checks above. Do not claim a provenance pass for an older image
   that lacks a SHA; record that limitation and escalate to Lex.
4. Write a new DEPLOYED line in the deploy record for the rollback release, including the
   reused image label, digest and commit, the release rolled back from, and the verification
   result.

**A tag is never deleted. A fix is a new tag.** Retain previous images and provenance so
rollback never depends on a rebuild. Do not overwrite a release tag or relabel an old image
as a new fix.

## Runtime configuration

`ORINYX_HOP_SECRET` is required: hosted MCP refuses startup without it, with no public REST
fallback. Use the same value on both apps (at least 32 ASCII characters; generate it with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`). The API requires both the
secret and an admitted private peer for MCP-audience OAuth and vendor machine exam calls.
It also charges and logs the agent's forwarded address only over that recognized hop.
Dashboard vendor sessions remain supported without the MCP secret; CLI exams stay disabled.

Apply engine migration 0034 and deploy its API before this client. Verify actual ASGI peer
handling after the proxy, authenticated introspection, a tool call and trace recording over
the private path; also test wrong/missing secrets and public peers. `/health` alone proves
none of those boundaries. Keep peer CIDRs narrow; coordinate secret rotation on both services.

To offer another MCP server's tools through this endpoint
([GATEWAY_TESTING.md](GATEWAY_TESTING.md#how-the-gateway-works)), set its address, the tools
to relay and its key as secrets, then redeploy:

```bash
fly secrets set -a orinyx-mcp \
  DOWNSTREAM_MCP_URL=https://<other host>/mcp \
  DOWNSTREAM_MCP_TOOLS=<tool>,<tool> \
  DOWNSTREAM_MCP_NAME="<what agents are told it is>" \
  DOWNSTREAM_MCP_TOKEN=<its key>
```

`fly secrets unset DOWNSTREAM_MCP_URL -a orinyx-mcp` turns the gateway off again. The Machine
reaches that host over the public internet, unlike the API.

## How the network server works

The variables it reads are in the README under
[Configuration](../README.md#network-server).

The bearer an agent presents is handed to the API's `GET /v1/auth/credential`, which
describes or refuses it (a positive answer is cached for 30 seconds by token hash; a refusal
is never cached); the tool call then becomes a REST request carrying that same bearer. The
process holds no database, no key of its own and no service credential. It serves `/mcp`,
`/health` and the RFC 9728 protected-resource document.
