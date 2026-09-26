# The Jev integration

Specification and record of wiring TypeSafe AI's Jev into the AI programme.
Owner: Quentin Casares. Phase A of eight is built; phases B to H are not. No
Jev code exists in this repository, nothing here imports TypeSafe's SDK, and no
request has ever been sent to TypeSafe from it. Last revised 26 September 2026.

## What this is

The request was for Jev to take part in decision-making and categorisation,
following TypeSafe's official guidance. The operator's scope decisions:

- **Where Jev acts:** research and operations categorisation, recorded trading
  signals, and direct trade decisions. All of it on paper. The three live-money
  gates are not touched by any phase.
- **What "the web" means:** the web app shows Jev's output, Jev is understood
  from TypeSafe's published documentation, and Jev classifies web content.

The design in one paragraph: Jev is one more model client inside the one
process already permitted a model client, `src/programme`. It is not a new
pathway into the engine. Every answer is recorded once and replayed, never
recomputed. In research, operations, findings and guardrails Jev may add
friction and never remove it. Only answers built from code-computed,
point-in-time state could ever reach an order, only on paper, and only after an
amendment to Safety rule 5 that is proposed below and is **not in force**.

Phase A, the part that is built, contains no Jev at all. It fixes the defects
in this repository that the research found would have undermined the
integration, and draws the boundaries before the code they bound exists.

## What Jev is

Jev is TypeSafe AI's first "System One" model. It does not write text, code or
explanations. It takes a piece of state and a set of typed questions and
returns a typed, probabilistic answer to each, which code can branch on.

- **Endpoints.** The OpenAPI spec (version 0.2.0) has two paths:
  `POST https://api.typesafe.ai/v1/systemone` and `GET /v1/models`. There is no
  batch, streaming, webhook or regional endpoint. Authentication is a bearer
  token.
- **Request.** `{state, model, questions}`. `state` is a string, object or
  array of text. `questions` maps names chosen by the caller, which are not sent
  to the model, to questions of three types.
- **Response.** `{model, answers, usage}`. `model` is the versioned ID that
  answered, which may differ from the one requested.

| Type | Asks | Returns |
|---|---|---|
| Noul | Whether a condition holds | `noul`, a probability of yes. No `confidence` field |
| Choice | One of a defined set | `choice`, `probabilities` over the options, `confidence` |
| Score | A position on ordered levels | `score` (the probability-weighted mean of the 0-indexed levels), `legend`, `probabilities`, `confidence` |

**Models.** The only current model is `jev-1.13.0`. The alias `jev-latest`
tracks the most recent stable release and `jev-preview` moves ahead of it when a
preview build exists; both point at `jev-1.13.0` today. `GET /v1/models` lists
only the aliases, and versioned IDs are accepted anyway. An earlier `jev-1.12`,
the source of most cookbook figures, is unlisted and may or may not still be
callable. The docs also write `jev` and `jev-1.13`; whether the direct API
accepts either is unknown.

**Input** is text only. English is the primary training language and "where
accuracy is currently best".

## Which sources count as the guidance

"Official" means TypeSafe's own publications:

- **docs.typesafe.ai**: 111 pages, indexed by `llms.txt`, concatenated in
  `llms-full.txt`, each also served as Markdown by appending `.md`. It includes
  the API reference, the confidence and pattern pages, a jaggedness page for
  `jev-1.13`, the SDK documentation and changelogs, and the cookbooks.
- **api.typesafe.ai/openapi.json**, version 0.2.0.
- **TypeSafe's own `typesafe-ai/skills` SKILL.md**, which says the live docs
  are the source of truth, that "typed output guarantees the interface, not
  truth", and that cookbook thresholds are "examples to evaluate, not universal
  rules".
- For contract questions: the Master Customer Agreement (MCA), DPA, Acceptable
  Use Policy and Privacy Policy at `typesafe.ai/legal/`, the trust centre at
  `trust.typesafe.ai`, and the status page at `status.typesafe.ai`.

The official sources disagree with each other in places. The OpenAPI spec is
looser than the prose: it makes `instructions` optional, puts no cap on Choice
options or Score levels, and documents only 200 and 422. Where they disagree,
the code follows the stricter reading and this document says so.

**Not official:** the `jev-decisions` skill synced to the operator's account.
It is a paraphrase, not a TypeSafe publication and not the same file as
TypeSafe's SKILL.md. It is wrong or imprecise here:

| The synced skill says | What the official pages and live behaviour say | Consequence here |
|---|---|---|
| A cheap reversible action can act at 0.6; an irreversible one hands off to a human below 0.9 | Not an official rule. The Confidence page sends below 0.5 to a human and still wants confirmation above 0.9 for high stakes; the confidence-routing pattern uses 0.6 and 0.85. Other pages use 0.8, and 0.35/0.85 | No threshold in this repository comes from any of them. Each is measured on our own labels |
| 401 for an invalid key | Correct for a bad key. With no key the live API answers **403** `Must supply an API key!`, which the docs' own error table also gets wrong, and the Python SDK raises `TypeSafePermissionDeniedError` for it | Both 401 and 403 are treated as authentication failures |
| 529 means "overloaded" | The Python SDK has no overloaded class. Every status of 500 or above, 529 included, surfaces as `TypeSafeInternalServerError` | 529 is handled with every other 5xx, as transient, and the stored status says which it was |
| "A single question is capped at 32k" | 64k tokens per request for state plus **all** questions, and 32k for state plus the **single longest** question | The catalogue caps both below the vendor's figures |
| Score takes 2 to 10 levels; Choice up to 255 options | Stated in the prose docs. The OpenAPI spec encodes neither; whether the server enforces them is untested | The question-set validator enforces the prose limits itself |
| "Both SDKs back off automatically and honour `retry-after`" | True. The Python SDK honours it with no cap; the JavaScript SDK caps it at 60 s | An explicit retry policy |
| "Both SDKs default to the correct endpoint" | True, and both silently honour a `TYPESAFE_BASE_URL` override with no host check | The base URL is passed explicitly |
| Examples use `jev-latest` | The docs advise pinning the versioned ID wherever thresholds are tuned | Pinned, and aliases refused |
| Latency of 70 to 500 ms | That is the launch blog's figure. The docs say about 100 ms; independent medians run 127 to 430 ms, and about 1.4 s through a proxy | Nothing on the decision or order path waits on a call: answers are stored first and read later |
| Lookalike domains exist | No TypeSafe source warns of them; registration records support the substance | Kept, and enforced (below) |

## The evidence, and how far it goes

Five research passes read the official documentation end to end, audited the
SDK's source and provenance, read the contract, mapped the access routes, and
gathered independent studies and the academic literature. Fourteen claims the
design depends on were each put to three sceptics; eleven survived. The other
three failed on details, and the corrections are applied throughout this
document:

- **Errors.** Not every SDK error carries a request id. Connection and
  timeout errors carry none, because there was no HTTP response, and an HTTP
  error's is None when the response lacks the request-id header.
