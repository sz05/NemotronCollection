# Research: Why the Nemotron API keeps returning 502

**Date:** 2026-08-15 · **Method:** 3 parallel research agents (NVIDIA status/retirements, community 502 reports, current API docs) + adversarial verify/synthesize pass · **Endpoint under investigation:** `https://integrate.api.nvidia.com/v1/chat/completions` (hosted NIM, urllib client, lightweight 8B Nemotron model)

## Executive summary

A 502 from this gateway means the request reached NVIDIA's edge but the model backend didn't answer. The two most likely causes for a **consistent** 502 are: (1) the gateway's internal job deadline (~90–120s) expiring because the shared free-tier backend is too slow/saturated, and (2) the specific legacy 8B model id still resolving at the gateway while its backend is unhealthy or effectively decommissioned (fully retired ids return 404, not 502 — so "listed but not actually serving" is the dangerous middle state). A four-step curl sequence (below) discriminates between all five candidate causes in a few minutes.

NVIDIA publishes no official 502 semantics for this endpoint; all evidence is community forums/GitHub, so the diagnostics are designed to be self-sufficient.

## Ranked causes

### 1. Gateway job-queue timeout / backend overload — **likelihood: HIGH**
The shared free-tier backend queues the request, exceeds the gateway's ~90–120s internal deadline, and the edge returns 502 (body often reads `[502]: This job timed out after 120000 ms`). Fits this project's history: the 49B model was already hitting timeouts on this account/route.
- **Confirm:** print the raw 502 body (`exc.read()` — the client already logs it: check the app's warning log for `Nemotron API returned 502: ...`). A 502 that arrives only after ~90–120s = this cause; an instant 502 rules it out.
- **Fix:** retry with exponential backoff (treat 502 as retryable), use `stream: true`, keep `max_tokens` small, or move to a higher-capacity current model.

### 2. Model id routes but backend is unhealthy/zero-replica — **likelihood: HIGH**
Best fit for *consistent* 502s on a niche/legacy id. NVIDIA has removed hosted models without notice (forum report, Aug 7 2026), and `/v1/models` has been observed listing models that don't actually serve. Distinct from full retirement, which returns 404 `Function ... not found`.
- **Confirm:** `GET /v1/models` with your key and check your exact model string byte-for-byte; then run a minimal 8-token probe on your id vs a control model (`meta/llama-3.1-8b-instruct`). Your-model-502s/control-200 pins it here.
- **Fix:** migrate to a currently served id, e.g. `nvidia/nvidia-nemotron-nano-9b-v2` or `nvidia/nemotron-3-nano-30b-a3b` (or `nvidia/llama-3.3-nemotron-super-49b-v1.5` for the larger tier).

### 3. Non-standard payload field hangs the backend → gateway kills job as 502 — **likelihood: LOW**
Traces to one closed needs-info GitHub issue; NVIDIA's documented bad-payload behavior is 422. Less applicable here since the payload is hand-built with only standard fields. Kept because it's a 2-minute check.
- **Confirm:** send a minimal payload (model, messages, max_tokens, temperature only) via curl; if it succeeds where the app fails, binary-search the difference.

### 4. Edge/CDN client fingerprinting or regional filtering — **likelihood: LOW**
Real phenomenon on this host (it explains the earlier httpx-hangs-urllib-works observation), but it manifests as hangs/resets, not a returned 502.
- **Confirm:** run the identical minimal curl from a different network (hotspot/cloud VM). Different outcome by network = edge-side.

### 5. Account/key issues (entitlement, rate limit) mistaken for 502 — **likelihood: LOW**
These surface as 401/403/404 or 429, not 502. Worth one cheap check because an Aug 2026 entitlement wave produced cases where `/v1/models` returns 200 but `chat/completions` fails.
- **Confirm:** read the actual status code of a raw curl. If it's genuinely 502, eliminate this.

## Fastest discriminating sequence

```bash
# (a) time-to-502 + raw body
curl -sS -w '\nHTTP %{http_code} in %{time_total}s\n' \
  https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVAPI_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"<YOUR_ID>","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
# instant 502 → cause 2/4; ~90-120s then 502 → cause 1

# (b) verify the model id is still listed
curl -sS https://integrate.api.nvidia.com/v1/models \
  -H "Authorization: Bearer $NVAPI_KEY" | python3 -c \
  'import json,sys;[print(m["id"]) for m in json.load(sys.stdin)["data"] if "nemotron" in m["id"].lower()]'

# (c) control probe on a heavily-used model
#     same curl as (a) with "meta/llama-3.1-8b-instruct"
# your-id fails + control works → model backend (switch models)
# both fail → gateway/account/network side
```

Regardless of root cause: add backoff-retry on 502 in `app/services/nemotron.py`, prefer streaming, and prefer a current-generation Nemotron id over the legacy 8B v1 endpoint.

## Caveats / confidence notes
- All 502-semantics evidence is community-sourced (forums, GitHub); NVIDIA has no official docs on it. Confidence in the mechanism taxonomy: medium-high; in per-cause likelihoods: medium.
- The "~half of catalog ids no longer serve" claim rests on a single third-party blog post — treat as anecdotal.
- Akamai JA3/JA4 fingerprinting evidence is generic Akamai documentation, not specific to this host.

## Sources
- https://github.com/diegosouzapw/OmniRoute/issues/3884
- https://github.com/diegosouzapw/OmniRoute/discussions/3845
- https://github.com/NVIDIA/NemoClaw/issues/2980
- https://forums.developer.nvidia.com/t/cannot-access-https-integrate-api-nvidia-com-v1-chat-completions-receiving-504-timeout-error/372135
- https://forums.developer.nvidia.com/t/nvidia-nim-down/366913
- https://forums.developer.nvidia.com/t/every-call-to-post-v1-chat-completions-fails-with-a-404-error/377109
- https://forums.developer.nvidia.com/t/model-deprecation-request/378412
- https://forums.developer.nvidia.com/t/integrate-api-nvidia-com-hangs-indefinitely-when-request-is-sent-from-a-spawned-child-process/379835
- https://forums.developer.nvidia.com/t/403-authorization-failed-on-v1-chat-completions-v1-models-returns-200/379651
- https://stevescargall.com/blog/2026/04/using-the-api-to-find-free-hosted-models-on-nvidia-builder/
- https://docs.api.nvidia.com/nim/reference/create_chat_completion_v1_chat_completions_post
- https://docs.nvidia.com/nim/large-language-models/1.11.0/reasoning-model.html
- https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-nano-30b-a3b
- https://downforai.com/nvidia-nim (third-party monitor, methodology unverified)
