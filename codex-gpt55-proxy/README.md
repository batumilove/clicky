# Clicky Codex GPT-5.5 OAuth Proxy

The current fork uses this loopback-only Node service for GPT-5.5 chat through Codex/ChatGPT OAuth and Deepgram transcription/speech. The separate Cloudflare Worker is a legacy Anthropic/ElevenLabs/AssemblyAI backend, not a relay to this service.

Codex OAuth stays on your Mac in `~/.codex/auth.json`. Never deploy it to a Worker or commit auth files, `.env` files, broker tokens, or captured private prompts.

## Prerequisites and first run

- Node.js **>=20.18.1**, matching `package.json`.
- Codex CLI authenticated with ChatGPT OAuth (`codex login`) and a valid `~/.codex/auth.json`.
- Deepgram credentials for `/transcribe` and `/tts`, supplied directly or through the configured Agent Vault broker.

For a new, inactive checkout:

```bash
cd codex-gpt55-proxy
npm ci --ignore-scripts
cp .env.example .env
# Configure Deepgram directly or the AGENT_VAULT_* broker settings.
npm run smoke
npm start
```

Do not overwrite an existing `.env`. Do not run `npm ci` in a live service's dependency directory; use the staged update procedure below. `npm run smoke` reads auth and checks startup configuration; it can refresh credentials, and does **not** make a real GPT chat request. Never run a second server on a port already owned by the managed service.

The service binds `127.0.0.1:8877` by default. Current Swift source uses that host for chat, transcription and TTS; `VoiceTranscriptionProvider` in `leanring-buddy/Info.plist` selects `deepgram`. Installed app bundles may differ from source defaults.

| Route | Contract |
|---|---|
| `GET /health` | Local liveness and configured model; not proof of upstream authentication |
| `POST /chat` | Anthropic-shaped request messages; streaming text from Codex Responses |
| `POST /transcribe` | Upload-based Deepgram transcription |
| `POST /tts` | Deepgram audio generation |

`/transcribe-token` is not implemented here. The retained AssemblyAI alternative requires an endpoint that actually implements that route; selecting it alone is not a working fallback.

## Configuration

- `PORT`: default `8877`; always loopback-bound by the server.
- `CODEX_AUTH_FILE`: default `~/.codex/auth.json`.
- `CODEX_MODEL`: default `gpt-5.5`.
- `CODEX_UPSTREAM_URL`: default `https://chatgpt.com/backend-api/codex/responses`.
- `DEEPGRAM_API_KEY`: required for voice unless broker settings supply credentials.
- `DEEPGRAM_STT_MODEL`: default `nova-3`.
- `DEEPGRAM_TTS_MODEL`: default `aura-2-thalia-en`.
- `DEEPGRAM_TTS_ENCODING`: default `mp3`.
- `AGENT_VAULT_ADDR`, `AGENT_VAULT_TOKEN`, `AGENT_VAULT_VAULT`, `AGENT_VAULT_CA_FILE`: optional broker configuration.

The server loads `.env` from its working directory. The installed macOS LaunchAgent may instead source `~/.clicky-codex-gpt55-proxy.env` before execution; inspect its actual plist. Do not print sourced environment values. Token refresh invokes `codex debug models` when auth is stale or upstream returns 401.

## Streaming acceptance contract

`/chat` emits `content_block_delta` objects containing `delta.type = text_delta` and `delta.text`, then finishes with `data: [DONE]`. This is **not** the complete Anthropic event lifecycle: do not require `message_stop` or non-streaming Anthropic JSON.

For a real, text-only GPT canary, send messages requesting exactly `CLICKY_PROXY_OK`, with `stream: true`, to `/chat`. Use a bounded request timeout. Parse SSE frames, join the text deltas in order, and require both the exact assembled text and `[DONE]`. HTTP 200, EOF, or a raw substring search alone is insufficient. Explicit errors, malformed required JSON, missing completion, and wrong text fail acceptance.

Before any outage, test the evaluator using valid text split across multiple events, wrong-text and missing-completion fixtures, malformed JSON and explicit errors. Use the same evaluator on the live response. Do not first discover the response contract after restarting production.

## macOS managed service

The locally installed LaunchAgent label is `ai.clicky.codex-gpt55-proxy`; verify this on the target Mac rather than assuming it exists:

```bash
launchctl print "gui/$(id -u)/ai.clicky.codex-gpt55-proxy"
plutil -p "$HOME/Library/LaunchAgents/ai.clicky.codex-gpt55-proxy.plist"
curl --fail --max-time 5 http://127.0.0.1:8877/health
lsof -nP -iTCP:8877 -sTCP:LISTEN
```

Record the actual executable, working directory, PID, bind address and source/dependency identity. A listener owned by another process is not a pass. Keep environment-file values private.

## Safe dependency update and rollback

Restart impact: **restart_required** for dependency activation; documentation edits are **restart_free**. Source publication, dependency installation and runtime activation are separate states and approval scopes. A local proxy dependency fix does not imply app replacement or Cloudflare deployment.

1. Record exact approved source commit, manifest/lock hashes, service definition, current PID and healthy before-generation. Prepare the candidate outside the live import path and preferably outside the Git worktree, on the same filesystem for rename-based replacement.
2. In the candidate only, run `npm ci --ignore-scripts`, `npm audit --audit-level=high`, `npm ls undici --all`, startup/auth smoke and relevant transport tests. Verify resolved versions, not just manifest ranges. Complete downloads/builds/review before the outage.
3. Preserve the complete original dependency tree and source/config identities. Test rollback imports/startup in isolation; keep credentials separate. Bind the candidate and rollback to hashes and the approved canary/lifecycle plan.
4. With activation approval, recheck identities. Stop **only** the owning LaunchAgent via `launchctl bootout`. Prove the exact old PID has exited within a bounded deadline before changing dependency bytes. If it survives, stop and investigate; do not swap.
5. Rename the complete original dependency directory to retained rollback storage, then the prepared directory into the live path. Do not run a package manager during the outage. Start the exact service once using `launchctl bootstrap` with its verified plist.
6. Require a distinct live PID, correct executable/cwd and loopback listener owner, expected installed dependency version, health, and a fresh real GPT SSE canary. Read health/PID again afterward. Preserve the result receipt and protocol output without secrets or private user input.
7. On failure, stop the failed generation and prove its PID is gone **before** restoring the complete rollback tree. Start the restored generation and verify its version/health. If shutdown cannot be proven, block byte restoration rather than mix generations.
8. Preserve each attempt's result separately. A harness mistake is not automatically a service defect; correcting an offline evaluation does not make a rolled-back generation live. Fix/test the harness and obtain retry approval for a changed acceptance plan.

Keep rollback until the agreed observation period passes. Synthetic text chat does not prove microphone capture, screenshot permissions, transcription, or speech playback. Report those separately when tested.

## Legacy Worker dependency overrides

`../worker/package.json` temporarily overrides Undici and Sharp because the retained Wrangler/Miniflare toolchain pins vulnerable transitive versions. Verify both its lock and installed tree with `npm audit` and `npm ls undici sharp miniflare wrangler --all` in an isolated checkout. Sharp updates can legitimately include its platform packages and libvips. Remove overrides only after a parent release resolves fixed versions without them and fresh audit plus tooling/image-processing checks pass. Do not deploy the Worker as part of a local proxy dependency update.