- **Gateways.** Vercel does not cap context below the direct API: it and
  DigitalOcean state the same two limits. OpenRouter and Cloudflare list
  32,000 tokens without saying which limit that is. OpenRouter's "floating"
  snapshot is an inference, not an observation.
- **Calibration.** The independent figures quoted were selective and partly
  overstated. The ranges below are the corrected ones.

The limits of that evidence matter more than any single figure. **Nobody held
an API key.** The only live calls were unauthenticated probes of
`api.typesafe.ai`, so every statement about the model's behaviour comes from
TypeSafe's cookbooks or from third-party studies, most of them single-author,
small and days old. Everything below is as of 25 September 2026, ten days after
launch, and SDK releases, prices, access and gateway listings all changed within
those ten days. The dossier and verification record were working files of that
session and are not in the repository; this section is their durable summary.

## The facts that drive the design

### 1. Jev is not deterministic, even with the model pinned

- The API has no seed, temperature, cache or idempotency control. The OpenAPI
  request has exactly three properties: `state`, `model` and `questions`.
- A vendor cookbook sent five byte-identical requests to `jev-1.12`. Eleven of
  thirteen answers did not move. Two Noul answers did: standard deviation
  0.0055 in both batching strategies for one, and 0.0045 batched and 0.0084
  single for the other.
- The vendor's two self-consistency cookbooks (`jev-latest`, answered by
  `jev-1.13.0`, fifteen calls each) put a throwaway `uid` in the state, and say
  themselves that this "cannot separate sensitivity to the irrelevant field from
  variation that would occur on identical requests". Choice labels split 11/4
  and 8/7 on two of eight questions, and one Noul ranged from 0.43 to 0.53,
  across a 0.5 line.
- One independent benchmark sent byte-identical requests, answered by
  `jev-1.13.0`: 2.2% of labels flipped between two passes over 2,000 items, and
  probabilities moved by up to 0.15. Re-run twelve hours later, 1.0% of 200
  items flipped.
- **Qualifier.** Every `jev-1.13` observation requested an alias. That a
  request pinned to `jev-1.13.0` varies as well is a strong inference, not an
  observation. The vendor promises only that Jev is "designed for consistency".

**What it forces: record once, replay forever.** Every answer is written once to
an append-only ledger, keyed by a hash of the canonical request, and everything
downstream reads the stored row. A backtest never calls Jev, so
`tests/unit/test_parity.py` keeps its meaning, and `target_weights` stays pure.
About 5% of requests are deliberately re-asked in a separate probe lane,
excluded from any canonical use, to measure the flip rate near each threshold.

### 2. The SDK is authentic, and its defaults are not ours

- `typesafe-sdk` 0.7.1 on PyPI carries a PEP 740 (Sigstore) attestation that
  verifies against `typesafe-ai/typesafe-sdk-python`,
  `.github/workflows/publish.yml` at tag `v0.7.1` (commit `0ffd094c…`), and the
  wheel is byte-identical to the tag. It has no install hook, `.pth` file or
  native code, and contacts only its base URL. Every request carries SDK and
  runtime headers naming the Python version, platform and architecture.
- It is MIT licensed, but the LICENSE file is the unfilled template,
  `Copyright (c) [year] [fullname]`. The GitHub organisation is unverified and
  the repository is a bot-pushed mirror of private development.
- **0.7.1 is the floor.** An explicitly passed key containing an illegal header
  character, a trailing newline for instance, is echoed into connection-error
  text in 0.5.7, 0.6.0 and 0.7.0. 0.7.1 strips, validates and redacts it.
- The attestation covers the SDK alone. Its dependencies (`httpx2`, a young
  fork; `pydantic`; `pydantic-core`, which is native; `tenacity`;
  `typing-extensions`) are not attested, so the whole tree is hash-locked.
- It ships a synchronous and an asynchronous client. This repository is async
  throughout and uses `AsyncTypeSafeClient`.
- The constructor's key check only refuses an empty key or one with whitespace,
  control or non-ASCII characters. A wrong key is discovered at the first
  request.

| SDK behaviour | Why it matters | Neutralised by |
|---|---|---|
| Honours `TYPESAFE_BASE_URL` with no scheme or host check | One environment variable sends the key and every request anywhere | `base_url=JEV_BASE_URL`, passed explicitly from `jev_catalogue.py` |
| Defaults to the alias `jev-latest`, or to `TYPESAFE_DEFAULT_MODEL` | The answers behind an alias change without a change here | `model=` passed explicitly; the catalogue refuses aliases; `response.model` must equal the pin |
| At DEBUG, logs full request and response bodies unredacted. `TYPESAFE_LOG_LEVEL` is read once, at import | Everything sent to TypeSafe lands in the logs | `TYPESAFE_LOG_LEVEL=off` before import, then the `typesafe_sdk` logger forced above CRITICAL |
| `extra_body` is merged last and shallowly | It can silently replace `state`, `model` or `questions` | Never used |
| The default policy makes three attempts, retries a non-idempotent POST with no idempotency key, and honours `Retry-After` uncapped | Whether a retried call is billed is undocumented, and a server can stall a pass | `RetryPolicy(max_retries=1, timeout=20)` and a 10 s per-request timeout |

### 3. A well-typed response can still be wrong

- On the default, untyped path `answers` defaults to `{}`, so a 200 with no
  answers parses without raising.
- An answer of an unrecognised type is dropped with a log warning.
- Probabilities and `confidence` are never range-checked. The maintainer's view
  is that "our API already guarantees the right range".
- On `jev-1.13.0`, `choice` is sometimes exactly 0.01 below another option's
  probability, in near-ties at low confidence (SDK issue #15). The 35 cases
  come from one third-party reporter; TypeSafe acknowledged the problem and gave
  no fix date.
- Values have been observed on a 0.01 grid, which TypeSafe does not document,
  and Choice and Score can return exactly 0 or 1. Noul values have only been
  observed within 0.01 to 0.99; that too is an observation, not a bound.
- `response.model` can differ from the model requested.
- Noul has no `confidence`. For Choice and Score, `confidence` is computed from
  the probabilities (the docs give `(n·p_max − 1)/(n − 1)` as an approximation)
  and measures how concentrated the distribution is, not whether the answer is
  right.

So `jev_validate.py` parses the raw JSON body itself. Every question asked must
be answered and no other; each answer's type must match; probability keys must
equal the criteria, values must lie in [0, 1] and sum to 1 ± 0.02; Score keys
must be `"0"` to `"n-1"`; the argmax is recomputed, and a mismatch counts as an
abstention; and `response.model` must equal the pin. **An invalid answer is
stored with its reason and consumed as not measured, never as 0.**

### 4. Errors, retries and request ids

| Condition | Status | Python SDK class | Handling here |
|---|---|---|---|
| No key sent | **403** (the docs say 401) | `TypeSafePermissionDeniedError` | Authentication failure: the lane is disabled for the day |
| Invalid key | 401 | `TypeSafeAuthenticationError` | The same |
| Request failed validation | 422 | `TypeSafeUnprocessableEntityError` | That question set is disabled |
| Rate limited | 429 | `TypeSafeRateLimitError`, with `.retry_after_ms` | Transient |
| Overloaded, or any server error | 529, or any 5xx | `TypeSafeInternalServerError` | Transient |
| Another 4xx, 408 for instance | | `TypeSafeAPIError` | Recorded by class |
| No HTTP response | | `TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError` | Transient. **No request id exists** |
| Malformed 200 | | `TypeSafeAPIResponseValidationError` | Invalid |
| A 403 whose body is not JSON | 403 | `TypeSafePermissionDeniedError` | The document is quarantined as a possible content block. A precaution: it rests on one unverified third-party report, and the verification found no primary evidence for it |

The request id comes from the `x-typesafe-request-id` response header. Among
the SDK's errors only `TypeSafeAPIError` and its subclasses carry
`.request_id`, and theirs is None when the header is absent. So a NULL
`vendor_request_id` means only that no request id came back: either there was
no HTTP response, or there was one without the header, which the non-JSON 403
in the table above plausibly would be. The HTTP status is stored beside it,
NULL only when there was no response, and that is what tells the two apart.

Rate limits are 250,000 tokens a second and 1,200 requests a minute, which the
docs say "can change without notice". A client-side token bucket keeps under
both.

### 5. Calibration does not transfer

- TypeSafe publishes no results on public benchmarks, by its own choice. Its
  headline speed and cost multipliers score every model against the average of
  two frontier LLMs' answers, not against ground truth.
- The only accuracy figure on financial text in the docs is a cookbook run on
  `jev-1.12`: 60 10-K excerpts, pre-filtered to filings whose own text supports
  their industry code, split by a 0.9 confidence cutoff into halves that scored
  27/30 and 12/30. Thirty items a side cannot measure calibration.
- Independent accuracy at a probability of 0.9 or above: 73.9% on phishing
  (30.8% coverage), 82.8% on a moral-judgement set (24.2% coverage), 100% on
  synthetic difficulty tiers, 99.9% on spam. Expected calibration error runs
  from about 0.02 to 0.33 depending on the task. One pre-registered study found
  accuracy flat from 0.50 to 0.95. **A threshold measured on one task says
  nothing about another.**
- **Jev always answers.** A cake recipe was classed as a technical issue at
  0.94. Without an escape option, 0 of 30 out-of-scope messages were flagged;
  with one, 21 of 30 were. An escape option helps; it does not solve the
  problem.
- **Option order** moved one ambiguous task's probabilities by 13 points in an
  exploratory, post-hoc comparison. The pre-registered first-versus-last test
  found 3.5 points, the prediction failed, and on clear items 0 of 192 answers
  moved. Freezing the order is cheap insurance, not a response to a large
  measured effect.
- The vendor's jaggedness page documents that answers are not consistent across
  question forms (a Noul and a Choice over the same judgement can disagree
  sharply), so a threshold tuned on one primitive does not transfer to another.

What the design does:

- A threshold is per question set, per question and per model, measured on this
  repository's own labels. None may be used until `jev_evaluations` holds one
  with at least 200 labelled items that beats both a majority baseline and a
  keyword baseline. Until then every lane is suggestion-only and the UI says
  "not calibrated".
- Every Choice question carries a "none of these" option, and "is this in scope"
  Nouls are asked first where they apply.
- Question sets are versioned. Option order is frozen and hashed, and changing
  a question's text without bumping its version fails a test.
- **A recorded departure from the official guidance.** The Confidence page wants
  a human to confirm even above 0.9 when the stakes are high. For the direct
  decision lane — paper only, a fixed universe, `apply_risk`, a hard capital cap
  and a separate account — the operator chose autonomy. That choice is to be
  stated in CLAUDE.md and on the strategy's page when the lane exists.

### 6. No training cutoff is disclosed, and the weights hold world knowledge

- TypeSafe discloses no training cutoff, base model or pretraining corpus. Its
  statements sit in tension: "we make all the data ourselves", and a reported
  "trained exclusively on synthetic data", against a primer presenting its
  method as post-training applied to pretrained language models, and a docs
  line advising "do not rely on knowledge stored in model weights when current
  information can come from your own knowledge base".
- An independent probe scored 94.2% on a public question-answering benchmark
  given only the question stem, so the model knows things its input did not
  tell it.
- The literature finds that language models recall pre-cutoff financial facts,
  that instructions to respect dates and masking do not remove the effect, and
  that the resulting bias is uncontrolled: usually inflating, not always.

**Consequence.** Any Jev label on text dated before the model's unknown cutoff
is not a point-in-time label, and a walk-forward over historical Jev labels is
not a clean test. Only labels collected going forward and stored can back a
result. Public evaluation sets are labelled "possibly in training, upper
bound"; thresholds are gated on a held-out set assembled after the model's
release.

### 7. The contract is thin

- **No uptime SLA.** The MCA's "as is, as available" is qualified only by a
  warranty that the service performs "materially as described in its
  Documentation", with a fix or termination as the remedy. Liability is capped
  at the greater of twelve months' fees or $50.
- **One region, observed from one place:** AWS us-west-2. The vendor's own
  status page reports 99.826% API uptime over 90 days, and shows downtime on
  about 25 days of which most have no incident posted.
- **New signups are paused**, per TypeSafe's X post of 22 September and a
  banner on `typesafe.ai`; existing accounts keep working. No docs page says so,
  and whether the pause continues was not confirmed.
- **Inputs.** TypeSafe will not train model weights on customer data without
  consent (MCA 4.1), but MCA 4.1(c) grants it a perpetual licence to derive
  "Telemetry" from that data, which MCA 4.3 defines to include "summary
  statistics and classifications, metrics, and learnings" and lets it process
  "without restriction". The no-training promise covers weights, nothing else.
- **Zero data retention is enterprise-only.** All six subprocessors are in the
  USA, with no EU or UK residency.
- **No distillation.** MCA 2.3(b) forbids using output to train a model that
  imitates it. That sits uneasily with TypeSafe's own cookbook on training
  downstream models on Jev probabilities; legal review would be needed before
  any such use, and none is planned.
- **No security testing** of TypeSafe's systems is permitted (MCA 2.3, AUP 3.7).
  The probe lane measures consistency on this system's own ordinary requests
  and is nothing else.
- **No model changelog or deprecation policy**, and no retention window for a
  pinned version. MCA 2.5 promises only "commercially reasonable efforts" to
  give notice of changes TypeSafe itself judges materially adverse.
- **Price:** $0.042 per million input tokens, output currently free, bought as
  prepaid credits that expire within twelve months.

**Defaults that follow,** applied unless the operator says otherwise: send
public web content and code-computed features; send hypothesis cards and
findings as titles only, their detail going only if `jev_send_internal_detail`,
which starts off, is switched on; never train a model on Jev's output; and
treat Jev as absent whenever it is, which means a missing answer holds rather
than guesses.

### 8. Direct API only

TypeSafe's docs name two gateways, OpenRouter and the Vercel AI Gateway;
Cloudflare, LiteLLM and DigitalOcean document Jev on their own pages.

| Route | Can request exactly `jev-1.13.0`? |
|---|---|
| Direct, `api.typesafe.ai` | Yes |
| LiteLLM pass-through | Yes; it forwards the request unchanged |
| DigitalOcean | Yes, as `typesafe-jev-1.13.0` |
| OpenRouter, `typesafe/jev-1.13` | The minor version only: it "resolves to the current 1.13 release". One dated snapshot exists so far |
| Vercel AI Gateway, `typesafe-ai/jev` | No. It routes to TypeSafe or to DigitalOcean, and its response names the provider but not the version |
| Cloudflare Workers AI, `typesafe/jev` | No. Its input schema has no model field |

Three routes can pin, and two of them put someone else between this system and
TypeSafe: another contracting party, another data path, another hop. On
context, Vercel and DigitalOcean state the direct API's two limits, 64k in
total and 32k for state plus the longest question. OpenRouter and Cloudflare
list 32,000 tokens without saying whether that is a total or the same
sub-limit, though OpenRouter's "the state you send plus the questions" reads
like a total. None is shown offering more than the direct API, so they buy
nothing here. The design uses the direct API alone.

### 9. Lookalike domains and packages

The official surfaces are `typesafe.ai` and its `api.`, `console.`, `docs.`,
`status.` and `trust.` subdomains; the GitHub organisation `typesafe-ai`; PyPI
`typesafe-sdk`; and npm `@typesafe-ai/sdk`. In the days after launch — the
domains below were registered one to five days after it:

- **Resellers with their own endpoints and billing**, which put a third party
  in the data path and the payment path: `jevtypesafeai.com`, `jev-api.com`
  (which tells coding agents to install its own SKILL.md and set
  `JEV_API_KEY`), `thejevai.com` (selling "Jev-Omni" under the Jev name,
  which its own page discloses is a third party's model built on Gemma 4 12B,
  not TypeSafe's), `jevmodel.org` and `jev-ai.pro`.
- **Sites inviting a user to paste a real TypeSafe key:** `jev.works` and
  `jev.guru`, tied to a GitHub organisation called `TypeSafeAI`. A second
  lookalike organisation is `jev-ai`.
- **Packages that are not TypeSafe's:** on PyPI, `typesafe-ai` (a third-party
  shim that depends on the real SDK), `typesafe-client` (a placeholder) and `jev`
  (no author, not traceable to TypeSafe), among others. On npm, `typesafe-sdk` —
  the official **PyPI** name — is an empty 66-byte placeholder from a third
  party.
- **`pypi.typesafe.ai`** resolves to TypeSafe's addresses and returns 404. A
  third-party placeholder claims it once served the SDK unauthenticated, which
  is unverified. **It is never to be added as a package index.**
- `typesafe.com` belongs to the historic, unrelated Typesafe Inc.

TypeSafe itself has published no warning. Phase A enforces the rest (see below):
the only TypeSafe distribution permitted is `typesafe-sdk`, from PyPI; nothing
points pip at another index; no npm package presenting itself as TypeSafe's is
installed, the official `@typesafe-ai/sdk` included, because the frontend holds
no model client; none of the eight lookalike hosts above is named, as a host or
as a subdomain of one, in `src/`, `web/src/` or the files that install, build
and deploy them; and `JEV_API_KEY` is named in no product file. A host added to
this section is one the scan must read, or
`test_every_host_the_doc_names_is_scanned` fails.

### 10. What this repository lacked

The research also read this repository, and found six gaps that had to close
before any Jev code could land safely. Phase A closes the first five; the sixth
belongs to phase H.

1. `FORBIDDEN_PREFIXES` did not name `typesafe_sdk`, and the scan compared the
   first segment of an import against it, so a Jev import in the worker, the API
   or the decision path would have passed.
2. `tick._convene` never ran the specialist panel.
3. `POST /deployments/{id}/enable` did not ask the deployment gate.
4. The worker claimed every job kind in the shared queue.
5. The programme's compose service inherited the broker keys.
6. Every deployment trades through the one paper account:
   `live_job._alpaca_from_env` builds each broker from a single environment
   credential pair.

## Architecture (planned)

Nothing in this section exists yet. It is what phases B to H build, and every
switch it names reads as off when it cannot be read.

```
   web content, allow-listed          daily_bars
             │                            │
             ▼                            ▼
   programme/web_ingest.py        programme/jev_features.py   (pure; code-computed
             │                            │                     descriptors, no text)
             └──────────────┬─────────────┘
                            ▼
                programme/jev_lane.py  ◄── jev_questions, jev_validate (pure)
                            │   hash → look up → call once → validate → write
                            ▼
                programme/jev_client.py ──────────────► api.typesafe.ai
                            │   the only importer of typesafe_sdk
                            ▼
   ┌──────────────────────── Postgres ─────────────────────────┐
   │ jev_requests · jev_answers · jev_signals · web_documents  │
   │ jev_labels · jev_evaluations                              │
   └───────┬──────────────────────┬────────────────────────────┘
           ▼                      ▼
   src/api (jev_repo,     src/db/repos/signals.py (phase F): lane 'decision',
   read only; enqueues)   provenance 'internal', available by the cutoff
                                  │
                                  ▼
                   Driver.decide → apply_risk → a paper forward_experiment
```

### Modules in `src/programme/`

Flat files, not a subpackage, so the transitive boundary test sees each one.

| Module | Role |
|---|---|
| `jev_catalogue.py` | Pure, and importable by the API. `JEV_BASE_URL`; an allow-list of pinned IDs matching `^jev-\d+\.\d+\.\d+$`; the refused aliases `jev-latest`, `jev-preview`, `jev` and `jev-1.13`; the size limits, 56k tokens in total and 28k for state plus the longest question, both estimated conservatively; and one `settings_problem()` shared by the form and the runner |
| `jev_questions.py` | Pure. Versioned question sets: name, version, lane, provenance, questions, and a `state_model` (pydantic, `extra='forbid'`). Each has a golden hash. Every Choice has an escape option and a frozen option order |
| `jev_validate.py` | Pure. The response rules in fact 3 |
| `jev_features.py` | Pure. Turns a `PricePanel` into enumerated descriptors computed in code — trend relative to the 200-day average, a volatility quintile, a drawdown bucket. The decision lane's only state |
| `jev_repo.py` | Queries for the Jev tables. No SDK, so the API can import it |
| `jev_client.py` | The only importer of `typesafe_sdk`, lazily, runner-only. Constructs `AsyncTypeSafeClient(api_key=…, base_url=JEV_BASE_URL, model=<pin>, retry=RetryPolicy(max_retries=1, timeout=20), timeout=10)` with the key read from the vault, then the environment. Records the error class; runs the token bucket |
| `jev_lane.py` | Runner-only. One pass: budget, build the state, hash, look up, call, validate, write, route. The signal packs live here and never import `client.py`, so on the signal path the cascade ends at Jev |
| `web_ingest.py` | An allow-listed `aiohttp` fetcher: the paperswithbacktest README on GitHub and the SEC EDGAR RSS feed. Stores excerpts only, strips markup and URLs, caps lengths |

### Outside `src/programme/`

- `src/db/repos/signals.py` is the **only** reader of `jev_signals` outside the
  programme. Its filter is fixed: `lane='decision' AND provenance='internal' AND
  available_at <= decision_cutoff(session)`, plus a fail-closed area switch.
- `src/core/panel.py` gains an optional signals channel, sliced as of the
  session like the prices. `src/strategies/base.py` gains
  `required_signals: ClassVar = ()`.
- One loader is called at every site that constructs a `Driver` —
  `backtest_job`, `walkforward_job`, `live_job` (the decision and `dry_run`),
  `shadow_job`, `src/api/drain.py` and `src/cli.py` — and a test proves each
  site uses it.
- The programme's `main.py` gains a Jev loop beside the heartbeat, gated by
  `jev_enabled`, handling its own job leases. The worker already claims only
  its own kinds (Phase A); scheduled kinds become two disjoint sets, one per
  process, each kind with exactly one owner.

### Keys and dependencies

- `typesafe_api_key` joins `KNOWN_SECRETS` and the configuration form, with a
  warning against lookalike keys. Resolution is vault, then environment, and the
  key is always passed as `api_key=`. `TYPESAFE_API_KEY` joins `.env.example`
  with no value.
- `JEV_API_KEY`, the reseller's variable name, is never used.
- `requirements-programme.txt` gains `typesafe-sdk==0.7.1` and
  `pydantic>=2.12`, the SDK's floor (`requirements.txt` says `>=2.7.0`). A
  hash-locked `requirements-programme.lock` covers the whole tree.
- A separate CI job runs the SDK-marked tests against a fake TypeSafe server
  over real HTTP. The main CI job stays SDK-free.

### Schema: migration `0012_jev.sql`

| Table | Holds |
|---|---|
| `jev_requests` | Append-only. The request hash (sha256 of the canonical `{model, state, questions}`, option order preserved), the state hash, question set and version, lane, provenance, subject, `as_of`, the state and questions sent; the model requested and the model that answered; the vendor request id (NULL when none came back, whether there was no HTTP response or one without the header), the HTTP status (NULL only when there was no response, which is what tells those apart), `status` of `ok`, `invalid`, `error` or `refused_budget`, the error class, the raw body, tokens and latency; `requested_at`, and `available_at` set to `NOW()` by a trigger. A partial unique index on the request hash where the status is `ok` and the lane is not the probe lane |
| `jev_answers` | One row per question: `noul`, `choice`, `score`, `probabilities`, `confidence` (NULL for a Noul), our own argmax and margin, `valid` and `invalid_reason` |
| `web_documents` | Append-only snapshots with a content hash and a one-way `quarantined` flag |
| `jev_signals` | Frozen by a trigger. Keyed `(signal, symbol, session)`, with status, the answer, lane, provenance, `available_at`, and a generated `backfilled` column: liveness is derived by the database, never written by the caller |
| `jev_labels` | `labelled_by` is `operator:…` or `source:<dataset@sha>` |
| `jev_evaluations` | Per question set, question and model: the dataset and its hash; n and n per class; accuracy with Wilson bounds; Brier score with a bootstrap interval; calibration bins; the threshold and its coverage; baseline accuracy; flip rate; `possibly_in_training`; the code commit |

Changes to existing tables: a sticky `candidates.evidence_uses_model_signals`;
signal-provenance columns on `backtest_runs` and `walkforward_runs`, computed
from the rows actually served (counts of live, post-release backfill and
pre-release backfill, the model IDs served, the pack hashes); and
`deployments.evidence_class`, `'walkforward'` or `'forward_experiment'`, with a
CHECK that `forward_experiment` implies `mode='paper'` and an owner other than
`default`, so only a new migration can relax it.

### Switches, all fail closed

Seeded in `system_flags` and read through the same broad `except` as
`programme_enabled`: `jev_enabled` false; `jev_model` `jev-1.13.0`; one area
switch each for research, ops, findings, guardrails, signals and decisions, all
false; `jev_daily_request_budget`; `jev_max_state_tokens`; and
`jev_send_internal_detail` false. A missing row, an unreadable value or a
database error reads as off, and a model setting the catalogue refuses means no
call — the same rule `flags.model_settings` already applies.

## Lanes

Planned, like the architecture above. None of these lanes exists.

| Lane | Question sets | State | What Jev may do | What it may never do |
|---|---|---|---|---|
| Research | `research.catalogue_v1` (asset class, mechanism, whether daily OHLCV suffices, rebalance horizon), `research.news_v1` (relevance, event type, tone). `guardrail.injection_v1` ("contains instructions addressed to an AI") runs first | Allow-listed web excerpts | Label the catalogue page; rank a shortlist `author.py` may use to prioritise; quarantine what the injection screen flags | Satisfy any gate criterion |
| Guardrails | Card checks beside `find_performance_claim`: a performance claim, an untestable falsification test | Hypothesis cards, as titles unless the detail switch is on | A "yes" rejects or raises a finding | Accept anything. A "no" changes nothing, so the accepted set with Jev is a subset of the set without it — a property test |
| Findings routing | Owning role (the twelve plus "unclear"), likely duplicate, suggested severity | Findings, as titles unless the detail switch is on | Suggest | Write `severity` or `status`. Findings it raises carry `raised_by='jev:<set>'`, never in `VETO_ROLES` |
| Ops triage | Job errors, reconciliation discrepancies, data-quality alerts, through a redactor | Free text only; code handles structured cases first | Show chips on System > Jobs | Resume anything, or touch the kill switch |
| Recorded signals | `signal.news_tone_v1` | Web content | Be recorded and scored going forward | Be loaded by the decision path. The loader's filter excludes web provenance by construction |
| Direct decisions | `decision.regime_v1`: a Choice over `risk_on`, `neutral`, `risk_off`, `insufficient_evidence` | Only `jev_features` descriptors: internal provenance, which no outsider can write to, so the prompt-injection route recorded as C-1 in `docs/02-security-audit.md` stays closed | Feed `jev_regime_allocator`, a pure strategy with a fixed universe and fixed weight vectors declared in code; the pack hash and threshold are its parameters | Act on a missing, invalid, argmax-mismatched or below-threshold answer: each means **hold** |

A code baseline twin — the same descriptors through a fixed rule — runs beside
the allocator. The honest expected edge is zero until forward measurement says
otherwise. For the decision lane the threshold is a strategy parameter chosen
on forward-collected data only, and it counts as a trial in the deflated
Sharpe.

## The Rule 5 amendment — PROPOSED

> **PROPOSED. Not in force.** It lands in phase F with the tests that enforce
> it. Until then Safety rule 5 in CLAUDE.md governs as written: no model output
> reaches an order, and Jev is a model.

The proposed wording:

> *Generative model output never reaches an order. Typed Jev answers may reach
> an order only as `jev_signals` rows with lane `'decision'` and provenance
> `'internal'`, read through `src/db/repos/signals.py`, by a strategy declaring
> `required_signals`, through `Driver.decide` and therefore `apply_risk`, in a
> paper-only `forward_experiment` deployment.*

What must hold before it can land, and which of it exists:

| Enforcement | Built, or the phase that brings it |
|---|---|
| The TypeSafe names (`typesafe_sdk`, `typesafe`, `typesafe_ai`, `jev`, `cooksafe`) are forbidden imports for every protected package, matched on whole dotted segments. `httpx2`, the SDK's transport, is not: it is a general HTTP client like the `aiohttp` the worker already holds, and the host scan below is the control on HTTP | Built, Phase A |
| `api.typesafe.ai` and `/v1/systemone` may be spelled only in `jev_catalogue.py` and `jev_client.py`, across `src/`, `web/src/`, `api/`, `scripts/` and every entry point | Built, Phase A |
| No model vendor's API host is spelled in any module a protected process loads, nor in `web/src`; TypeSafe's is allowed only in the same two files | Built, Phase A |
| `jev_client` and `jev_lane` are runner-only, and `from src.programme import x` is read as importing `x` | Built, Phase A |
| The closure is walked from every protected package and every entry point, resolving packages, relative imports, function-level imports and star imports through `__all__` | Built, Phase A |
| The decision path and `src/worker` may not load `src.programme` at all | Built, Phase A |
| Outside the programme, only `signals.py` may name a Jev table | Phase B, extended in F |
| `jev_lane` is the only writer of `jev_signals`; `client.py`, `author.py`, `panel.py` and `tick.py` never name it | Phase B |
| `apply_risk` and `weights_to_orders` are called only from `Driver` | Phase F |
| A strategy with `required_signals` is refused `mode='live'` at create, at enable and in `run_live_decision` — a fourth refusal, additive to the three live-money gates | Phase F |
| `signals.py` excludes web-provenance, backfilled and switched-off rows | Phase F |
| Parity holds with signals, including missing, late and below-threshold ones | Phase F |
| The `jev_signals` freeze trigger holds | Phase B |
| `forward_experiment` is paper-only by CHECK constraint | Phase H |

## Honesty rules for Jev

The honesty rules in CLAUDE.md apply unchanged. These are what they will mean
for Jev, phase by phase, as the code that they govern lands.

- **Point-in-time loading.** The signal loader serves only rows available at or
  before the decision. A backfilled answer therefore reads as not measured.
- **No label leaks into what is evaluated.** Label fields are stripped from
  evaluation state, and a test proves it.
- **Public evaluation sets are an upper bound.** The 61-strategy README set is
  labelled "possibly in training". A held-out set assembled after the model's
  release is what gates a threshold.
- **Report the uncertainty and the floor.** Balanced accuracy, per-class Wilson
  intervals, Brier score, and both a majority and a keyword baseline, every
  time, with n.
- **Measure the noise.** About 5% of requests are re-asked in the probe lane to
  measure the flip rate near each threshold.
- **Contaminated evidence is refused**, not flagged: by `_walkforward_verdict`,
  the deployment gate at create and at enable, the backtest enqueue guard, and
  the programme's `evidence_is_real` criterion — each tested by driving the
  shipped route.
- **A forward experiment is labelled as one.** A `forward_experiment` deployment
  needs at least 20 error-free shadow sessions, signal coverage of at least 95%
  and a capital cap, and reads "forward experiment, not validated by
  walk-forward" everywhere it appears. Its results are a paired difference
  against the baseline twin, with the session count and the standard error.

## Web UI rules

For phase E, and for every page that shows a Jev answer after it.

- Probabilities and `model_answered` are shown inline, never only in a tooltip.
- `confidence` is labelled "concentration, not probability correct". A Noul
  shows "n/a".
- A "choice ≠ argmax" badge wherever it applies.
- "Not measured" is a third filter state, and an unknown never sorts as a low.
- Vendor accuracy is shown as "not published by TypeSafe".
- The catalogue page opens outbound links over https only, republishes no
  abstract, and uses no `dangerouslySetInnerHTML`.
- The API never calls Jev. `POST /jev/probe` enqueues work; it does not run it.

Planned surfaces: a router, `src/api/routers/jev.py`, importing only
`jev_repo`, `jev_catalogue`, `jev_questions` and `flags`, with status, answers,
signals, catalogue and evaluation reads, a labelling endpoint, and
`POST /system/jev` for the switches, which takes a typed `ENABLE JEV` and writes
an audit entry. Pages under a "Jev" group — status, answers, the labelling
queue, signals — plus a programme catalogue page and a shared answer component.
Existing pages gain a "suggested reviewer … Jev (automated, cannot block)"
column on findings, triage chips on jobs, the Jev choice with its probabilities
on deployments, and on candidates, backtests and the metrics panel the
contaminated badge, the live fraction, the signal model and the threshold.

## Delivery

Each phase lands as its own pull request, with CI green.

| Phase | Contents | Status |
|---|---|---|
| A. Safety fixes | No Jev code. The defects in fact 10, the boundaries, and this document | **Done** |
| B. Foundations, dark | Migration 0012; the pure modules; the switches and the secret name; `jev_client` and `jev_lane` behind the switches; the programme's job loop; the lock file and the SDK CI job | Not started |
| C. Research lane | Web ingest, the injection screen, catalogue labels, hypothesis categorisation, guardrails; the evaluation harness (`python -m src.programme.jev_eval`, never `src/cli.py`). **The forward clock starts:** `decision.regime_v1` is collected, recorded and not consumed | Not started |
| D. Ops triage and findings routing | Triage chips for job errors, reconciliation discrepancies and data-quality alerts; suggested reviewer, duplicate and severity for findings, which needs the panel to sit (phase A) | Not started |
| E. Web UI | For everything above | Not started |
| F. Signals in the engine | The signals channel, the loader at every `Driver` site, parity with signals; provenance columns and the contaminated-evidence refusals; the Rule 5 amendment and its CLAUDE.md changes | Not started |
| G. Shadow | A `jev_regime_allocator` candidate and its baseline twin, in shadow | Not started |
| H. Paper direct decisions | A `forward_experiment` deployment on a second Alpaca paper account; the broker for a non-default owner hard-coded to paper; marks and reconciliation per owner | Not started |

### Phase A, as built

**The specialist panel sits.** `tick._convene` bound the stage's roles to a
local named `panel` and then called `panel.assess` on it — on the tuple, because
`src.programme.panel` had never been imported. Every call raised
`AttributeError`, the per-role `except` recorded `assessment_failed`, and the
gate went on promoting as though the panel had sat. Wherever a key and model
settings existed, no role ever reviewed a candidate and the veto could not
fire. Ruff saw a bound
local; no type checker runs in CI; no test drove `_convene` with a key. The
module is now imported as `specialist_panel` and the local is `stage_roles`.
`tests/unit/test_programme_convene.py` asserts every role is asked and recorded
and a veto role's critical finding is opened as blocking;
`tests/integration/test_programme.py::TestThePanelSitsBeforeThePromotion` proves
on real Postgres that a veto raised in a pass blocks that same pass.

**Enabling asks the gate.** `POST /deployments/{id}/enable` used to flip the
status and check nothing, while `create` — which only writes a disabled row —
held the whole gate. The programme inserts its shadow deployments directly, any
row can be written by hand, and evidence can change after creation. The
create-time checks are now one function, `_deployment_gate`, asked by both
endpoints; for `enable` it is asked of the row as stored. It also refuses a
NULL approved backtest (reachable only from a row) and any mode other than
`paper` without `LIVE_TRADING_ENABLED`, so an unanticipated mode fails closed.
Before the gate, `enable` refuses with **409** any owner but `default`: the
programme's shadow deployments stay disabled, because shadow mode reaches no
venue. `tests/integration/test_deployment_enable_gate.py` covers each refusal
and asserts the row is still disabled after it.

**The worker claims only what it can run.** The queue is shared with the
programme, which will own kinds the worker has no handler for. A worker claiming
every row would take those, fail them with `retry=False`, and retire another
process's work for good. `_drain` now passes `kinds=list(HANDLERS)`, read at
claim time so the filter and the dispatch table cannot disagree.
`tests/unit/test_worker_claim.py` pins the argument;
`tests/integration/test_scheduling.py::TestTheWorkerClaimsOnlyWhatItCanRun`
leaves a stand-in `jev_pass` job queued with its attempts untouched.

**The import boundary refuses Jev before it arrives.**
`tests/unit/test_import_boundaries.py` was rewritten around one scanner and one
import graph of `src/`. The scanner reads `from a import b` as `a` and `a.b` —
the old check compared the module alone, so `from src.programme import tick`
went straight through it — reads `import a, b` as two imports, resolves relative
imports, and finds imports inside functions. A loader called directly with
literal arguments is read as the import it performs: `import_module("x")`,
`__import__` with its fromlist, `pkgutil.resolve_name`, `pydoc.locate`, and
uvicorn's `import_from_string` (uvicorn is installed in the API and the
worker). A star import is read through the package's literal `__all__`. The
loaders it knows are refused wherever they cannot be read: a computed name or
fromlist, a loader aliased or stored rather than called, `getattr` on a loader
module, `runpy` and the spec and path loaders, `exec`, `eval` and `compile`,
and a star import through an `__all__` that is not a literal. That reads
spellings; it is not a sandbox. A loader it does not know — a third-party
helper, `mock.patch` with a dotted target, unpickling — still loads by a name
it never sees, and a reviewer is the control for those.

The graph follows package `__init__` files and walks the modules outside `src/`
that run as a protected process: `api/index.py` and the two scripts that build
the API in-process as part of `api`; `tests/e2e/broker_check.py`, which drives
the Alpaca adapter with the broker keys, and `src/db/migrate_cli.py` as part of
the worker. That list is read back off the workflows rather than trusted:
`test_every_credentialed_workflow_command_is_walked` requires every `python`
command in a workflow holding a venue key or the production database to be
walked, the programme's own excepted because the reverse boundary binds it.
`broker_check` was once missing, and an `import anthropic` in it passed every
test. Every closure check now walks from every protected package. The
forbidden names are matched on whole dotted segments, and gain the TypeSafe
names and the other model SDKs; `RUNNER_ONLY` gains `panel`, `jev_client` and
`jev_lane`; the decision path and the worker may load nothing from
`src/programme`; and the no-tools rule applies to every module that imports an
SDK, so `jev_client.py` is covered the day it is written.

An import is not the only route to a model. `aiohttp` reaches any vendor given
a URL, and the API holds `SECRETS_KEY`, which decrypts the stored model key.
So the TypeSafe endpoint may be spelled only in the two Jev modules, across
`src/`, `web/src/`, `api/`, `scripts/` and every entry point, and
`test_nothing_that_can_move_money_names_a_model_vendor_host` refuses the API
hosts of the model vendors and routers in any module a protected process
loads, in any other file in a protected package, and anywhere in `web/src`.
The hosts are a list, matched as substrings: the scan closes the likely
spellings, not every one. Every scanner is tested against synthetic sources that
must trip it before it is trusted with the real tree.

**A model SDK is installed only where it may be imported.**
`tests/unit/test_dependency_boundaries.py` is new. It reads requirements as pip
does — includes followed, names normalised — and reads `pip install` lines out
of the Dockerfiles and workflows. A model SDK may be declared only in
`requirements-programme.txt` (`pyproject.toml` included in the check, since
Vercel installs from it), installed only by `Dockerfile.programme`, built only
by the `programme` compose service and installed only by `programme.yml`:
`worker.yml` is not a test harness but the worker itself, holding the broker
keys. The only TypeSafe distribution permitted is exactly `typesafe-sdk`, in
the programme file, from PyPI; `cooksafe`, TypeSafe's own cookbook helper, is
refused with the rest, because the programme may hold the SDK and nothing
beside it. `httpx2`, the SDK's transport, is not a model SDK: it is a general
HTTP client, starlette's TestClient already asks for it, and
`test_test_tooling_may_install_httpx2` keeps that migration open. Nothing may
change where pip or uv fetch from, in any spelling. No npm package, in a
manifest or a lockfile, may present itself as TypeSafe's, the official
`@typesafe-ai/sdk` included, because the frontend holds no model client. None
of the eight lookalike hosts in fact 9 is named, as a host or a subdomain of
one, in `src/`, `web/src/` or the files that install, build and deploy them.
The scan once read three of the eight while this document claimed all of them;
`test_every_host_the_doc_names_is_scanned` now holds the list to fact 9.

**Neither the worker nor the programme holds both a venue key and a model
key.** Compose hands `.env` to a service in one of two ways: `${NAME}`
interpolation passes one value, and `env_file: .env` passes the whole file.
Only the API, the worker and the programme load the whole file, so which of
them holds which key is decided by blanking. The worker now also blanks
`TYPESAFE_API_KEY`; the API blanks both model keys; and the programme blanks
`ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` and `BANKR_API_KEY`, because a venue key
needs no import to use. The database loaded the whole file as well, blanked
nothing and was missing from the compose header's table, so the postgres server
held both venue keys, both model keys and `SECRETS_KEY` at once. It is now
passed `POSTGRES_USER`, `POSTGRES_DB` and `POSTGRES_PASSWORD` by name and
nothing else, and `web` loads no key file.
`tests/unit/test_secret_isolation.py` asserts both directions against compose
and the workflows. It requires a blank to be `""` (a bare `NAME:` passes the
shell's value through), derives the broker key names from `src/config.py` rather
than trusting a list, refuses a model-key read from the environment outside
`src/programme`, and refuses `JEV_API_KEY` in any product file.
`TestEveryComposeServiceIsAccountedFor` reads the services from the file
rather than naming three, allows the shared file to those three alone, refuses
any key's name in another service, and renders the file through
`docker compose config` with a sentinel for every key to check what each
container actually receives; that last test is skipped where compose is not
installed. The API is the exception the heading leaves out: it holds the broker
keys beside `SECRETS_KEY` (open item 6).

**A panel that did not finish holds the promotion.** Once the panel could
sit, one role could still fail inside the per-role `except` and the pass promote
as if it had been heard. `_convene` returns the roles that were due and did not
report; `_advance` withholds the promotion, naming them, and only they are asked
again next pass. The hold outlasts the key: a panel that has heard some of its
roles and then loses its key or its model settings keeps holding until both are
back, or until an operator confirms the promotion, which re-evaluates the gate
but does not ask whether the panel finished. Only a stage with no view on
record reads as a panel never convened, and that holds nothing (open item 13).

A role's view and its findings are one write. Written separately, a failure
between them — a clash on `findings.ref` when two runners overlap, a dropped
connection — left the role on record as heard and its objection nowhere, and
the next pass promoted past a veto that had been raised and lost.
`tick._record_view` writes both in one transaction, a savepoint inside a
caller's. A write that fails is caught per role, noted as
`assessment_unrecorded`, and holds the promotion like any other unheard role.
`tests/unit/test_programme_convene.py::TestAViewAndItsFindingsAreOneWrite`
drives the two passes, and
`tests/integration/test_programme_panel_atomicity.py` forces the clash on real
Postgres, on its own connection and inside a caller's transaction.

**The worker trades only the operator's rows.** `_enabled_deployments` and the
maintenance jobs' selection require `owner_id = 'default'` as well as
`status = 'enabled'`, so the enable route is the first refusal of a programme
row and not the only one.

Phase A added no dependency, no migration, no switch and no Jev module.

### Open items Phase A found

Recorded so each is decided rather than lost. Three were fixed within Phase A;
the rest are outside its scope.

1. ~~**A panel that errors does not block a promotion.**~~ *Resolved in
   Phase A.* `_convene` now returns the roles that were due and did not report,
   and `_advance` withholds the promotion until they have, with a key or
   without one. A stage with no view on record and no key or usable settings
   still holds nothing, as the module intends; item 13 is the one case that
   rule misreads. `test_programme_convene.py::TestAPanelThatDidNotFinishHoldsThePromotion`.
2. ~~**The worker trusts status alone.**~~ *Resolved in Phase A.*
   `live_job._enabled_deployments` and `maintenance_jobs._enabled_deployment_rows`
   also require `owner_id = 'default'`, so a programme row enabled by any path
   reaches no venue. Phase H has to widen both, deliberately, for its own owner
   and its own account.
   `test_deployment_enable_gate.py::TestTheWorkerTradesOnlyTheOperatorsRows`.
3. **`deployments.approved_backtest_run_id` is nullable**, though the schema
   comment says the gate "lives in the schema". (The docstring in
   `src/programme/repo.py` that said the column is required has been
   corrected.) The enable gate now refuses NULL; NOT NULL needs a new
   migration.
4. **The gate checks the approved backtest's strategy, not its parameters,**
   while the walk-forward is matched on parameters. This predates Phase A.
5. **The gate and the `UPDATE` in `enable` are not one transaction,** so the
   evidence could change between the check and the switch. The window is small.
6. **The API holds the broker keys beside `SECRETS_KEY`,** the venue-plus-vault
   combination the workflow rule forbids, because `/system/status` reports
   `broker_configured` from them. `SECRETS_KEY` decrypts the stored model key,
   so the API is the one process that can hold a venue key and a model key
   together. Having the worker report it — on its heartbeat, say — would let
   the API blank the pair and the no-both rule extend to compose.
7. **`live_job` calls `broker.submit(intent, client_order_id=coid)`,** which only
   `AlpacaBroker` accepts; the `BrokerAdapter` protocol and `SimulatedBroker` do
   not. It works in production, and a test that injected a `SimulatedBroker`
   there would raise `TypeError`. Not confirmed as a live bug.
8. **No type checker runs in CI.** One would have caught the panel defect.
9. **Leases.** `job_repo.requeue_expired` applies to every kind, so phase B's
   long programme jobs must extend their leases.
10. **When the key lands in phase B,** `TYPESAFE_API_KEY` needs adding to
    `.env.example`, to `test_env_example_is_complete.py`'s no-value check, and to
    `KNOWN_SECRETS`.
11. ~~**Safety rule 5's text** named the runner as `tick`, `author`, `client`
    and `main` only.~~ *Resolved:* it now lists `panel`, `jev_client` and
    `jev_lane` as `RUNNER_ONLY` does. The rule's substance changes in phase F,
    with the amendment.
12. **The compose stack connects to its database as a superuser.** The
    API, the worker and the programme connect as `trader`, which the postgres
    image creates as a superuser, and a superuser's `COPY ... FROM PROGRAM`
    runs a shell command in the database container, under its environment.
    While that container loaded the whole `.env`, a key the worker or the
    programme blanks was one SQL statement away. It now holds only the
    `POSTGRES_*` variables, whose password the caller already has, so the
    route reaches no key; but the route is open, and anything later added to
    that container's environment is on it. Connecting as a role without
    superuser closes it, and touches the migrations and the deployment.
    Production is not on this route: it connects through `DATABASE_URL` to
    Neon, which grants no role superuser.
13. **A panel in which every role failed reads as never convened once the key
    is gone.** The hold rests on `role_assessments`, and a pass in which every
    role's call or write failed leaves no row there, only `assessment_failed`
    or `assessment_unrecorded` in the run's actions. If the key or the model
    settings then go away, the stage reads as never convened, and the next pass
    may promote. Holding on the run's actions would make the runner depend on
    whether an earlier pass finished writing its report; a row recording that
    the panel was summoned needs a migration.

## Inputs needed from the operator

Inputs, not approvals.

1. **A TypeSafe API key** from an existing `console.typesafe.ai` account, since
   new signups are paused. Once phase B adds it to the vault, it is set on
   System > Configuration; for the scheduled programme it can also be the
   `TYPESAFE_API_KEY` repository secret. Until it exists, phases A to G are built
   and tested against fakes, and no live call is made.
2. **A replacement Alpaca paper key** for the revoked one.
3. **For phase H, a second Alpaca paper account's key**: a `PK` key, checked
   against both endpoints before it is stored, as CLAUDE.md requires of any
   Alpaca key.

Defaults applied unless the operator says otherwise:

- Public web content and code-computed features are sent to TypeSafe.
- Hypothesis cards and findings are sent as titles only. Their detail is sent
  only if `jev_send_internal_detail`, which starts off, is switched on.
- No model is ever trained on Jev's output.
- The model is pinned to `jev-1.13.0`, and every Jev switch starts off.

## Verification

| When | Check |
|---|---|
| Every phase | `pytest tests/unit -q`; `pytest tests/unit/test_parity.py -q`; `ruff check src/ tests/`; the integration suite on real Postgres in CI; from phase B, the SDK job |
| Once a key exists | A probe run; `jev_eval` on the held-out set and on the 61-strategy set, labelled an upper bound; the forward clock checked daily; the new pages checked on the deployed app with the live smoke |
