# The Jev integration

Specification and record of wiring TypeSafe AI's Jev into the AI programme.
Owner: Quentin Casares. Phases A and B of eight are built, and phase C is
under way: C1+C2 hardened the one road every lane takes, W gave the worker the
forward clock's reference bars, and C4 starts the forward clock — a planner,
the `jev_regime` job, a daily connectivity probe, flip re-asks, the
pre-registered analysis plan and a read-only harness. D to H are not built.
The code is dark: every Jev switch is seeded off, no lane is wired into the
programme's tick, and the planner, the only producer of a job that can make a
call, plans nothing until an operator switches the programme and Jev on.
A TypeSafe key exists, as the `TYPESAFE_API_KEY` repository secret set on 26
September 2026, and the dispatch-only key check proved it against TypeSafe's
own host the same day: the listing named the aliases only, and the pinned
`jev-1.13.0` answered the connectivity probe as expected. The programme itself
has made no call. Last revised 27 September 2026.

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

Phase A contains no Jev at all. It fixes the defects in this repository that
the research found would have undermined the integration, and draws the
boundaries before the code they bound exists. Phase B builds everything needed
to make one recorded, validated call — the ledger, the pure modules, the
client, the lane and the programme's job loop — and switches none of it on.

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
| Honours `TYPESAFE_BASE_URL` with no scheme or host check | One environment variable sends the key and every request anywhere | `base_url=JEV_BASE_URL`, passed explicitly from `jev_catalogue.py`, and redirects refused by the HTTP client `jev_client.py` builds for the SDK |
| Defaults to the alias `jev-latest`, or to `TYPESAFE_DEFAULT_MODEL` | The answers behind an alias change without a change here | `model=` passed explicitly; the catalogue refuses aliases; `response.model` must equal the pin |
| At DEBUG, logs full request and response bodies unredacted. `TYPESAFE_LOG_LEVEL` is read once, at import | Everything sent to TypeSafe lands in the logs | `TYPESAFE_LOG_LEVEL=off` before import, then the `typesafe_sdk` logger forced above CRITICAL and given a filter that drops every record, both re-applied on every call |
| `extra_body` is merged last and shallowly | It can silently replace `state`, `model` or `questions` | Never used, nor `extra_headers` or `response_model` |
| The default policy makes three attempts, retries a non-idempotent POST with no idempotency key, and honours `Retry-After` uncapped | Whether a retried call is billed is undocumented, and a server can stall a pass | `RetryPolicy(max_retries=1, timeout=20, respect_retry_after=False)`, retrying only 429, 500, 502, 503, 504 and 529, a failed connection and a timeout, and a 10 s per-request timeout |

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

So `jev_validate.py` parses the raw body itself, as strict JSON: `NaN`,
`Infinity` and a name given twice in one object are refused, though Python's
own parser reads all three. A body that is not an object with an `answers`
object, names a model other than the pin, or answers none of the questions
asked is refused whole, as `invalid`, and may be asked again. Otherwise each
question asked is judged on its own answer: one with no answer is `missing`,
and an answer to a question nobody asked is ignored and noted. Each answer's
type must match; probability keys must equal the criteria, values must lie in
[0, 1] and sum to 1 ± 0.02, compared as the decimals written; Score keys must
be `"0"` to `"n-1"`; `true` is not a number; and the argmax is recomputed, a tie
or a mismatch counting as an abstention. **An invalid answer is stored with its
reason and consumed as not measured, never as 0.** A response sound as a whole
that gets one answer wrong is `ok`, with that answer invalid: it is what the
pinned model said, it is recorded once, and asking again would not check it.

### 4. Errors, retries and request ids

| Condition | Status | Python SDK class | Handling here |
|---|---|---|---|
| No key sent | **403** (the docs say 401) | `TypeSafePermissionDeniedError` | Authentication failure: every lane is held until 00:00 UTC, the connectivity probe's included, and a key replaced before then is held with it: only the dispatch-only key check can prove the new one sooner |
| Invalid key | 401 | `TypeSafeAuthenticationError` | The same |
| Request failed validation | 422 | `TypeSafeUnprocessableEntityError` | That question set's version is held, under the pin, until a new version |
| Rate limited | 429 | `TypeSafeRateLimitError`, with `.retry_after_ms` | Transient |
| Overloaded, or any server error | 529, or any 5xx | `TypeSafeInternalServerError` | Transient |
| Another 4xx, 408 for instance | | `TypeSafeAPIError` | Recorded by class |
| No HTTP response | | `TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError` | Transient. **No request id exists** |
| Malformed 200 | | `TypeSafeAPIResponseValidationError` | Judged by the validator from the raw body, like any 2xx; the SDK's objection is kept beside the verdict |
| A 403 whose body is not JSON | 403 | `TypeSafePermissionDeniedError` | For text — a web excerpt, a hypothesis title — the state is not sent again, and the document it came from is quarantined, as a possible content block. A precaution: it rests on one unverified third-party report, and the verification found no primary evidence for it. An enumerated state is not held: it is labels computed in code, nothing a filter could object to, so an edge's 403 page is the likelier cause, and holding it for good would take it out of the forward clock |

As built in phase B, the client classes every failure by `error_kind` —
`auth`, `content_block`, `invalid_request`, `rate_limited`, `server`,
`timeout`, `connection`, `response_shape` or `client` — and the lane records it
on the request's row. There is one retry, for 429, 500, 502, 503, 504 and 529
and for no response at all; 501 is `server` and not retried, since it will say
the same thing again, and 408, a redirect and every other status the table
does not name are `client`, recorded by class. The actions in the last column
beyond recording were left to phase C, and its first pull request built them
into the road, derived from the rows these failures leave rather than from a
switch anybody writes: an authentication failure holds every lane, not only
the one that met it, until 00:00 UTC (`auth_held`) — the ledger records no
trace of which key failed, so a key replaced after it is held too, and until
midnight only the operator's dispatch-only `jev_check` can prove it (open item
37); a 422 holds the question set's version under the pinned model until a new
version changes its words (`set_refused`); and a 403 whose body is not JSON
holds exactly the text it answered, in every set and every ask, a probe's
included, and before any replay (`content_blocked`). Text only: a web excerpt
or a hypothesis title, the states a content filter could object to. An
enumerated state is held by nothing — its 403 is recorded, and it is asked
again — since holding one for good would take it out of the forward clock on
the strength of a page an edge more likely served (open item 36). Quarantining
the document that text came from arrives with web ingest.

The request id comes from the `x-typesafe-request-id` response header. Among
the SDK's errors only `TypeSafeAPIError` and its subclasses carry
`.request_id`, and theirs is None when the header is absent. So a NULL
`vendor_request_id` means only that no request id came back: either there was
no HTTP response, or there was one without the header, which the non-JSON 403
in the table above plausibly would be. The HTTP status is stored beside it,
NULL only when there was no response, and that is what tells the two apart.

Rate limits are 250,000 tokens a second and 1,200 requests a minute, which the
docs say "can change without notice". A client-side sliding window, at 1,000
requests a minute and 200,000 estimated tokens a second, keeps under both. It
admits every attempt, a retry included, because the vendor counts requests
rather than calls.

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

## Architecture

Phase B built the programme's half of this, dark: the ledger, the pure
modules, `jev_client`, `jev_lane` and the programme's job loop. Phase C6
built `web_ingest.py`, which stores what it reads and asks nothing; the arrow
from it to the lane below is C7's `jev_ask` jobs, which ask the injection
screen, and then the catalogue, about the excerpts it stored, as C8's ask the
title sets about the programme's hypotheses. The signal loader and everything
on the engine's side are what the later phases build. Every switch named here
reads as off when it cannot be read.

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
| `jev_catalogue.py` | Pure, and importable by the API. `JEV_BASE_URL`; `KNOWN_MODELS`, the pinned IDs this repository has chosen to call, today `jev-1.13.0` alone, each matching `^jev-\d+\.\d+\.\d+\Z` under `re.ASCII` (with `$`, `"jev-1.13.0\n"` would pass); the refused aliases `jev-latest`, `jev-preview`, `jev` and `jev-1.13`, by name in any case or spacing; the size limits, 56k tokens in total and 28k for state plus the longest question, on an estimate of one token per three ASCII bytes and one per byte of anything else, the byte-level worst case, since the vendor's tokenizer is undisclosed; the client's rate ceilings; the lane, provenance, subject-type and area vocabularies and `LANE_AREA`; `LANE_BUDGET_PERCENT`, each recorded lane's share of the daily budget, in code so that no database write can raise one (phase C); and one `settings_problem()` shared by the form and the runner, which caps the daily budget at 10,000 |
| `jev_questions.py` | Pure. Versioned question sets: name, version, lane, provenance, questions as ordered pairs, a `state_model` (pydantic, `extra='forbid'`, frozen, strict) and a purpose. Each has a golden hash. Every Choice has exactly one escape option, last, and a frozen option order. Phase B registers `probe.connectivity` v1 and `decision.regime` v1. Phase C adds `WebExcerptState`, the one state web text is asked about in, of 1 to 300 characters; each state model's subject type, and for text who writes it (`TEXT_SUBJECT_PROVENANCE`); the injection screen's name, its one question and clear answer (`screen_problem`); and `registration_problem`, which holds a set to the sets already registered and to the rules the lane relies on. A set's state is read twice for this system's own detail: from its model at registration, failing closed, and from what `dump_state` would send. A Score question registers with at most four levels. C7+C8 register `guardrail.injection`, `research.catalogue`, `research.hypothesis` and `guardrail.card`, v1 each, and `HypothesisTitleState`, a title of 1 to `TITLE_MAX_CHARS` (300) characters |
| `jev_validate.py` | Pure, and never raises. The response rules in fact 3, and from phase C a Score's legend and its agreement with its own probabilities |
| `jev_hash.py` | Pure; importable by the programme, the API and the harness, and, like every module here, never by the worker or the decision path. A request's identity: `state_hash`, `request_hash`, `questions_hash` — the part of the request hash a set contributes — and `text_sha256`, a text subject's content address. Moved out of `jev_lane` in phase C, which re-exports the first two, so the API and the harness can compute one without loading the client |
| `jev_features.py` | Pure. `regime_state` turns a `PricePanel` into enumerated descriptors of three sleeves, computed in code from `adj_close` — trend relative to the 200-session average, a volatility quintile, a drawdown bucket, the direction of 63-session momentum — or `None` when the data cannot support them. The decision lane's only state. From C4, `regime_state_problem` says why it would be `None`, for a job's error |
| `jev_repo.py` | Queries for the Jev tables. No SDK, so the API can import it. A request and its answers are one write. From phase C, the road's reads: the calls a lane made today, whether the vendor refused a key today, a set's version or a state, whether content is quarantined, and whether the injection screen cleared a text; from C4, the clock's, the planner's and the harness's: whether a session has a signal, a series' signals with their answers, the canonical requests of a day, each canonical answer beside its re-asks, the probe's series, and the jobs behind a list of keys. Inside the programme it is the one reader of `jev_signals`. From C6, the one writer of `web_documents`: `insert_documents`, `ON CONFLICT DO NOTHING`, `title` and `published_at` NULL by the statement, and `quarantine_content`, the one update the table allows, by content and one-way; with `get_document` and `earliest_quarantined`. From C7+C8, the one writer of `jev_labels` (`record_label`, and `record_label_once` for a source's headings), what each set is to be asked about (`documents_to_screen`, `documents_to_describe`, `hypotheses_to_ask`), the `jev_ask` jobs waiting, the earliest content block on record for a subject, and `ask_job_key` |
| `jev_clock.py` | C4. Holds no client and is not runner-only, so phase E may read the cutoff. The forward clock's times — the reference bars at a session's close plus 45 minutes (the worker's ingest time), the collection at plus 50, the cutoff at plus 60 (the worker's decision time) — the sessions the planner plans, the signal's and the jobs' names, `sleeve_symbol`, and the bar loader, which reads `adj_close` from `yfinance` alone |
| `jev_forward.py` | C4, runner-only. `collect`, the `jev_regime` job: one session's regime, asked before the cutoff by the database's clock, at most one call an attempt — an attempt whose call got no response is retried and asks again — and one answer recorded at most once; never a backfill and never a `missing` row |
| `jev_jobs.py` | C4, runner-only. `run_reask`, the `jev_reask` job; from C7+C8, `run_ask`, the `jev_ask` job — one registered set asked about one stored text, a web excerpt read through the code screen or a model-written title within its cap — and what an answer changes (`ASKABLE`), a quarantine and nothing else. Re-exports `ask_verdict` |
| `jev_plan.py` | C4, runner-only. The planner: the daily probe, the worker's reference bars, the regime job and the re-asks, each behind its switches, enqueued with literal kinds and nothing else; from C6, the web ingest, once a UTC day for each allowed source, behind the research area; from C7+C8, the `jev_ask` jobs, each set behind its lane's area |
| `jev_prereg.py` | C4. Pure, the standard library alone, importable by the API. The analysis plan and `REGIME_BASELINE_RULE`, registered before any answer and golden-hashed, with an append-only release history kept in its test; from C7+C8, a plan for each set asked about text, with its keyword baseline, recorded with every answer (`plans_in_force`) |
| `jev_stats.py` | C4. Pure. `proportion` and `wilson`; a figure over nothing is `None`. C9 adds the rest |
| `jev_eval.py` | C4, runner-only CLI. `python -m src.programme.jev_eval status`, `forward` and `forward-audit`: read-only, `DATABASE_URL` and nothing else, no key, and a closure that reaches no client |
| `job_errors.py` | C4. Pure. `JobFailedError`, moved out of `main.py`, which re-exports it, and `RETRIED_ERROR_KINDS`; from C7+C8, `ask_verdict` and `NOT_ASKED`, moved out of `jev_jobs`, and `described`, an error by its class, SQLSTATE and constraint, moved out of `web_ingest` |
| `claims.py` | C8. Pure, the standard library alone. The performance-claim check — `PERFORMANCE_TERMS`, `find_performance_claim`, `NUMERIC_BY_DESIGN`, `reject_performance_claims`, `PerformanceClaimError` — moved verbatim out of `author.py`, which re-exports every name and screens a hypothesis's title with it too |
| `jev_client.py` | The only importer of `typesafe_sdk`, lazily, runner-only. Builds the SDK's `httpx2` client itself — redirects refused, every attempt admitted by a sliding-window rate limiter, the final attempt's response kept as it arrived — and constructs `AsyncTypeSafeClient(api_key=…, base_url=JEV_BASE_URL, model=<pin>, retry=RetryPolicy(max_retries=1, timeout=20, respect_retry_after=False, http_statuses={429, 500, 502, 503, 504, 529}), timeout=10, http_client=…)`, with the key the programme resolved from the vault, then the environment. Returns a `JevCall`: status, raw body, request id, latency, error class and kind |
| `jev_check.py` | Runner-only. `python -m src.programme.jev_check`: whether a key works, asked of TypeSafe's own host. Lists the models the key may use with `jev_client.list_models` (no tokens), which settles that TypeSafe's host accepts the key and not the pin: the listing names the aliases only, and a versioned id is accepted unlisted. It stops if the key is refused, then asks the connectivity probe once through `jev_client.ask`, whose answer proves the pin, and judges any 2xx body with `jev_validate` exactly as the lane does, against `PROBE_EXPECTED`. Records nothing and prints no secret, withholding any run of the key a vendor might echo; exit 0 pass, 1 fail, 2 no key, 3 no verdict — a network failure, a rate limit or a vendor fault, which says nothing about the key. `jev-check.yml` runs it by dispatch with the `TYPESAFE_API_KEY` repository secret and nothing else |
| `jev_lane.py` | Runner-only. One ask of one question set: check the arguments and the subject, the switches, the pin, the web gate and the content block, hash, look up, and unless the answer is on record, the key, the vendor's standing refusals, the budget and the lane's slice of it, and the size; then call once, validate, write. `run_probe` is the `jev_probe` job's handler. Building each lane's state from its sources, and routing its answers, arrive with the lanes from phase C. It reaches none of `client.py`, `author.py`, `panel.py` or `tick.py`, so on the signal path the cascade ends at Jev |
| `web_sources.py` | Phase C5. Pure, and importable by the API. The allow-list, one page written out in full, checked when the module loads and recorded as written; the README parser, which keeps titles and refuses a page that has changed shape, a line it cannot read among them; the excerpt normaliser, idempotent; the code screen, version 1, its rules and readings data and its hash pinned beside them and in a released history; `screen_cell`, what becomes of a row; the labeller a source's grouping is recorded as |
| `web_fetch.py` | Phase C5. Runner-only, and the only module in `src/programme` that imports `aiohttp`. Fetches an allow-list entry, by identity and as written, once: no redirects, no environment, global addresses only, verified TLS, fixed headers, a size cap as declared, received and inflated, strict type and UTF-8, 200 only, one attempt. Imported by `web_ingest` alone |
| `web_ingest.py` | Phase C6, runner-only, and the one importer of `web_fetch`. The `jev_web_ingest` job: re-read the programme's switch, the research area and the pin, and run only while a key is set (read in `main`'s wrapper for that and nothing else), fetch the allow-listed page outside any transaction, parse it with the source's parser, store what `web_sources.screen_cell` decides for each row in one transaction through `jev_repo`, its locks taken in content order, quarantine by content, and call nothing; no key reaches it. Its result is counts and hashes. From C7, it records the README's own headings as labels of the catalogue's asset class. The SEC EDGAR feed the plan also named is not planned for phase C |

### Outside `src/programme/`

- `src/db/repos/signals.py` is the **only** reader of `jev_signals` outside the
  programme. Its filter is fixed: `lane='decision' AND provenance='internal' AND
  status='measured' AND available_at <= decision_cutoff(session)`, the cutoff
  computed from the calendar rather than read from the row, plus a fail-closed
  area switch.
- `src/core/panel.py` gains an optional signals channel, sliced as of the
  session like the prices. `src/strategies/base.py` gains
  `required_signals: ClassVar = ()`.
- One loader is called at every site that constructs a `Driver` —
  `backtest_job`, `walkforward_job`, `live_job` (the decision and `dry_run`),
  `shadow_job`, `src/api/drain.py` and `src/cli.py` — and a test proves each
  site uses it.
- The programme's `main.py` runs a Jev loop beside the heartbeat, built in
  phase B. It claims only the kinds in `JEV_HANDLERS` — `jev_probe`, from C4
  `jev_regime` and `jev_reask`, and from C6 `jev_web_ingest`, which calls
  nothing — and only while `programme_enabled` and
  `jev_enabled` are both on, and it extends a running job's lease every 60
  seconds. From C4 it runs the planner before each drain, at most once a
  minute, in a `try` of its own. The worker already claims only its own kinds
  (Phase A), so the two dispatch tables are disjoint, one per process, and
  every kind has exactly one owner.

### Keys and dependencies

All of this was built in phase B.

- `typesafe_api_key` is in `KNOWN_SECRETS` and on the configuration form,
  whose note warns against pasting a key anywhere but `console.typesafe.ai`
  without naming any other site. The programme resolves it for each job, vault
  then environment, and it reaches the SDK only as `api_key=`.
  `TYPESAFE_API_KEY` is in `.env.example` with no value, and `programme.yml`
  passes the repository secret of that name.
- `JEV_API_KEY`, the reseller's variable name, is never used.
- `requirements-programme.txt` declares `typesafe-sdk==0.7.1`;
  `pydantic>=2.12.0`, the SDK's floor (`requirements.txt` says `>=2.7.0`); and
  `httpx2>=2.0.0`, because `jev_client` imports it by name. The hash-locked
  `requirements-programme.lock` pins the whole tree, 64 packages, and
  `Dockerfile.programme`, `programme.yml` and CI install it with
  `--require-hashes --only-binary :all:`: wheels only, because pip does not
  hash-check what it fetches to build an sdist.
- CI's `programme sdk` job runs `pytest tests/sdk -m sdk -q` with no secret, a
  read-only token and a trust-authenticated Postgres service: the client
  against a fake TypeSafe server over real HTTP, and one call end to end into
  the ledger. The main CI job stays SDK-free.

### Schema: migration `0012_jev.sql`

Built in phase B. Every table refuses UPDATE, DELETE and TRUNCATE with an
exception, `web_documents` allowing one change, below.

| Table | Holds |
|---|---|
| `jev_requests` | Every question put to Jev, and every refusal to put one. The request hash (sha256 of the canonical `{model, state, questions}`, state keys sorted, question and option order preserved), the state hash, question set, version and pack hash, lane, provenance, subject, `as_of`, the state and questions sent (`questions` as `json`, since `jsonb` would reorder the options inside the hash); the model requested and the model that answered; the vendor request id (NULL when none came back, whether there was no HTTP response or one without the header), the HTTP status (NULL only when there was no response, which is what tells those apart), `status` of `ok`, `invalid`, `error`, `refused_budget`, `refused_limits` or `refused_model`, the error class and kind, the raw body, tokens and latency; `requested_at`, and `available_at` set by a trigger to `clock_timestamp()`, the moment of the insert. The partial unique index `jev_requests_canonical` on the request hash where the status is `ok` and the lane is not the probe lane, and CHECKs holding the rest of the row to its status |
| `jev_answers` | One row per question asked, valid or not: `noul`, `choice`, `score`, `probabilities`, `confidence` (NULL for a Noul), our own argmax and margin, `valid` and `invalid_reason`. A valid row carries its value, argmax and margin and no reason, and a valid Choice is its own argmax |
| `web_documents` | Snapshots, one per source and content hash. The one change allowed is `quarantined` from false to true, with a reason, the rest of the row unchanged |
| `jev_signals` | Frozen. Keyed `(signal, symbol, session)`, with status, the answer, lane, provenance, pack hash, model, the decision cutoff, `available_at`, and a generated `backfilled` column: liveness is derived from the database's stamp and a cutoff held to the session's own day in New York, so no writer sets it and none can move the cutoff off that day. `measured` and a value go together, both ways. A trigger holds the lane, provenance and pack to the request the signal's answer came from, and a `measured` signal to a valid answer to a canonical request from the model it names; an answer not yet visible to the inserting transaction is refused there rather than left to the foreign key, which checks later with a newer snapshot |
| `jev_labels` | `labelled_by` is `operator:<name>` or `source:<dataset>@<sha>`, neither part empty; one label per labeller per item |
| `jev_evaluations` | Per question set, question and model: the dataset and its hash; n and n per class; accuracy with Wilson bounds; Brier score with a bootstrap interval; calibration bins; the threshold and its coverage; baseline accuracy; flip rate; `possibly_in_training`, which must be stated; the code commit. Every measurement is nullable, NULL meaning not measured |

Changes to existing tables: `candidates.evidence_uses_model_signals`, which a
trigger refuses to clear once set; signal-provenance columns on
`backtest_runs` and `walkforward_runs` (counts of live, post-release backfill
and pre-release backfill, the model IDs served, the pack hashes), all NULL,
meaning the run used no model signal, or all set, and to be computed from the
rows actually served once phase F serves any; and `deployments.evidence_class`,
`'walkforward'` or `'forward_experiment'`, with the CHECK
`deployments_forward_experiment_is_paper`: `forward_experiment` implies
`mode='paper'` and an owner other than `default`, so only a new migration can
relax it.

A data-only logical restore fires the `available_at` stamp and rewrites every
row's to the moment of the restore. Restore data with `--disable-triggers`; a
full restore creates the triggers after loading the rows, and a physical
backup never runs them.

Migration `0013_jev_model_provenance.sql`, phase C's first, is additive. Both
provenance CHECKs gain `model`, text the programme's own generative model
wrote, which is none of the other three: recorded as `internal` it would pass
the one filter the phase F loader is to trust. Each CHECK keeps its name,
because the schema suite reads the vocabulary back by it. Four indexes carry
the road's new reads: `state_hash`, for a content block and a screen's answer;
`(error_kind, available_at)` where `error_kind` is set, for the standing
refusals; `(question_set, question_set_version, subject_type, subject_id)`;
and `web_documents (content_sha256)` where `quarantined`, for the web gate's
quarantine lookup, which the one-snapshot constraint on `(source,
content_sha256)` cannot serve. And a CHECK,
`web_documents_content_is_its_excerpt`, holds a document's `content_sha256` to
the sha256 of its own `excerpt` as UTF-8 — what `jev_hash.text_sha256`
computes — because the gate looks quarantine up by the address of exactly the
text it is about to send, and a writer that hashed anything else would leave a
quarantined document where the gate cannot see it. Added while `web_documents`
is empty everywhere; over a database holding a row it refuses, 0013 fails
whole and leaves it at 0012.

### Switches, all fail closed

Seeded in `system_flags` by migration 0012 and read through `flags.py` with
the same broad `except` as `programme_enabled`: `jev_enabled` false;
`jev_model` `jev-1.13.0`; one area switch each for research, ops, findings,
guardrails, signals and decisions, all false; `jev_daily_request_budget` 500;
`jev_max_state_tokens` 8,000; and `jev_send_internal_detail` false. A missing
row, an unreadable value or a database error reads as off, and a model setting
the catalogue refuses means no call — the same rule `flags.model_settings`
already applies. A switch is on only for a stored JSON `true`, not the string
`"true"` or 1; an area needs the master switch as well as its own; and the two
counts read as 0, which permits no request, on any failure or any value the
catalogue refuses, rather than being clamped. From phase C that includes a
budget of 1 to 9: each lane spends at most its share of the budget, rounded
down, and below 10 the probe lane's would be none while the setting read as one
that permitted calls, so a budget is 0 or at least 10
(`jev_catalogue.MIN_DAILY_REQUEST_BUDGET`, derived from the shares). The programme's Jev loop asks
`programme_enabled` as well as `jev_enabled`: two independent switches, both
required, neither derived from the other. From phase C the road asks them
itself, on every ask, with the area of the set's own lane and, for a set that
carries this system's own detail, `jev_send_internal_detail`, so a caller that
forgot to is held to them anyway.

## Lanes

Planned, except where a row says what is built. Phase B built the one road
every lane takes, `jev_lane.ask`, and registered two question sets: the
connectivity probe, and `decision.regime` v1, which the forward clock asks
from C4. Phase C's first pull request moved every rule a lane could forget
into that road, and C7+C8 registered the research and guardrail sets below,
dark and in shadow. A set's version is a field of its own, pinned with its
golden hash, so the sets below are named without one.

| Lane | Question sets | State | What Jev may do | What it may never do |
|---|---|---|---|---|
| Research | `research.catalogue` (asset class, mechanism), built in C7; `research.hypothesis` (the same two questions about a hypothesis's title), built in C8; `research.news` (relevance, event type, tone), not planned. `guardrail.injection` ("addressed to an AI system"), built in C7, runs first | Allow-listed web excerpts; the programme's model-written hypothesis titles | Today: be recorded and planned on, the catalogue only for text the screen cleared; quarantine what the injection screen flags. Later: label the catalogue page; rank a shortlist `author.py` may use to prioritise | Satisfy any gate criterion |
| Guardrails | `guardrail.card` (a performance claim), built in C8 beside `find_performance_claim`, in shadow; an untestable falsification test, planned | Hypothesis titles; cards as titles unless the detail switch is on | Today: be recorded and change nothing. Later, once calibrated (phase D): a "yes" rejects or raises a finding | Accept anything. A "no" changes nothing, so the accepted set with Jev is a subset of the set without it — a property test |
| Findings routing | Owning role (the twelve plus "unclear"), likely duplicate, suggested severity | Findings, as titles unless the detail switch is on | Suggest | Write `severity` or `status`. Findings it raises carry `raised_by='jev:<set>'`, never in `VETO_ROLES` |
| Ops triage | Job errors, reconciliation discrepancies, data-quality alerts, through a redactor | Free text only; code handles structured cases first | Show chips on System > Jobs | Resume anything, or touch the kill switch |
| Recorded signals | `signal.news_tone` | Web content | Be recorded and scored going forward | Be loaded by the decision path. The loader's filter excludes web provenance by construction |
| Direct decisions | `decision.regime` v1: a Choice over `risk_on`, `neutral`, `risk_off`, `insufficient_evidence` | Only `jev_features` descriptors: internal provenance, which no outsider can write to, so the prompt-injection route recorded as C-1 in `docs/02-security-audit.md` stays closed | Feed `jev_regime_allocator`, a pure strategy with a fixed universe and fixed weight vectors declared in code; the pack hash and threshold are its parameters | Act on a missing, invalid, argmax-mismatched or below-threshold answer: each means **hold** |

A code baseline twin — the same descriptors through a fixed rule — runs beside
the allocator. The rule lives in code, beside the allocator, and never in the
question: `decision.regime`'s options describe the regimes, so the paired
difference compares a judgement with a rule rather than a rule with a noisy
copy of itself. The honest expected edge is zero until forward measurement says
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
| A decision-lane question set takes internal provenance only, and its state is Literal labels, booleans and nested models, with no computed field or serializer | Built, Phase B |
| Nothing in a decision-lane state names a date or a ticker | Review only. The rule reads shapes, not meanings: `spy`, `d20200316` or a date split into small ordinals passes it, and `test_jev_questions.py::TestTheDecisionStateIsEnumerated::test_the_rule_reads_shapes_not_meanings` pins that. A machine control — a golden vocabulary per decision-lane state — is needed before phase F |
| A signal carries the lane, provenance and pack of the request its answer came from, and only a valid answer to a canonical request is `measured` (`jev_signals_rest_on_their_answer`) | Built, Phase B |
| Outside the programme, only `signals.py` may name a Jev table | Built in phase B: `tests/unit/test_jev_table_boundaries.py::test_only_the_signals_reader_names_a_jev_table_outside_the_programme` (no module outside `src/programme` names one until `signals.py` arrives in F) |
| `jev_lane` is the only writer of `jev_signals`; `client.py`, `author.py`, `panel.py` and `tick.py` never name it | Built in phase B: `test_jev_table_boundaries.py::test_only_the_lane_writes_signals` and `::test_the_model_runners_never_name_the_signals` (no writer exists yet; the first arrives in C) |
| `apply_risk` and `weights_to_orders` are called only from `Driver` | Phase F |
| A strategy with `required_signals` is refused `mode='live'` at create, at enable and in `run_live_decision` — a fourth refusal, additive to the three live-money gates | Phase F |
| `signals.py` excludes web-provenance, backfilled and switched-off rows | Phase F |
| Parity holds with signals, including missing, late and below-threshold ones | Phase F |
| The `jev_signals` freeze trigger holds | Built, Phase B |
| `forward_experiment` is paper-only by CHECK constraint | Built, Phase B, as `deployments_forward_experiment_is_paper`, ahead of the phase H it was planned for |

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

Each phase lands with CI green: A and B as one pull request each, and C as the
six below the table, beside a UI pull request that is not phase C's.

| Phase | Contents | Status |
|---|---|---|
| A. Safety fixes | No Jev code. The defects in fact 10, the boundaries, and this document | **Done** |
| B. Foundations, dark | Migration 0012; the pure modules; the switches and the secret name; `jev_client` and `jev_lane` behind the switches; the programme's job loop; the lock file and the SDK CI job | **Done** |
| C. Research lane | Web ingest, the injection screen, catalogue labels, hypothesis categorisation, guardrails; the evaluation harness (`python -m src.programme.jev_eval`, never `src/cli.py`). **The forward clock starts:** `decision.regime` v1 is collected, recorded and not consumed | **In progress**: C1+C2, W, C5, C4, C6 and C7+C8 done |
| D. Ops triage and findings routing | Triage chips for job errors, reconciliation discrepancies and data-quality alerts; suggested reviewer, duplicate and severity for findings, which needs the panel to sit (phase A) | Not started |
| E. Web UI | For everything above | Not started |
| F. Signals in the engine | The signals channel, the loader at every `Driver` site, parity with signals; provenance columns and the contaminated-evidence refusals; the Rule 5 amendment and its CLAUDE.md changes | Not started |
| G. Shadow | A `jev_regime_allocator` candidate and its baseline twin, in shadow | Not started |
| H. Paper direct decisions | A `forward_experiment` deployment on a second Alpaca paper account; the broker for a non-default owner hard-coded to paper; marks and reconciliation per owner | Not started |

Phase C lands as seven pull requests rather than one, each with its own
subsection under "Phase C, as built" and its own CLAUDE.md rows. The design
names nine parts, C1 to C9, and its review grouped them into six; C5, the
one part that reaches the open web, was then built on its own, ahead of the
ingest job that follows the forward clock. The table lists the owner's UI
pull request beside them because it merges first, though it is not phase C.

| Pull request | Contents | Depends on | Status |
|---|---|---|---|
| UI | The owner's design decisions OD-5 to OD-8. Not phase C; merges first | — | Outside phase C |
| C1+C2 | The road hardened: every switch read by the road, subjects that are their content, the web gate, the vendor's standing refusals, per-lane budget slices, open item 15 and provenance `model` (migration 0013); and open item 20, the Score checks and the four-level rule | — | **Done** |
| W | The worker's reference bars (C3), with the live ingest kept on one adjustment basis, reviewed as a live-path change | — | **Done** |
| C4 | The forward clock starts, with the restart schedules moved clear of it | C1+C2, W | **Done** |
| C5 | Web sources (pure: the allow-list, the parser, the normaliser and the code screen) and the fetcher, dark | C1+C2 | **Done** |
| C6 | Web ingest, which calls nothing | C1+C2, C4, C5 | **Done** |
| C7+C8 | The injection screen and catalogue suggestions, and hypothesis categorisation with the card check, in shadow | C5, C6 | **Done** |
| C9 | The evaluation harness, migration 0014 | C4, C7+C8 | Not started |

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

Recorded so each is decided rather than lost. Three were fixed within Phase A
and two in Phase B; the rest are still open.

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
   `broker_configured` from them. `SECRETS_KEY` decrypts the stored model keys,
   and since Phase B that includes the TypeSafe key, so the API is the one
   process that can hold a venue key and a model key together. Having the
   worker report it — on its heartbeat, say — would let the API blank the pair
   and the no-both rule extend to compose. Until then, holding is as far as it
   goes: `test_secret_isolation.py::test_only_the_programme_decrypts_a_stored_secret`
   keeps every call that decrypts a stored secret inside `src/programme`, so a
   "check the key" button in the API, the natural next step, fails the build
   rather than turning the API into a second road to a vendor.
7. **`live_job` calls `broker.submit(intent, client_order_id=coid)`,** which only
   `AlpacaBroker` accepts; the `BrokerAdapter` protocol and `SimulatedBroker` do
   not. It works in production, and a test that injected a `SimulatedBroker`
   there would raise `TypeError`. Not confirmed as a live bug.
8. **No type checker runs in CI.** One would have caught the panel defect.
9. ~~**Leases.** `job_repo.requeue_expired` applies to every kind, so phase B's
   long programme jobs must extend their leases.~~ *Resolved in Phase B.* The
   programme extends a running Jev job's lease every 60 seconds, against a
   five-minute lease, on a connection of its own.
   `test_job_ownership.py::TestTheProgrammeRunsWhatItClaims::test_the_lease_is_kept_while_the_handler_runs`.
10. ~~**When the key lands in phase B,** `TYPESAFE_API_KEY` needs adding to
    `.env.example`, to `test_env_example_is_complete.py`'s no-value check, and to
    `KNOWN_SECRETS`.~~ *Resolved in Phase B,* all three, and the step can no
    longer be forgotten for the next key:
    `TestTheVaultAndTheEnvironmentAgree` requires every stored secret to be
    documented blank and handed to the scheduled programme, and the no-value
    check finds credentials by the ending of their names.
11. ~~**Safety rule 5's text** named the runner as `tick`, `author`, `client`
    and `main` only.~~ *Resolved:* it now lists `panel`, `jev_client` and
    `jev_lane` as `RUNNER_ONLY` does. The rule's substance changes in phase F,
    with the amendment. Phase B removed the "the future" it carried before
    `jev_client` and `jev_lane`, which went stale when phase B built them.
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

### Phase B, as built

Everything needed to make one real, recorded, validated call, and nothing
switched on. Every Jev switch is seeded off; no lane is wired into `tick`,
`author` or `panel`; nothing in `src/api` or `web/src` reads the ledger; and
the one job the programme can now run, `jev_probe`, has no producer outside
the tests. The worker is untouched. The programme has made no call. The only
traffic to TypeSafe so far is the key check's, by dispatch: one listing and one
probe on 2026-09-26 (run 36270381727), both HTTP 200, the listing naming only
`jev-latest` and `jev-preview` — which is why the check had to stop looking for
the pin there — and the probe answered by `jev-1.13.0` in 201 ms, `true` at
p=0.99 with a margin of 0.98, 290 tokens in and 23 out. Nothing was recorded.

**Record once, replay forever, in the lane and in the schema.** Jev is not
deterministic (fact 1), so an answer is an event that happened once, not a
function to call again to check it. `jev_lane.ask` hashes the canonical
request — the pinned model, the state with its keys sorted at every depth, and
the questions in the order asked, options included — and looks it up before
anything is sent; an answer on record is read back, needing neither key nor
budget. The partial unique index `jev_requests_canonical` makes the rule the
database's as well: one `ok` row per request hash, outside the probe lane. Two
asks of one request in flight together can both find nothing and both call;
the loser of the insert gets the index's unique violation, replays the winner,
and logs its own vendor request id as it drops its answer. A probe always asks,
and is recorded in lane `probe`, which the index leaves out, under its set's
own name, version, pack hash and provenance. `questions` is stored as `json`,
not `jsonb`, because `jsonb` reorders keys and the order of the options is
inside the hash: a stored row recomputes its own request hash.
`test_jev_schema.py::TestTheCanonicalAnswerIsRecordedOnce`;
`test_jev_repo.py::TestTheCanonicalRace`, on two real connections;
`tests/unit/test_jev_lane.py::TestARecordedAnswerIsReplayed`; and
`TestTheRaceForTheCanonicalAnswer` and `TestAProbeAlwaysAsks` in both the unit
and the integration `test_jev_lane.py`.

**The ledger cannot be tidied, and says when each row became readable.** All
six tables refuse UPDATE, DELETE and TRUNCATE with an exception, not the silent
no-op `hypotheses` uses: a caller editing an answer is rewriting what the model
said, and should hear so at once. TRUNCATE has a statement trigger of its own,
because a row trigger never sees it. `web_documents` allows one change,
`quarantined` from false to true with a reason, with the rest of the row
compared whole through `to_jsonb`, so that a column a later migration adds is
protected without anyone listing it. `available_at` on `jev_requests` and
`jev_signals` is overwritten on insert with `clock_timestamp()` — the moment of
the insert, not `now()`, the start of a transaction a writer could hold open
across a decision cutoff — and `jev_signals.backfilled` is generated from it
and from a cutoff `jev_signals_cutoff_is_on_its_session` holds to the session's
own day in New York, so nobody writes whether a signal was live. The daily
budget and the
status summary count from UTC midnight by that stamp, not by the caller's
`requested_at`. `test_jev_schema.py::TestTheLedgerIsAppendOnly`,
`::TestQuarantineIsOneWay`, `::TestAvailabilityIsStampedByTheDatabase` and
`::TestBackfilledIsDerivedNotWritten`; `test_jev_repo.py::TestRequestsToday`.

**A row is held to its status, and a valid answer to being a measurement.**
The schema goes further than the plan above did. An `ok` or `invalid` row
carries a 2xx and the body it was validated from, `IS NOT NULL` spelled out,
since a CHECK that evaluates to NULL passes; so a 422 is an `error`, a fact
about the request rather than about Jev's answer. An `ok` row was answered by
the model it asked. A refused row got no response, and nothing a response
carries — a body, a request id, the answering model — is stored without the
status of the response it came in, which keeps exception text, and any key an
SDK release before 0.7.1 echoed into it, out of `raw_body`. A valid answer
carries its value, argmax and margin and no reason, and a valid Choice is its
own argmax, so a validator that stopped refusing SDK issue #15 still could not
write one as valid. A signal's lane, provenance and pack must be its request's,
and `measured` needs a valid answer to an `ok`, non-probe request from the
model the signal names (`jev_signals_rest_on_their_answer`): the decision
path's loader is to trust `provenance = 'internal'`, and a provenance the
writer could simply claim would reopen the injection route that filter exists
to close. `candidates.evidence_uses_model_signals` cannot be cleared once set;
the five signal-provenance columns on each run table are all NULL or all set;
and `deployments_forward_experiment_is_paper` is built now, not in phase H. A
request and its answers are one write, `jev_repo.record_exchange`, a savepoint
inside a caller's transaction, and an `ok` request without answers is refused
before anything is written, because the replay could never recover from it.
`test_jev_schema.py::TestARowCarriesOnlyTheResponseItGot`,
`::TestAValidAnswerIsAMeasurement`, `::TestASignalRestsOnItsAnswer`,
`::TestModelSignalEvidenceIsSticky`, `::TestRunsRecordTheSignalsTheyUsed` and
`::TestAForwardExperimentIsPaperAndNeverTheOperatorsBook`;
`test_jev_repo.py::TestAnExchangeIsOneWrite`. The schema suite writes with
plain SQL, so it tests the schema and not one writer's manners, on a database
of its own: the ledger cannot be cleared, and a shared one would keep the
first run's canonical answers. `TestTheVocabulariesAgree` holds the
catalogue's lanes and provenances to the schema's, and `TestTheMigration`
applies 0012 on top of a database already at 0011 and holding rows.

**The questions, and the state they are asked about.** `jev_questions`
registers `probe.connectivity` v1 — one Noul, "Is the sentence in `text` about
the sun?", about the fixed state "The sun rises in the east.", whose answer is
known to be true — and `decision.regime` v1, one Choice over `risk_on`,
`neutral`, `risk_off` and `insufficient_evidence` in that frozen order. Each
set's pack hash is pinned in `GOLDEN_PACK_HASHES`, and the regime instructions
render the windows and bucket edges `jev_features` computes with exactly, so a
band moved from 1% to 1.2% changes the words: changing a character, an
option's position or a definition fails the build until the version is bumped.
Every Choice carries exactly one escape option, last, with at least two
options besides it. The regime's options say what each regime means and name,
by path, the fields that bear on it — never the labels a rule would test. A
rule the state fully determines belongs in code, as TypeSafe's own guidance
has it; it is the baseline twin's, and a question that spelled it out would
leave Jev only a table to misread, so the forward comparison would measure
reading errors and call them an edge. The escape is the complement of a clear
fit — mixed or weak evidence — and gives no example, since any example is one
a regime could also claim. The review that found this found the first wording
did both: its criteria were a lookup table, and its escape's example and
catch-all each overlapped a regime. No request had been sent, so v1 was
reworded in place; the released hashes, kept apart from the words in the
test, now make the next change a version bump. A
decision-lane state model may hold only Literal labels, booleans and models
built from them, and neither a computed field nor a serializer, each of which
sends what no annotation shows. `QuestionSet.dump_state` takes exactly the
registered model, because a subclass passes `isinstance` and can add a computed
`as_of`, and re-validates what would be sent from its JSON.
`jev_features.regime_state` describes each of three sleeves — trend against
its 200-session average, "near" within 1%; the 20-session volatility's
quintile among its last 1,260 readings; the drawdown from the 252-session
high; the direction of the 63-session return — from `adj_close` read through
`PricePanel.at(session)`. It needs 1,280 closes a sleeve, and anything the data
cannot support makes the whole state `None`, never a guess.
`test_jev_questions.py::TestTheGoldenHashes`, `::TestEveryChoiceCarriesAnEscape`,
`::TestTheDecisionStateIsEnumerated` and `::TestDumpingAState`;
`test_jev_features.py::TestNoLookAhead`, `::TestMissingIsNone` and
`::TestEachWindowIsExactlyAsLongAsDefined`.

**Validation is strict, and never raises.** `jev_validate.validate_body`
applies fact 3's rules to the raw body and returns a verdict for anything it is
given: a call has been made and billed, and an exception would lose its record.
A defect in the module itself is caught and refuses every answer as
`validator_error`, not measured. Where the plan was loose it is stricter. A
response answering none of the questions asked is refused whole, not only one
whose `answers` is empty: one answering only questions nobody asked would
otherwise be recorded `ok` with every answer missing, and replayed as
unanswerable for good. The pin is checked against the catalogue as well as
compared, so an alias echoed back is still a mismatch, and bytes must be UTF-8.
Sums and margins are computed on the decimals the vendor wrote: in binary,
three probabilities of 0.34 miss a tolerance they meet. The first rule an
answer fails is the one recorded, from a closed vocabulary.
`test_jev_validate.py::TestNothingRaisesOnAnyInput` judges 4,000 seeded bodies
against an independently written copy of the rules;
`::TestAChoice::test_a_choice_that_is_not_the_most_probable_is_an_abstention`
is SDK issue #15, and `::TestANoul::test_true_is_not_1` the boolean that is not
a number. `test_jev_repo.py::TestTheValidatorsAnswersFitTheLedger` writes
what the validator produces to the real ledger, so the two cannot drift
apart.

**The switches fail closed.** `flags.py` gains six readers, each with
`programme_enabled`'s broad `except`. `jev_enabled`, every area switch and
`jev_send_internal_detail` are on only for a stored JSON `true`, and a string
`"true"` is logged as the error it is. `jev_area_enabled` needs the master
switch and the area's own, and a name that is not an area — the lane's
`guardrail` where the area `guardrails` belongs — is off with no row read,
because a key nobody seeded reads as off today and as on the day somebody
inserts it by hand. `jev_model` returns only what `jev_catalogue.model_problem`
accepts, and has no default. The budget and the state limit read 0 on any
failure and on any value the catalogue's `settings_problem` refuses, the
function the configuration form will call too, and a value above the ceiling
reads as 0 rather than as the ceiling: a spend control that corrects itself
upward is one an operator cannot reason about.
`test_jev_flags.py::TestEveryReaderFailsClosed`,
`::TestEverySwitchIsOnOnlyForJsonTrue`, `::TestTheAreaSwitches`,
`::TestTheModelIsPinned`, `::TestTheCountsFailClosedToZero` and
`::TestTheReadersReadTheSeededKeys`; on real Postgres,
`test_jev_schema.py::TestTheSwitchesAreSeededOff::test_they_read_as_off_through_the_shipped_readers`.

**The key.** `typesafe_api_key` joins `KNOWN_SECRETS`, so System >
Configuration stores it encrypted; the field's note says TypeSafe issues keys
at `console.typesafe.ai` and nowhere else, and names no other site, since
`web/src` may not. The programme resolves it for each job, the vault first and
`TYPESAFE_API_KEY` second, never the Anthropic key, and hands it to the lane.
`.env.example` documents it blank, and `programme.yml` passes the repository
secret of that name. `test_env_example_is_complete.py::TestTheVaultAndTheEnvironmentAgree`
turns both halves into a rule over every stored secret, and the no-value check
now finds credentials by the ending of their names, which checked
`SECRETS_KEY` for the first time. The inventory's scan also stopped counting an
assignment as a read (`TestTheScanReadsWhatItClaims`): `jev_client` writes
`TYPESAFE_LOG_LEVEL` precisely so that nothing an operator sets there matters.

**The client.** `jev_client.ask` imports `typesafe_sdk` lazily, and refuses an
alias, an unknown model or a key that is not text before it does. It then
overrides each default fact 2 lists, and goes one step further than the plan:
rather than let the SDK build its HTTP client, it builds the `httpx2` client
itself and hands it over. The SDK's own reading of a response is not evidence —
it keeps the last of a name given twice, reads `NaN` as a number, and hands its
errors a body it has already parsed — so a response hook keeps the final
attempt's response exactly as it arrived, a request hook admits every attempt
through the rate limiter, and redirects are refused. `raw_body` is the wire's
bytes, read as UTF-8 whatever the response declares, with an undecodable byte
or a NUL marked by U+FFFD; the request id comes from the header, and is `None`
when it is absent or blank; `latency_ms` is `None`, not 0, when nothing was
sent. `ask` never raises for anything the vendor or the network does: each
failure is a `JevCall` classed by `error_kind` (fact 4) and logged by class
alone, since exception text can carry what was sent. `transport` is a test
seam, which production code never passes and the lane only forwards.
`tests/sdk/test_jev_client.py` proves this against the real SDK over real HTTP,
through a transport that records each original URL before forwarding it to a
fake TypeSafe server: the host, the model and the key stay put with
`TYPESAFE_BASE_URL`, `TYPESAFE_DEFAULT_MODEL` and `TYPESAFE_API_KEY` pointed
elsewhere (`TestWhatLeavesIsWhatWasHashed`); the evidence is the response byte
for byte (`TestASuccessIsRecordedAsItArrived`,
`TestEveryFailureIsClassedWithItsEvidence`); retries are capped and
`Retry-After` is not deferred to (`TestRetriesAreCapped`); and a fresh process
told to log at DEBUG logs nothing (`TestNothingReachesALog`).
`tests/unit/test_jev_client_offline.py`, which runs where the SDK is absent,
holds the source to naming no `extra_body`, `extra_headers` or `response_model`
(`TestTheRequestIsNeverRewritten`), the limiter to its windows
(`TestTheRateLimiter`), and every call site in `src/` to passing no transport
(`TestNothingInSrcHandsTheClientATransport`, rooted at every client function
that takes one, `ask` and `list_models` among them).

**The lane.** `jev_lane.ask` is the programme's one road to Jev — the only
other is `jev_check`, the operator's, by dispatch, recording nothing, and
`test_jev_lane.py::TestTheOnlyRoadsToTheClient` holds the client to those two
importers — and each early return
writes exactly what it should. The arguments are checked first, before any
switch is read, so a caller's mistake shows while Jev is off: the set must be
the registered one, the state exactly its model, the subject non-blank and
`as_of` timezone-aware. Then the switches — the master and the area of the
set's own lane, so probing an area's question needs that area on, and only a
probe-lane set answers to the master switch alone — then the pin, the ledger,
the key, the budget and the size. An ask stopped by any of the first four
writes nothing: a switch that is off and a missing key are standing states
rather than events, a model nobody can name cannot be recorded as requested,
and an answer on record is already there. So the schema's `refused_model` is
never written today. The calls made since UTC midnight reaching
`jev_daily_request_budget`, or a request over the size limits, write a
`refused_budget` or `refused_limits` row and send nothing. Then the call, and
always a row for it. A 2xx with a body is judged by the validator, whose
verdict is the status even where the SDK raised over the body; the SDK's
objection is kept beside it in `error_class` and `error_kind`, and the two
disagree only over what the validator deliberately leaves alone, such as a
missing `usage` block. Anything else is an `error`. The validator's note, which
has no column, is logged; the state and the body never are. `run_probe` asks
`probe.connectivity` as a probe and reports each answer beside
`PROBE_EXPECTED`, with `as_expected` `None` unless every answer it knows was
measured. The `jev_probe` job succeeds on nothing less than an expected answer:
every other outcome fails it with the reason as its error, which is what the
jobs page and the daily report read (`main.probe_verdict`), retried only where
another attempt could change it — no response, a rate limit, a vendor fault, or
a switch turned off mid-job. `tests/unit/test_jev_lane.py` drives every branch against a fake
client and a fake ledger that applies the migration's checks, reading the
switches through the shipped readers; `tests/integration/test_jev_lane.py`
repeats the paths that write, on real Postgres (`TestOneAskIsOneRecord`,
`TestNothingIsWrittenWithoutARequest`, `TestARefusalIsRecordedAndSendsNothing`,
`TestWhatArrivedIsWhatIsRecorded`).

**The programme's job loop, and one owner for every kind.** `jobs` has two
consumers now. The programme drains it for the kinds in `JEV_HANDLERS`, today
`jev_probe` alone, claiming with `kinds=list(JEV_HANDLERS)` under its own
worker id, read at claim time as the worker reads `HANDLERS`, and only while
`programme_enabled` and `jev_enabled` are both on. The plan gated it on
`jev_enabled` alone. Both are asked, before every claim, because Jev is a model
API and switching the programme off should stop its spend as it stops the
tick's: two independent switches, both required, neither derived from the other
— Safety rule 1's shape, for Safety rule 7's reason. With either off, a queued
job waits with its attempts untouched. A running job's lease is extended every
60 seconds on a connection of its own, which closes open item 9; a handler that
raises fails its job for a retry, the key replaced by `[redacted]` in the
error, and one that raises `JobFailedError` fails it as that verdict says; a
kind with no handler is refused without retry. At shutdown a job already
running is given 35 seconds to finish, so a call that was sent is recorded
rather than abandoned mid-flight and asked again when its lease lapses. `test_job_ownership.py`
holds the two dispatch tables disjoint and every kind enqueued anywhere in
`src/` to exactly one owner, and refuses an `INSERT INTO jobs` in `src/`
anywhere but `job_repo`, since the scan reads `enqueue` calls
(`TestEachKindHasOneOwner`, `TestEveryEnqueuedKindHasExactlyOneOwner`,
`TestTheProgrammeClaimsOnlyItsOwnKinds`, `TestTheProgrammeRunsWhatItClaims`);
`tests/integration/test_jev_lane.py::TestTheProgrammeLoop` runs the probe job
through the loop on real Postgres.

**Dependencies, the lock and the SDK job.** `requirements-programme.txt`
declares `typesafe-sdk==0.7.1`, `pydantic>=2.12.0` and `httpx2>=2.0.0`.
`requirements-programme.lock` is its closure, resolved by uv for CPython 3.11
on manylinux x86_64 with the command recorded at its top: 64 packages, each
pinned to one version and every file to a sha256, `typesafe-sdk` to exactly
the two files of 0.7.1 that the publishing workflow attested, the wheel and
the sdist. `Dockerfile.programme`, `programme.yml` and CI's new `programme sdk`
job install it with `--require-hashes --only-binary :all:`, and the image no
longer installs a compiler. That job may hold a model SDK because it holds
nothing else: no `secrets.` reference, a token that can only read, and no
tests but `pytest tests/sdk -m sdk -q`, collected from `tests/sdk` because a
bare `-m sdk` collects `tests/e2e`, which imports Playwright. Its Postgres
service trusts every connection, so no credential exists in it to be held.
`test_dependency_boundaries.py` now reads `ci.yml` job by job, and checks its
YAML reader against PyYAML's, which also proves every workflow parses: a first
draft's unquoted `:all: ` would have stopped both workflows from loading at
all, while every line-reading rule passed it
(`test_ci_holds_a_model_sdk_only_in_a_job_that_holds_nothing_else`,
`test_the_unit_suite_runs_where_no_model_sdk_is_installed`,
`test_the_lock_pins_every_file_it_installs`,
`test_typesafe_sdk_is_the_release_whose_provenance_was_checked`,
`test_the_lock_covers_what_the_programme_declares`,
`test_the_lock_was_resolved_for_the_python_that_installs_it`,
`test_the_programme_set_is_installed_as_the_lock_hash_checked`,
`test_the_programme_set_is_refused_wherever_the_programme_is_not`,
`test_the_jev_client_imports_only_what_the_programme_declares`,
`test_the_job_reader_agrees_with_yaml`,
`test_the_marker_ci_selects_is_registered`).

**One call end to end.** Every other suite holds a fake on one side, and a fake
is a reading of the other side that two suites can share while both are wrong.
`tests/sdk/test_jev_lane_over_http.py` drives the shipped chain whole — lane,
client, the real SDK and `httpx2`, real HTTP to the fake TypeSafe server,
validator, and the ledger on real Postgres — and asserts on the two ends. The
stored request hash recomputes, from its written definition rather than the
lane's function, from the request that left; the stored body is the body that
arrived; a second identical ask makes no HTTP request; a non-JSON 403 is a
`content_block` row; no response at all leaves no evidence and still counts
against the budget; and a probe asks every time and is never the canonical
answer.

Phase B added one migration, eight modules, eleven seeded settings, the SDK
with the lock that pins it, one CI job, and the dispatch-only key check
(`jev_check.py`, `jev-check.yml`) with the listing call it needs,
`jev_client.list_models`, built on the same hardening as `ask`. The worker and the decision path
import none of it, and the API reaches only `jev_catalogue`, through `flags`,
which is what a pure catalogue is for.

### Open items Phase B found

Numbered on from Phase A's, so a reference to either list is unambiguous.

14. **The configuration page names one fallback.**
    `web/src/app/system/configuration/page.tsx` tells an operator whose
    `SECRETS_KEY` is unusable that the programme falls back to
    `ANTHROPIC_API_KEY`, and does not mention `TYPESAFE_API_KEY`. Phase E.
15. ~~**The request hash does not name the question set.**~~ *Resolved in phase C, by C1+C2:* the hash is unchanged — two sets sending identical bytes did send the same request — and attribution is checked beside it, three ways. The registry refuses a set whose questions hash equals a registered set's; `RELEASED_QUESTION_HASHES` holds every released version's pairwise distinct, words no longer registered included; and the lane raises if the answer it would read was recorded by another pack — before sending anything when it is the canonical row a replay would read, and after the call when it is the winner of a race that call lost, which is billed and dropped unrecorded like every lost race's (item 17). See Phase C, as built.
16. **`flag_repo.get_flag` decodes any string it is given.** asyncpg hands
    `jsonb` over as text, which the reader parses. Were a JSON codec ever
    registered on a pool, a stored JSON string `"true"` would arrive as the
    text `true`, parse, and read as on — for every switch, the kill switch
    included. No codec is registered today.
17. **The daily budget is approximate at its edge.** The check and the call
    are not one step, so asks in flight together can overspend it by at most
    their number, and a call that loses the race for the canonical row writes
    no row, so the budget never counts it. The programme asks one at a time.
    In the other direction, an `error` row for a call that sent nothing — a key
    the SDK refused, a defect on this side — counts against it: a conservative
    over-count, kept deliberately.
18. ~~**Nothing enqueues `jev_probe`.**~~ *Closed by C4:* the planner
    enqueues one a UTC day, under `jev_probe:{date}`, once the programme and
    Jev are both on with a usable pin and a key; seeded, it plans nothing.
    Phase E's `POST /jev/probe` will be a second producer, by hand.
19. ~~**Two Rule 5 enforcements planned for phase B were not built.**~~ *Resolved in phase B:* `tests/unit/test_jev_table_boundaries.py` now holds both — outside the programme only `src/db/repos/signals.py` may name a Jev table, only `jev_lane` may write `jev_signals`, and the model-holding runners never name it — each scanner proved against sources that must trip it.
20. ~~**What the validator does not check.**~~ *Resolved in phase C, by C1+C2:* a Score's `legend`, where it sends one, must name the levels asked, in order (`legend_mismatch`), and its `score` must be its own probability-weighted mean within a deliberately conservative bound on what rounding to the 0.01 grid can move it, one that holds however the score is reported and admits some answers rounding alone could not produce (`score_inconsistent`). The tripwire test is replaced by a registration rule admitting a Score of at most four levels, the most for which the 0.02 sum tolerance covers that rounding. Still open: a Score of five to ten levels needs a tolerance measured from recorded answers, and the legend's wire format has not been observed (item 34).
21. **The validator's note has no column.** `Validation.problem` — why a
    response was refused whole, which unasked answers were ignored, whether
    the usage could be read — goes to the log and nowhere else. Each answer's
    `invalid_reason` and the verbatim body are stored, so nothing is lost that
    cannot be recomputed, but phase E's status page may want it stored.
22. **`programme sdk` is not a required check.** If branch protection lists
    required checks, it should name the new job, or a pull request can merge
    with the SDK's tests failing.

### Phase C, as built

Phase C lands as seven pull requests (see Delivery). Each adds a subsection
here as it lands.

#### C1+C2: the road, hardened, and the Score checks

Every rule a phase C lane could forget now lives in `jev_lane.ask`, the
registry or the schema, before any lane exists to forget it. Nothing new can
be asked: no set is registered, nothing is enqueued, every Jev switch is still
seeded off, and every change to the road is a refusal it did not make before.
The programme has still made no call.

**The road reads every switch itself.** `ask` reads `programme_enabled`,
`jev_enabled` and the area of the set's own lane on every ask, before the
ledger, and for a set declaring `internal_detail` then
`jev_send_internal_detail`, which this is the first reader of. Each goes
through its own fail-closed reader and none is derived from another. The
programme's loop still reads the first two before it claims a job; the road no
longer depends on its having done so, because a planner, a harness or a job
added later might not. `internal_detail` is part of a set's equality and not of
its pack hash, so a copy with it cleared is not the registered set, and `ask`
refuses it. `tests/unit/test_jev_lane.py::TestTheProgrammeSwitchBindsTheLane`,
with the order of the reads asserted, and `::TestTheDetailSwitch`, through
test-only sets registered for a test and gone after it; on Postgres,
`tests/integration/test_jev_lane.py::TestNothingIsWrittenWithoutARequest`
gains the programme's switch.

**A text subject is its content.** The request hash names no subject, so the
same excerpt filed under two ids would be answered once and recorded against
one of them, and a label on the other would never meet its answer. Among the
arguments, before any switch, `ask` now requires the subject type to be the
state model's own (`jev_questions.STATE_SUBJECT`: `probe`, `session`,
`web_excerpt`, and from C8 `hypothesis_title`), a text subject's id to be the
sha256 of exactly the text sent (`jev_hash.text_sha256`, which migration
0013's CHECK `web_documents_content_is_its_excerpt` makes the address every
stored document is filed under), and a session's to be its date written
`YYYY-MM-DD`. A state model with no subject type, or a web set whose state is
not addressed text, is refused there too, for a set placed in the registry by
hand. `test_jev_lane.py::TestSubjectsAreContentAddressed`;
`test_jev_schema.py::TestADocumentIsAddressedByItsExcerpt`.

**Web text is asked about only once screened, and never once quarantined.**
Registration holds provenance `web` to `WebExcerptState`, an excerpt of 1 to
300 characters and nothing else, and the other way round. For a web set, `ask`
refuses text quarantined under any source as `quarantined`, the injection
screen included; and for every web set but the screen, text without a clear
answer from the screen as registered now under the pin — a canonical,
non-probe answer about exactly this state whose `addressed_to_ai` Noul is
valid and `false` — as `unscreened`. Both are checked before the replay, so an
answer on record about text since quarantined is not read back, and they bind
probes as well. The screen is a web set asking `addressed_to_ai`, as a Noul,
and nothing else (`jev_questions.screen_problem`): the gate lets the screen
alone ask about unscreened text, so a second question in it would be answered
about exactly that text. Registration refuses any other set under the screen's
name, and one placed in the registry by hand is no screen: it is asked nothing
about unscreened text, and its answers clear nothing. No screen was
registered until C7, so until then every web ask was unscreened: the gate
failed closed (C7+C8 below registers `guardrail.injection`).
`test_jev_lane.py::TestTheWebGate`, and on real `web_documents` and screen
rows, `tests/integration/test_jev_lane.py::TestTheWebGate` and
`test_jev_repo.py::TestTheWebReads`, where each filter of the screen's read is
the only one barring some case the schema allows.

**The vendor's standing refusals are remembered.** Fact 4's actions, derived
from the rows the failures left, so no process writes a switch: an `auth`
failure since 00:00 UTC, by the database's stamp, holds every lane until then
(`auth_held`), the connectivity probe's included — and, since nothing records
which key failed, a key replaced before midnight is held with the one it
replaced, so the dispatch-only `jev_check` is what proves it sooner (open item
37); a 422 holds its set, version and pinned model for good (`set_refused`),
since the same words would be refused again and a new version is what changes
them; and a content block holds exactly the text it answered, across every set
and lane, a probe's included (`content_blocked`). Text only — a web excerpt or
a hypothesis title, the states a content filter could object to. The first
draft held any state, and the review found what that cost: an enumerated
regime state, labels computed in code, held for good by one 403 page an edge
served, which would take that state out of the forward clock, its canonical
answer's free replay included, for as long as the market stayed in it. So an
enumerated state, the connectivity probe's among them, is held by nothing: its
failure is recorded and it is asked again (open item 36). The block is checked
before the replay, like quarantine, because blocked text is not read back; the
two holds after the replay and the key, since they exist to stop calls and a
replay makes none. None of the new statuses writes a row: each is a standing
state read from rows already written, not an event. `main.probe_verdict` fails
the probe's job on each, without a retry, and its words for `auth_held` point
to the key check. `test_jev_lane.py::TestStandingRefusals`;
`tests/integration/test_jev_lane.py::TestTheVendorsStandingRefusals`, each
refusal that would hold the tests after it on a database of its own, with
yesterday's failure written with the stamp switched off, and blocked text in
`::TestTheWebGate`; and `test_jev_repo.py::TestTheStandingRefusals`, the reads
against real rows.

**No lane can starve another.** `jev_catalogue.LANE_BUDGET_PERCENT` gives each
recorded lane its share of `jev_daily_request_budget`: research and guardrail
35%, decision 20%, probe 10%, and 0 to the lanes with no set. In code, so no
database write can raise one, and rounded down, so the shares never exceed the
budget: at the seeded 500 calls, 175, 175, 100 and 50. Below 10 the probe
lane's share would be none, and below 5 the decision lane's, while the setting
read as a budget that permitted calls, so the catalogue refuses a budget of 1
to 9 as it refuses any unusable setting, and the runner reads it as 0
(`MIN_DAILY_REQUEST_BUDGET`, derived from the shares; the probe job's error
names the probe lane's share). `ask` asks the budget and then the recorded
lane's share, and either refusal is a `refused_budget` row. A probe is
recorded, and counted, in the probe lane whatever its set, so it spends the
probe lane's share and is held to it. `test_jev_lane.py::TestTheLaneSlices`,
`test_jev_catalogue.py::TestTheVocabulary` and `::TestTheSettings`, and on
Postgres `tests/integration/test_jev_lane.py::TestTheLaneSlices`.

**No answer crosses question sets (open item 15).** The request hash is
unchanged — two sets sending identical bytes did send the same request — and
attribution is checked beside it, three ways. `registration_problem` refuses a
set whose `questions_hash`, the part of the request hash a set contributes,
equals a registered set's. `RELEASED_QUESTION_HASHES`, kept in the test beside
`RELEASED_PACK_HASHES` and append-only like it, holds every released version's
questions hash pairwise distinct, so a retired version's words, a copy under a
new name and a version bump that changed only a lane or a provenance are all
refused, words no longer in code included. And `ask` raises if the answer it
would read carries another pack hash: before anything is sent when it is the
canonical row a replay would read, which also covers a row written by hand;
and after the call when it is the winner of a race this call lost, since the
race is only found when the answer is recorded — that call was made and billed,
and like every lost race's it is dropped unrecorded and logged with its vendor
request id (open item 17). `test_jev_questions.py::TestOpenItem15` and
`test_jev_lane.py::TestNoAnswerCrossesSets`.

**The rest of the registry's rules.** `registration_problem` runs after
`question_set_problem` at registration, in order: one set per name; item 15;
web text is a `WebExcerptState` and nothing else is web; a set of provenance
`internal`, `operator` or `model` whose state could carry text beyond a plain
`title` declares `internal_detail`; every state model has a subject type; text
is recorded as its writer's (below); and the screen is a web set asking
`addressed_to_ai` as a Noul and nothing else, since the road reads a valid
`false` from it as clean and lets it alone ask about unscreened text.
`test_jev_questions.py::TestRegistrationRules`, each half of the web rule by its
own message.

**This system's detail goes only where declared** (fact 7). The detail rule
fails closed: a field is text unless the rule can prove otherwise — a Literal,
a boolean, an integer, a float or `None`, a model built only from those that
sends nothing its fields do not declare, or a container or union of them.
Everything else counts: `str`, `bytes`, `Any`, and every shape the rule does
not read, a dataclass, a TypedDict, a NamedTuple, a NewType, a URL, a path, a
secret, a date, an enum, a `Decimal`, which is sent as a string; and so does a
validator that runs after or instead of a field's type, a serializer, a
computed field, a JSON encoder, and a nested model that keeps undeclared keys.
The first draft read `str`, `bytes`, `Any` and nested models and nothing else,
and the review registered a finding's full text in a pydantic dataclass as no
detail at all, which the road then sent with `jev_send_internal_detail` off.
The rule is read a second time on every ask, from the output rather than the
types: `QuestionSet.dump_state` refuses, for a set of this system's own text
without `internal_detail`, any string beyond the top-level `title` that its
state model does not write itself — a field name, or a value one of its
Literals allows — so no shape the first reading misses can carry detail past
the switch; at worst such a set is refused on its first ask, before any switch
is read. `test_jev_questions.py::TestTheDetailRuleFailsClosed`, every shape the
review found and every shape that must still pass, and
`::TestDumpingWhatAStateSends`; `test_jev_lane.py::TestUndeclaredDetailIsNeverSent`.

**Model-written text is labelled `model`.** Migration 0013 adds the provenance
to both tables' CHECKs, keeping each constraint's name, with the indexes the
road's reads stand on and the content-address CHECK (see the schema section).
Phase C will ask Jev about the titles the programme's own model writes, which
are none of `web`, `internal` or `operator`; recorded as `internal` they would
pass the one filter the phase F loader is to trust. The schema only admits
`model`; what holds a set to it is registration: `TEXT_SUBJECT_PROVENANCE`
names who writes each kind of text a set may ask about — a web excerpt the
web, a hypothesis title the programme's model — and a set whose subject is one
of them records that provenance and no other, a set carrying a title and more
included, while a state model of text whose subject names no writer is
refused. An operator's text (open item 28) will be a subject of its own.
`test_jev_questions.py::TestTextIsRecordedAsItsWriters`; and
`test_jev_schema.py::TestModelProvenance` applies 0013 on top of a database at
0012 holding requests, signals and a document under each older rule, and reads
every row back unchanged.

**A request's identity is its own module.** `state_hash` and `request_hash`
moved, verbatim, from `jev_lane` to the pure `jev_hash`, beside
`questions_hash` and `text_sha256`, so the registry, the API and the harness
can compute one without loading the client; `jev_lane` re-exports both. The
worker and the decision path may import it no more than any other module of
the programme.
`tests/unit/test_jev_hash.py` pins the request hash to a value phase B's code
computed, and imports the module in a fresh interpreter to show it loads
nothing from `src` but itself, and nothing that reaches a network, a database
or a model.

**A Score answer is checked against itself (open item 20, C2).** Two reasons
join `jev_validate.ANSWER_REASONS`, applied after the score's range and before
the confidence. `legend_mismatch`: a `legend`, where one is sent, must name the
levels asked, in order, as a list of them or as an object keying each by its
index written as text; anything else, a null included, fails closed, because
the vendor's shape has not been observed. `score_inconsistent`: the score is
documented as the probability-weighted mean of its levels, and one further
from that mean than `score_consistency_bound(n)` =
0.005·(1 + n(n−1)/2) disagrees with itself, like a Choice that is not its own
argmax, and is not measured. The bound is derived, not chosen, and
deliberately conservative: each probability is observed on the 0.01 grid,
within half a step of its true value, and level i's rounding moves the mean by
up to i half steps; the score's own grid has not been observed, so it is
allowed half a step more, as though rounded independently — 0.01 at two
levels, 0.02 at three, 0.035 at four, compared on the decimals written. That
refuses nothing rounding could explain, however the score turns out to be
reported. It is not tight, and it admits answers rounding alone could not
produce: a score rounded to the grid is the rounding of the same mean the
probabilities were rounded from, so rounding moves it by at most 0, 0.02 and
0.03 at two, three and four levels (0.01 at three, rounding halves up), and a
two-level score 0.01 from its rounded top probability is accepted though no
rounding made it. A bound as tight as rounding halves up would refuse an
honest score reported at full precision, which can sit 0.015 away at three
levels against its 0.01, so tightening waits on recorded answers that show how
the score is reported. The tripwire that refused any Score set is replaced by
the rule behind it: a Score question registers with at most four levels
(`MAX_SCORE_LEVELS_UNMEASURED`), the most for which the 0.02 sum tolerance
covers the grid's rounding, four half steps; more need a tolerance measured
from recorded answers, and the vendor's own limit of ten stays the ceiling
beyond that. No Score set is registered. `test_jev_validate.py::TestAScore` —
the bound worked out again from its definition, how much of it each way of
reporting the score uses, every corner of the rounding box accepted at two to
four levels over distributions across the simplex, and the five-level corner
the sum tolerance refuses — with the 4,000-body fuzz's independent copy of the
rules gaining both checks;
`test_jev_questions.py::test_a_score_question_registers_only_up_to_four_levels`.

Changes to phase B's tests, each because the behaviour changed: the lane rig
switches `programme_enabled` on, fakes the six new reads, and asks the probe
about its own subject; two budget tests moved to budgets whose lane shares are
not zero, and the spent-budget test from a budget of 3 to one of 10, since 3 is
now refused as a setting; the two tests of what the ledger is asked for a
regime state still expect no read before the answer's, since no block holds a
regime state, and a new one expects the block read first for text; the
storable-text test screens its text before a web set asks about it, and the
two unstorable-text tests match their refusal's message, since the subject rule
would refuse one of them too; the Score test that scored 0.0 for a mean of 0.1
now scores it for a mean of 0.01; the pinned provenance vocabulary gains
`model`, and the schema's closed-vocabulary case refuses `vendor` instead; the
ten-level Score shape is now a refused one; the schema suite's documents are
filed under their excerpts' addresses, as 0013's CHECK requires, so its
one-snapshot test repeats an excerpt rather than a hash; and the probe-verdict
table gains the new statuses and the budget's new words. The integration
probe-job cases run on databases of their own, and the SDK suite switches the
programme on.
Phase C lands as several pull requests, each reviewed on its own, and each has
a part here.

#### W: the reference bars, and one adjustment basis for the live ingest

A worker change, reviewed as one on the live path, with the parity and
real-data suites unchanged and green. It moves no switch, and nothing it adds
is enqueued: the programme's planner (C4) will be the new job's first producer.

**The live ingest keeps one adjustment basis** (open item 23, closed here).
Yahoo back-adjusts `Adj Close` at every distribution, so each fetch returns the
whole history on the basis of the day it was made. `run_ingest_bars` refetched
ten days and upserted them, which left every older row on the basis of the last
day that fetched it: each distribution left a step at the ten-day boundary, the
steps accumulated, and a stored series drifted from any fresh fetch of its own
history by roughly the symbol's distribution yield a year — an estimate from
the yields, not a measurement. The live decision read that table while a
backtest of the same days fetched afresh, so a signal with a lookback was
computed on different numbers on the two paths. The ingest now refetches each
symbol it owns over its whole stored span, from the earlier of its first stored
session and `session - REFERENCE_WINDOW_DAYS` (2,200 calendar days, which hold
between 1,510 and 1,524 NYSE sessions across the calendar) to its latest stored
session or the job's, whichever is later, and every stored row the fetch
returns takes that fetch's `adj_close`: the adjusted series is on one basis,
even when a retried job for an older session runs after a newer one. A stored
session the fetch did not return keeps its older basis: it is counted in the
job's `rows_not_refreshed`, with a warning naming the first five, and the job
still succeeds, because a vendor that has stopped returning a session will not
return it to a retry either, and the live path is never failed over a
data-quality condition it did not fail on before. A symbol whose session bar
the fetch left out is named in `session_missing`, with a warning, and the job
succeeds too: the live decision has no close for it, as it never had; the
warning used to be judged by the newest bar across every symbol, which one
symbol's landing made look complete. A fetch of the whole span that fails is
another matter, because a retry can mend it. It is followed by one of the
last `INGEST_LOOKBACK_DAYS`, the window this job always fetched, and that is
written, so the session's bar lands wherever the ten-day ingest landed it and
the live decision loses nothing. The job then fails, naming the stored rows
it could not re-base, so the worker retries the whole span: those rows keep an
older basis, so a step at the ten-day boundary is back for every distribution
since the last whole refetch, and as built the job succeeded that day with the
fact in a result nothing reads. `ingest_bars:{session}` now succeeds only once
one fetch has re-based every stored row it returns, which is what the forward
clock can read (open item 40). The fetch runs in a thread, as a backtest's
does, so the lease and the heartbeat keep answering while years download, and
the writes are one transaction, so a failure part-way leaves every stored row
as it was and no reader sees a series half re-based; the refresh is one
statement in `(symbol, session)` order, so two workers refreshing overlapping
spans lock rows in one order and cannot deadlock. The thread and the
transaction were claims with no test behind them until review removed each
and found the suite still green:
`tests/unit/test_reference_bars.py::test_the_fetch_leaves_the_event_loop_free`
now needs a coroutine to run beside the download for the download to return,
and `tests/integration/test_reference_bars.py::TestOneTransaction` fails the
second statement of a write on Postgres and finds every row the first one
rewrote as it was, down to its `xmin`. Refetching years every session would
rewrite every row every day, so a row the fetch repeats is left alone; on a
day with no distribution only the new session is written, and the result's
`new_bars` counts the sessions the table did not hold before, beside `bars`,
every row the span returned. The span grows a session a day, bounded by the
instrument's listed history.

**Raw prices stay as they were written.** `daily_bars` holds raw prices, and
Yahoo's `Close` is split-adjusted: a split halves every earlier session's raw
prices in each fetch after it. The ingest refreshes a row whole, raw prices
included, only inside `INGEST_LOOKBACK_DAYS` of the job's session, as it always
refreshed it — which is how a vendor's correction of a recent bar lands, and a
missed recent session is caught — and any other stored row takes only its new
`adj_close`, its open, high, low, close and volume staying as first written. So
after a split an old row's adjusted close is on the new basis and its raw close
is as first written — as it traded for a row written before the split, and
already split-adjusted for one first fetched after an earlier split, which
covers the six years the first ingest after this merges backfills: their ratio
is no adjustment factor, and nothing reads it as one. A session not yet stored
is inserted whole, so a missed session is now caught across the whole span —
on the split basis of the day it is fetched, so a gap older than the lookback,
filled after a split, sits on another raw basis than the rows either side of
it, where the ten-day ingest never filled it at all.
`tests/integration/test_reference_bars.py::TestTheLiveIngestKeepsOneBasis`
puts a fake vendor with Yahoo's shape through a distribution between two
ingests and finds every stored row's adjusted close on the second day's basis,
over a thousand of them behind the old ten-day boundary; through a split, and
finds raw prices repriced inside the lookback and nowhere else, and the shadow
replay's prices for older sessions unchanged; leaves no row on another fetch's
basis when a late job runs after a newer one; when the span will not download,
lands the old window and fails, and through the worker's own claim is retried
until the whole span lands on one basis; counts a session the fetch omits and
keeps its row; changes nothing when every fetch fails; rewrites no row a rerun
repeats, down to its `xmin`; and reads the live panel back as exactly the
panel a fresh fetch of the same span builds, every field, cut at the session.

**No money reads an old row.** A split inside the lookback still reprices those
rows, as it always has, and every old row's adjusted close now moves with each
distribution, so `tests/unit/test_daily_bars_readers.py` names every statement
that reads `daily_bars`, with what it reads, and fails the build on one it does
not name — spelled as a literal, an f-string, a string assembled by `+` or
`str.join`, SQL's `TABLE daily_bars` shorthand, or one of asyncpg's table
copies, which name the table as an argument and hold no SQL; review found the
last three passing unnamed, and each spelling is now proved against sources
that must trip it: the live panel (`live_job._load_panel`), whose old rows reach a
strategy only as `adj_close` and money only as the session's own close, through
`Driver._prices`; the shadow replay (`shadow_job._price_map`), which fills and
marks a hypothetical book at old opens and closes and writes no order, fill or
mark; and five that count rows or sessions and read no price. Marks come from
the venue's account, and fills from its orders. For every registered strategy,
scrambling the raw prices of every row before the session leaves
`Driver.decide`'s orders exactly where they were, and scrambling the session's
own close moves them. The first ingest after this merges backfills about six
years for each deployed symbol, SPY today. The deployed `buy_and_hold` needs
one session of history, so its decisions do not change; a strategy with a
lookback now has on the live path the history its backtest had, where before it
had the weeks the ten-day windows had accumulated. The programme's gate 0 → 1
counts a candidate's rows in `daily_bars` (`universe_available`, at least 60),
so a candidate on SPY now finds years there where it found weeks.

**The reference bars are the worker's.** `src/data/reference.py` holds
constants the worker reads, and the programme will read from C4:
`REFERENCE_SLEEVES` (equities SPY, bonds IEF, commodities GSG, keyed by
`jev_questions.SLEEVES`), `REFERENCE_SOURCE` (`yfinance`, the one source the
forward clock will read), `REFERENCE_WINDOW_DAYS`, `REFERENCE_MIN_ROWS` (1,300:
above the 1,280 closes a regime state needs, and below the fewest sessions any
backfill writes, so one backfill is enough) and `REFERENCE_PRIORITY`.
`run_ingest_reference_bars` is registered in the worker's `HANDLERS` and
nowhere else — not `SCHEDULED_KINDS`, `JobKind`, `DRAINABLE` or
`KILL_GATED_KINDS`, as `shadow_decision` is not — so the worker claims it, the
session planner never plans it, the API cannot drain it, and the kill switch,
which stops what reaches a venue, does not stop it, as it does not stop
`ingest_bars`. It reads one thing from its payload, the session, which must be
an NYSE session. The symbols are the constant, so a symbol list in a payload is
ignored and no job row chooses which instruments the worker fetches, and a
source by any name but `REFERENCE_SOURCE` is refused.

Nor does the session choose when the job runs or how far back it reaches. As
built it was checked against the calendar alone, so a job run before the close
fetched the session in progress as its close, and a job for a session years
past counted a live-owned sleeve's rows only up to that session, found it
short, and backfilled years in front of the live ingest's first row, from
which every later live ingest refetched. Review found both. The job now runs
only inside `maintenance_jobs.reference_window`: from its session's close plus
`INGEST_AFTER_CLOSE`, when the live ingest fetches the same bars, until the
next session's bars settle, when that session's job refetches everything this
one would and this one's forward-clock cutoff has long passed. Both bounds come
from the calendar, early closes and daylight saving included, and are judged
by the database's clock, the one that released the job from the queue, so a
job the planner schedules at the moment its bars settle is never refused over
two machines disagreeing. Outside the window the job is refused before it
fetches or writes anything.

A sleeve is the live ingest's while an enabled operator deployment trades it,
since the live ingest fetches exactly what enabled deployments trade. A sleeve
no enabled deployment trades is refetched over its whole stored span and
written as the live ingest writes its own: adjusted closes everywhere, raw
prices whole only inside the lookback. A sleeve the live ingest owns is that
job's: it is fetched only when it has fewer than `REFERENCE_MIN_ROWS` rows up
to the session, and then only its history before the live ingest's lookback is
inserted, with `ON CONFLICT DO NOTHING`, so no row the live ingest wrote
changes, and no bar the live ingest refreshes whole is written by a job the
programme enqueues. The session's close is among those bars, and it is what
the live decision sizes its orders from: as built, a backfill ran to the
session itself, so a newly enabled deployment whose live ingest failed that
day read its close from the reference job — the session in progress, had the
job run early — where before it read none. The live ingest re-bases what was
filled on its next whole refetch, since its span starts at the first stored
session. Ownership is read again inside the transaction that writes, so a
deployment enabled while the job downloads takes its sleeve back before
anything of it is written (`taken_back` in the result). Ownership follows the
live ingest in both directions — as built, this section and CLAUDE.md said no
live-ingest row was ever overwritten, which review found false after a
disable: disabling the last deployment that trades a sleeve hands the sleeve
to this job, which refetches its whole span and writes it by the live ingest's
own rules, and enabling one hands it back, the next live ingest re-basing the
whole span again, so a sleeve is always exactly one job's. Making ownership
outlast a disable instead would leave a disabled deployment's sleeve to
neither job, and a forward clock reading a series nobody refreshes. One
consequence is deliberate and small: a deployment enabled after its session's
live ingest has run finds, for that session's decision, the bars the reference
job last wrote while the sleeve was its own — the same vendor's settled bars by
the same rules — where before this it found no close for the session at all,
and traded a session later.

The job exists to put its session's close in the table for every sleeve, and
as built it succeeded without one: a vendor late with one ticker's bar, or a
per-ticker failure `yfinance` swallows while the other tickers load, left a
sleeve short with the job retired as done, and its staleness warning read the
newest bar across the sleeves, which the other two made look complete. Now,
once what landed has committed, the job fails while any sleeve lacks its
session's close, naming each and whose bar it is — the vendor's, which a retry
can fetch, or the live ingest's, which this job never writes — so the worker
retries it and the jobs page says why. That covers a live-owned sleeve too,
the live ingest having left its bar out or the deployment having been enabled
after the live ingest ran. The two jobs share one fetch and one writer, so they
cannot drift apart. One fetch, in a thread, serves every symbol that needs one;
both writes are one transaction; a failed fetch fails the job for the worker's
retry, with no fallback, since nothing on the live path waits on it; and the
result holds counts and symbols, never a price. `REFERENCE_PRIORITY` is 1,
below every live-path kind (the lowest is 5) and above a queued backtest's 0,
so when the reference job and `ingest_bars` are due together the worker, which
runs one job at a time, claims the ingest first. A priority orders claims and
does not preempt a job already running, so the planner is to schedule the job
no earlier than `ingest_bars`, at the same minute after the close. Every
`enqueue` of the kind anywhere in `src/` must pass `REFERENCE_PRIORITY` by name,
and only `src/programme/jev_plan.py` may enqueue it, so the planner that lands
in C4 is held to both. Nothing in `src/programme`, or anything it loads, writes
`daily_bars`: `test_import_boundaries.py::test_nothing_in_the_programme_writes_daily_bars`
walks the programme's import closure reading SQL — a write to the table named,
interpolated, formatted or concatenated on, a `DROP` or `ALTER` of it, a
statement assembled from literals by `+` or `str.join` and read as the one text
it makes, a write verb standing alone whose table is joined on from somewhere
the scan cannot follow, and asyncpg's bulk writers — each spelling proved
against sources that must trip it. Review planted a joined and a concatenated
`INSERT` in the programme and found both passing; both now fail it. Like every
scan here, it reads spellings and is not a sandbox.
`tests/unit/test_reference_bars.py` holds the rules without a database, and
`tests/integration/test_reference_bars.py` holds them on Postgres.
`TestTheReferenceJob`: sentinel rows of a live-owned symbol survive whole, a
distribution re-bases every stored row of a sleeve the job owns, a rerun
changes nothing, the job runs through the worker's own claim with the kill
switch engaged, and a sleeve without its session's close fails the job, which
the worker retries until the bar lands. `TestTheWindow`: Postgres's own clock
refuses a session not yet settled and one long superseded, and a stale session
leaves a live-owned sleeve as the live ingest wrote it. `TestWhoOwnsASleeve`:
a disable hands a sleeve over and an enable hands it back, a deployment
enabled mid-download takes its sleeve back with every row as it was, and the
live decision's close is the live ingest's or none. Like the live ingest, it
reads the deployed universe by building each enabled deployment's strategy, so
a deployment whose stored parameters no longer validate fails it, as it fails
the live ingest and the live decision.

**Where W departs from the design.** Two departures, both toward keeping what
is stored. The design refetched a reference-only sleeve over the window alone,
which leaves every row older than the window on the basis of the last day the
window reached it, so a regime state recorded more than about a year earlier
would recompute across a step; the reference job starts each span at the first
stored session, as the live ingest does. And the adjustments to the design had
the live ingest upsert every row returned, which would have carried each split
into every old row's raw prices: the shadow replay fills its recorded
quantities at those prices, so a split would have repriced a candidate's whole
shadow book after the fact, where the ten-day ingest repriced at most ten days
of it. Raw prices are refreshed only where they always were, and the adjusted
close, which is what needs one basis, is refreshed everywhere. Additions: the
refetch reaches the latest stored session, the live ingest falls back to the
old window when the span will not download and then fails the job so it is
retried, a row the fetch repeats is not rewritten, the fetch runs in a thread,
the writes are one transaction in one row order, the result counts the new
sessions apart from the re-based ones, a source not named `yfinance` is
refused, the priority is a constant every enqueue must name, the job runs only
in its session's window, a backfill never enters the live ingest's lookback,
and a sleeve without its session's close fails the job.

#### C5: web sources and the fetcher

The one egress phase C adds, reviewed on its own. It was to land with the
ingest job as C5+C6; it lands first, alone, so that the one part of phase C
that reaches the open web is read without the rest around it, and the ingest
job (C6), which also needs the forward clock, follows. Nothing imports the
fetcher, nothing is enqueued, no switch moves and no table is written: the
programme has made no call to Jev and fetches no page.
`src/programme/web_sources.py` is pure, and the API may import it;
`src/programme/web_fetch.py` is runner-only, and the only module in
`src/programme` that imports `aiohttp`.

**One page, written out, and fetched as written.** `web_sources.ALLOWED_SOURCES`
holds one source, the paperswithbacktest README at its raw address on GitHub,
with the rules its response is held to: `text/plain` in UTF-8, at most 512 KiB
(the page is 90,734 bytes), read by the parser `pwb_readme_strategies/v1`.
Each entry is checked when the module loads — `https`, the host written out
and equal to the entry's own, a DNS name and not an address, no port, user,
query or fragment, no empty or dot segment and no escape in the path, printable
ASCII, and unchanged by being split and joined again — so a malformed entry
fails every import rather than the first fetch; and the module then records
each entry as written, the object and its values in a tuple nothing can edit
(`web_sources.as_written`). The entries are frozen, but a frozen dataclass is
edited anyway, by `object.__setattr__` or a slot's descriptor, and checking an
entry's rules again at each fetch refused only an edit that broke one: review
pointed the entry at another well-formed https page and the fetcher fetched it.
The fetcher now refuses any entry that is not exactly as written — another
page, a larger cap, another type, or a list rebound to hold a new entry — and
fetches with the values recorded rather than the live entry's, so what is
checked is what is fetched.
`test_web_sources.py::TestTheAllowList::test_the_allow_list_is_pinned` pins the
entry field by field and holds its host clear of every model vendor's host, of
fact 9's lookalikes and of any TypeSafe name; `::test_the_list_is_checked_when_the_module_loads`
loads the module with its URL made plain http and requires the import to fail;
`::test_each_rule_refuses_on_its_own` gives each of five rules an input only it
refuses, `127.1` among them, which `ipaddress` does not read as an address and
a resolver reads as 127.0.0.1; and
`::TestNothingInSrcWritesToTheAllowList` refuses the spellings of an edit it can
read: a write to the list or its record under any alias, `vars()`, `globals()`
and `locals()`, a computed `setattr`, a new `AllowedSource` under any name,
`object.__setattr__` naming an entry's field or a name not written out, a
descriptor's `__set__` or `__delete__`, `__dict__`, and the `gc` walks that
reach the mapping inside a `MappingProxyType`. It reads spellings and is not a
sandbox; the fetcher's own comparison is what holds whatever it misses.

**Titles, and nothing else.** `parse_pwb_readme` reads only between the
generator's markers — exactly one of each, as whole lines, in that order — so
the README's second `## Crypto`, under its books, is never read. Every line
inside must be blank, one of the seven level-two headings `HEADING_LABELS`
names, a table row, or the generator's note in italics before the first
heading; anything else refuses the snapshot. Review found the parser reading
lines where a renderer reads blocks: a setext heading, an `<h2>`, a heading
in a quote or a list, or an italic line after a heading, all of which a reader
takes for a heading, were skipped, and the rows under each filed under the
heading before; and the rows inside a comment, a code fence or `<details>`,
which a reader never sees, were kept. A row is kept only if it matches
`ROW_PATTERN` in full, digits in ASCII. Only
its title survives: the link and the four figures, a Sharpe among them, are
dropped, and are never stored or quoted. A table's header and delimiter rows
are told apart by Markdown's own rule, the row before the delimiter, and every
other line that opens with a pipe is a row, counted, then kept or dropped. No
line inside the block may be longer than 4,096 characters, measured before any
pattern reads one — the page's longest is 465 — and the heading pattern reads
a line once: it paired a lazy group with a trailing run of spaces, which
backtracked quadratically, and one heading line of spaces inside the size cap
held the parser for about seventeen minutes. A page that has changed shape is
refused rather than guessed at: `SnapshotRefused` for missing or repeated
markers, a line over the bound, an unknown heading, a line it cannot read, no
row kept, more than half the rows dropped, more than 20 under one heading or
more than 150 in all, each with a message of counts and line numbers that
carries none of the page's text, since it will become a job's error.
`test_web_sources.py::TestTheParser`, `::TestARefusedSnapshot`,
`::TestNoLineHoldsTheParser`, and `::TestTheParserUnderFuzz`, where 2,000
seeded mutations of the page raise nothing else.

**One normal form.** `normalise_excerpt` decodes HTML references and
Markdown's backslash escapes, applies NFKC, and removes control, format,
private-use, surrogate and unassigned characters and every other character the
code screen's `hidden_characters` names, by the same explicit ranges — so the
reserved default-ignorable code points, unassigned and therefore missed by a
removal by category, go too — reading whitespace, and the blank-glyph fillers a
renderer draws as a blank, as a space. It replaces a Markdown image or link
with its text, removes whole any token that is or holds an address — a scheme's
`://`, `www.`, a protocol-relative `//host`, an email, `mailto:`, `xmpp:`,
`javascript:`, `vbscript:`, a `data:` URI, or a host followed by a path — and
collapses whitespace. The removal reads each token once: the pattern it
replaces backtracked quadratically on a run with no space in it, and a title
NFKC expands and that never settles cost half a second, a page of them over a
minute. It is idempotent by construction rather than by the order of its steps:
one step can uncover work for another — removing a zero-width space can join
`&` to `lt;`, or `http:` to `//` — so the pass repeats until the text settles,
and text still changing after 16 passes, or longer than 2,000 characters as
given or once NFKC has expanded it, is no excerpt at all. It keeps HTML and
never truncates, both on purpose: a tag is the code screen's to find, and an
overlong excerpt is quarantined whole. `test_web_sources.py::TestTheNormaliser`,
whose seeded fuzz of hostile fragments holds idempotence, and that no address,
Markdown link, control, format, private-use, unassigned or hidden character,
or NUL survives; `::test_what_the_screen_calls_hidden_never_reaches_an_excerpt`
reads every default-ignorable code point Unicode lists, raw and by reference.

**The code screen, version 1.** `code_screen` returns the first of six rules a
text trips: `hidden_characters` (every default-ignorable code point Unicode
lists, plane 14's reserved block whole, every control and private-use
character, and the blank-glyph characters Unicode does not call ignorable — the
Braille blank, the Khitan filler, the musical null notehead — by explicit
ranges, so the rule is the same under any Unicode database, and checked against
Unicode's own list by `::test_hidden_characters_names_every_default_ignorable_code_point`),
`markup_in_cell`, `instruction_phrase`, `encoded_payload` (40 base64 or
base64url characters in a run, two runs of 16 split by whitespace, or 64 hex),
`mixed_script_word` (a Latin letter beside a letter of any other script or
block in one word, read after NFKC so a ligature or a fullwidth letter is the
Latin it stands for) and `overlong` (past the 300 characters a web state may
hold). `instruction_phrase` reads a skeleton of the text: marks dropped after
NFKD, 254 lookalike letters of other scripts and Latin letters no
decomposition reaches (`CONFUSABLES`, after Unicode's UTS #39) read as the
ASCII letter they are drawn like, before casefolding and after, and Markdown's
emphasis markers read as spaces; its keywords are bounded by the ASCII letters
around them, not by `\b`. So `__Ignore__`, `İgnore`, `Ignöre`, a dotless i, a
script g, and a Jev spelled in Cyrillic, Armenian, Coptic, Cherokee or Lisu
letters — each of which passed v1 as first written — are the plain words, and
a digit or another script's letter beside a keyword no longer hides it. Beside
the design's phrases it reads "ignore your instructions", "ignore the above",
"do not follow … instructions", "system prompt" however it is joined, a role
opening the text or a sentence, `human:` among the roles, and a dictated answer
("answer false", "respond with insufficient evidence"). The rules and how they
read are data (`CODE_SCREEN_RULES`, `SCREEN_READINGS`, `CONFUSABLES`,
`SKELETON_SPACES`), hashed by `code_screen_sha256`, pinned beside the rules by
`GOLDEN_CODE_SCREEN_SHA256`, and every released version's hash is pinned,
append-only, in `test_web_sources.py`, as the question sets' are: re-recording
the module's golden after a change, the edit a failing hash test invites, still
fails against the released history
(`::TestTheCodeScreen::test_changing_a_released_rule_with_its_golden_redone_is_refused`),
so "v1" names one rule set for as long as a row says it. v1's hash was
re-recorded once, in review, before any row could say v1. It is a keyword
baseline with false positives by design — a paper naming Claude Shannon is
quarantined — whose only cost is that Jev is not asked about that title; the
page's 61 titles trip none of it. Every pattern reads a bounded stretch or runs
once per word, so text as long as the normaliser produces is screened at once
(`::test_no_text_holds_the_screen`).

**What becomes of a row.** `screen_cell` screens a title as written in its
cell, normalises it, screens the excerpt, and decides: `keep`, `quarantine`
under the rule its excerpt trips, or `drop`. Quarantine is by content, one-way
and across sources (C6), and the design had ingest quarantine on a hit from the
cell or the excerpt. Review found the flaw in that: the decorations the
normaliser removes — a hidden character, an address — leave the clean title's
own words and so its own content address, so anyone who could decorate one row
could have a clean title quarantined everywhere. Only words that trip the
screen themselves are now quarantined; a row whose decoration alone tripped it
is dropped, counted and its rule named, and an excerpt that normalises to
nothing is dropped too, which closes open item 45. The rule lives here, pure
and tested, so the ingest job stores what it decides rather than deciding.
`test_web_sources.py::TestWhatBecomesOfARow`, whose seeded fuzz holds that a
quarantined excerpt trips the screen on its own; `::TestTheAdversarialCorpus`
pins each of 46 cases to its fate: dropped by the parser, dropped or quarantined
by a named rule, or the snapshot refused. `dataset_labeller` names the
README's grouping as a labeller, `source:pwb-readme@<sha12>`, from the distinct
pairs of heading label and excerpt, so it changes when a title moves between
headings and not when a figure moves; `content_sha256` is
`jev_hash.text_sha256`, the address migration 0013's CHECK files every
document under.

**The fetcher.** `web_fetch.fetch(source, *, session_factory=None)` fetches
once and returns `Fetched` — the text, the sha256 and size of the body, and
when it arrived — or `FetchFailure(kind, http_status)`, with neither body nor
exception text in either. Each control, and the test in
`tests/unit/test_web_fetch.py` that fails without it, over real local HTTPS
against a server with a certificate authority of its own
(`tests/fakes/web_server.py`):

| Control | Rule | Held by |
|---|---|---|
| Input | an `ALLOWED_SOURCES` entry, by identity, its rules checked again and its values compared with those `web_sources` recorded as it loaded, or `ValueError` before any session exists; the fetch uses the recorded values; no function takes a URL | `TestOnlyTheAllowListIsFetched` |
| Redirects | `GET` with `allow_redirects=False`; any 3xx is `redirect` and is never followed — not to a listener, a lookalike host or the metadata address | `TestNoRedirectIsFollowed` |
| Environment | `trust_env=False`: no proxy variable and no `.netrc` applies | `TestTheEnvironmentAppliesToNothing` |
| Addresses | `GlobalOnlyResolver` refuses the whole answer if any address in it is not global — loopback, private, link-local, multicast, reserved, or one of those carried inside an IPv6 address, whatever a release's tables say of the prefix — before any connection; aiohttp connects to exactly the addresses it returned, so nothing is looked up twice | `TestOnlyGlobalAddressesAreReached` |
| TLS | aiohttp's default, verified against the system's trust store. Nothing in `src/programme` passes `ssl`, `ssl_context`, `verify`, `verify_ssl`, `check_hostname` or `cert_reqs` anything but `True`, `None`, a default context or a keyword-only test seam, builds an `SSLContext` without `PROTOCOL_TLS_CLIENT`, sets a context's `check_hostname` or `verify_mode`, spreads arguments into a call that makes a connection, or names `CERT_NONE`, `CERT_OPTIONAL` or an unverified context. The scan first read only a literal `False`, and `verify=ssl.SSLContext()` planted in the Jev client passed every suite; the client is now also called with no transport, as production calls it, against a server nobody trusts | `TestTLSIsVerified`, `TestTLSIsNeverTurnedOff`, `tests/sdk/test_jev_client.py::TestTLSIsVerifiedWithNoTransport` |
| Headers | `User-Agent: trader-research/1`, `Accept: text/plain`, `Accept-Encoding: gzip`, each written out in the test rather than compared with the module's own table, which pinned nothing; a `DummyCookieJar`; no credential | `TestASuccess::test_the_request_is_fixed` |
| Size | a declared length over the cap refused before reading; the body counted as it arrives and again as it inflates, gzip inflated here a bounded amount at a time; a gzip stream that does not end with the body is `protocol` | `TestTheSizeIsCapped`, a gzip bomb of 64 times the cap among them |
| Type, encoding | one `Content-Type` the source allows, declaring `charset=utf-8`; no coding but gzip; strict UTF-8 | `TestTheTypeAndTheEncodingAreStrict` |
| Status | 200 only | `TestOnly200IsRead` |
| Time | 5 s to connect and 20 s in all, inside the programme's 35 s shutdown grace; one attempt, with aiohttp's own resend of an idempotent request after a dropped connection switched off | `TestTime` |
| Output | never raises for the network or the server; cancellation propagates; logs the status, the size and the hash, never the body | `TestTime::test_cancellation_propagates`, `TestNothingFetchedReachesALog` |
| Test seam | `session_factory`, and the session builder's `resolver` and `ssl_context`, which production never passes, read from `src/` by the scan that holds `jev_client`'s transport, generalised to take any seam | `TestTheSeam` |

Each control above was removed in turn and a test failed each time, and each
boundary scan below was run against an offence planted in the real tree; so
was each fix review asked for, twenty-nine mutations in all, each caught.

**Boundaries.** `web_fetch` joins `RUNNER_ONLY`, so neither the API nor
anything that can move money may load it, and CLAUDE.md's Safety rule 5 names
it; `test_import_boundaries.py::test_safety_rule_5_names_every_runner_only_module`
now holds that list to the tuple, so open item 11 cannot recur.
`::test_only_the_web_fetcher_imports_aiohttp_in_the_programme`;
`::test_no_programme_module_reaches_aiohttp_but_through_the_fetcher`, since the
first counted only names beginning `aiohttp`, and a module that took it from
`src.bankr_client`, or would from the fetcher itself, built a bare session with
every test green; `::test_nothing_imports_the_web_fetcher_yet`, which C6 is to
turn into "only the ingest job"; `::test_the_web_sources_reach_nothing_that_fetches_stores_or_asks`
and `::test_the_web_fetcher_reaches_no_model_no_database_and_no_runner`, each
walking its module's closure; `test_web_sources.py::test_web_sources_loads_nothing_heavy`,
in a fresh interpreter; and
`test_dependency_boundaries.py::test_the_web_fetcher_imports_only_what_the_programme_declares`,
which keeps `aiohttp` in what the programme's lock installs.

**Checked against the page, and nothing kept from it.** Every fixture is
synthetic: the repository publishes no licence, so the tests hold invented
titles in the README's shape, beside figures that are sentinels. The parser
was run once, read-only, against the page as it was served on 2026-09-27 —
90,734 bytes, sha256 `456caf19…` — and nothing from it was committed: 61 rows
under 7 headings (12, 12, 3, 4, 8, 10 and 12), none dropped, no code-screen
hit on any cell or excerpt, no title under two headings, the longest excerpt
137 characters, one title changed by normalising (a doubled space), and the
labeller `source:pwb-readme@6d424588c995`, the value the design computed from
the same page. Fetched once more on 2026-09-28, read-only, it was byte for byte
the same page, and read after review's changes it gives the same 61 rows, every
one kept by `screen_cell`, and the same labeller; its block holds blank lines,
the seven headings, their tables and the one italic note, so the stricter
reading refuses nothing on it.

**Where C5 departs from the design.** Markdown's backslash escapes are
decoded, which the design's steps left out: a literal pipe in a table cell must
be written `\|`, and without the step an excerpt would not be the title as it
reads, and the same words from another source would be another subject.
Idempotence comes from repeated passes, bounded, rather than from the order of
the steps. The normaliser removes more than the design's categories — every
character the screen calls hidden and every unassigned code point — reads the
blank-glyph fillers as spaces, removes every address form a renderer links or a
browser acts on rather than only a `://` or `www.`, and gives up on text past
2,000 characters. `hidden_characters` covers every default-ignorable code point
rather than the design's five kinds, and the blank glyphs beside them.
`instruction_phrase` reads a skeleton rather than the NFKC casefold, adds the
prototype's variants and review's phrasings to the design's, asks for an
article in "you are … an AI" so that a title like "You Are What You Trade"
passes, and leaves out the prototype's `llm` as a name, which the design did
not list and a paper's title may name. `mixed_script_word` compares Latin with
any other script, not Cyrillic and Greek alone, and base64url and whitespace-split
base64 are payloads too. A decision the design left to C6 is made here:
`screen_cell` quarantines only words that trip the screen, where the design
quarantined on a hit from the cell as well. The limit under a heading counts
the rows under each heading line rather than each label, since seven labels at
20 would leave the limit of 150 unreachable. A heading of any level inside the
block must be a known level-two one, and every other line blank, a row, or the
note. `FetchFailure` carries the HTTP status beside its kind, and `Fetched`
keeps its text out of its `repr`. gzip is inflated by the fetcher rather than
by aiohttp, so that no more than the cap is ever held; a coding other than gzip
is refused as `content_encoding`. aiohttp's resend after a dropped connection,
a second attempt the design's "no retry" did not see, is switched off. The
address check also refuses multicast, reserved and unspecified addresses, and
an IPv6 address for the IPv4 one it carries. The session builder's two test
parameters are seams as well, and the transport-seam scan was generalised to
take them rather than copied. The fetcher compares the entry with what
`web_sources` recorded, not only its identity and rules, so an entry edited in
place to any page is refused. The code screen's rule set is pinned by its hash
now, beside the rules and in a released history, not first by C7's analysis
plan. `web_fetch` imports `aiohttp` at module level, since it is installed
everywhere, and names aiohttp's threaded resolver, so installing `aiodns` would
change nothing.

#### C4: the forward clock starts

The first pull request that can make a call nobody queued by hand, and it is
dark: every switch it reads is seeded off, so nothing is planned, claimed or
asked until an operator turns the programme and Jev on
(`tests/integration/test_jev_dark.py` runs the shipped loop for several passes
at the seeds, with a key available, and finds no job, no request and no Jev
row). What it adds: the planner, the `jev_regime` job that records
`decision.regime` v1 every session and consumes nothing, a daily connectivity
probe, flip re-asks, the pre-registered analysis plan with the regime's
baseline rule, the harness's three read-only commands, the daily report's data
health on the traded universe, and restart schedules moved clear of the close.

**The clock's times are the worker's.** `jev_clock` holds them: the reference
bars at a session's close plus 45 minutes, `scheduler.INGEST_AFTER_CLOSE`; the
collection at plus 50; the cutoff at plus 60, `scheduler.DECIDE_AFTER_CLOSE`,
the moment the live decision is planned, so a signal counts as live exactly
when it could have been read by that session's decision. Each is read off the
calendar, early closes and daylight saving included, and the cutoff always
falls on the session's New York day, as the schema's CHECK requires.
`sessions_to_plan` is today's session while its cutoff is ahead and the next
session, never a past one and nothing past the calendar's reach, so the planner
builds no backlog. The bar loader reads `adj_close` and nothing else, from
`REFERENCE_SOURCE` alone, over `REFERENCE_WINDOW_DAYS` up to the session, and
cuts the panel at the session; `test_daily_bars_readers.py` names it among the
table's readers. The instruments are recorded once, in the signal's symbol
(`equities=SPY;bonds=IEF;commodities=GSG`), since the state holds no ticker.
`tests/unit/test_jev_clock.py::TestTheTimes`, `::TestSessionsToPlan` and
`::TestTheNames`; `tests/unit/test_jev_forward.py::TestTheLoader`.

**The forward clock never backfills and never writes a missing row.**
`jev_forward.collect` is the `jev_regime` handler. A payload that names no
session the calendar holds, or another set, fails without a retry; a version
that is no longer registered completes `superseded`; a session already
recorded completes `recorded_before`. Then the database's clock: at or past
the cutoff, nothing is asked, the job fails for good, and its error says when
the clock read and quotes the reason the attempt before the cutoff met, from
the job's own row, since that reason and not the clock is why the session is
absent. Before the cutoff, whatever can still change fails the job for a
retry and writes nothing: the decisions area off; a sleeve the live ingest
owns whose `ingest_bars:{S}` has not succeeded (below); no bar stored; or no
state, with `jev_features.regime_state_problem`'s reason — the first check
`regime_state` would fail, named with its sleeve and symbol, in the same order,
and held to agree with it on every case that returns `None`. The clock is read
again after the bars have loaded and before the one ask, which goes through
`jev_lane.ask` looked up on the module with every keyword spelled. An `ok` or
`invalid` ask is recorded; anything else fails the job as `ask_verdict` says.
Twenty attempts back off `attempts × 10 s`, about 32 minutes, so retries
outlast the ten-minute window and the first after the cutoff ends the job.
The result holds labels, counts and ids, never a state or a price. Phase B's
docstring promised a `missing` row for an unmeasured session; nothing built it,
and a `missing` row, once written, would be final and bar the measurement a
bar landing two minutes later made possible, so the docstring now says what is
built. `tests/unit/test_jev_forward.py`, every row of the state machine,
`::TestItNeverBackfills` and `::TestOneAskPerJob` among them.

**A live-owned sleeve waits for the live ingest** (open item 40, closed here).
When an enabled operator deployment trades a sleeve's instrument, the live
ingest owns it, and its history is on one adjustment basis only once
`ingest_bars:{S}` has succeeded. Until then the session is treated as a
missing close: retried until the cutoff, then absent, the error naming the
sleeve, the job and its state, the ingest's own error quoted. The programme may
not import the worker, so it reads the traded universe again,
`repo.traded_universe`, by the worker's rule — enabled, the operator's, each
strategy built from its stored parameters and asked for its universe — and a
deployment it cannot build makes every sleeve possibly the live ingest's.
Owned now is not owned when the ingest ran, as C4's review found: an attempt
that failed its span refetch while a deployment traded a sleeve still wrote
that sleeve's ten-day window, and if the deployment is disabled before the
regime job runs, the sleeve reads as nobody's, a later attempt that succeeds no
longer fetches it, and the reference job for S, run while the live ingest
owned it, left it alone — the first cut measured such a session over the
stitched history. So once an attempt of `ingest_bars:{S}` has not succeeded,
or is still running, a sleeve nobody trades now is read only if the reference
job for S re-based it whole, its result naming it among those it upserted;
otherwise the session waits, the error naming the sleeve and both jobs.
`tests/integration/test_jev_forward.py::TestTheTradedUniverseIsTheWorkers`
holds the two readings to one answer on the same rows, and
`::TestALiveOwnedSleeveWaitsForTheLiveIngest` waits through an unplanned and a
failed ingest on Postgres and asks once it has succeeded, and waits for a
sleeve disabled after a failed attempt through a retry that fetched nothing;
`tests/unit/test_jev_forward.py::TestASleeveTheLiveIngestHeldWhenItFailedWaitsToo`
holds each case.

**A signal rests on its answer, once.** `jev_lane.record_signal` is the one
`INSERT INTO jev_signals` in `src/`. It refuses, writing nothing, a set that is
not the registered one or not of the decision lane and internal provenance, a
question the set does not ask, an ask that recorded no response, a session
that is not a date and a cutoff without a timezone — both of which asyncpg
would store without a word, the one under the next day, the other four hours
early (tests for both added in C4's review) — and a request row that is
another set's, another version's, a probe's or one that recorded no response.
Status and value come from the answer read back by its question
key (`signal_outcome`: a valid answer is measured unless it is the escape; the
escape, a tie and a choice that is not its own argmax abstain; every other
invalid answer is invalid). Lane, provenance, pack and model are copied from
the request row, never taken from the caller, and the database stamps
`available_at` and derives `backfilled`. `ON CONFLICT DO NOTHING`; a session
already recorded is read back through `jev_repo.get_signal`, so inside the
programme the lane writes the signals and reads none, and `jev_repo` reads
them and writes none. Two sessions in one state rest on one answer, and
`answer_id → request → state` gives every session's exact state.
`tests/unit/test_jev_lane.py::TestSignalOutcome`, `::TestRecordSignalRefuses`
and `::TestTheSignalIsItsAnswers`; on Postgres,
`tests/integration/test_jev_forward.py::TestEveryStatusPassesTheRealTrigger`,
`::TestASignalIsWrittenOnce`, `::TestLateIsTheDatabasesWord` and
`::TestAReplayedSessionRestsOnTheFirstAnswer`; over real HTTP,
`tests/sdk/test_jev_forward_over_http.py`.

**The planner plans only what its switches allow.** `jev_plan.plan` runs in
the programme's Jev loop before each drain, at most once a minute
(`JEV_PLAN_SECONDS`), on a connection of its own and inside a `try` of its
own, so a planner that fails costs a minute of planning and never a drain;
`_drain_jev` and its one claim are unchanged. It is told whether a TypeSafe
key exists, never the key. It plans nothing without a key, and nothing unless
`programme_enabled`, `jev_enabled` and a usable `jev_model` hold, each through
its own fail-closed reader; each rule then needs its area. It enqueues through
`job_repo.enqueue` with literal kinds and nothing else, under dedupe keys that
hold across statuses, so planning again adds nothing:

| Rule | Area | Kind | When | Key | Priority / attempts |
|---|---|---|---|---|---|
| Daily probe | the master switch | `jev_probe` | now | `jev_probe:{UTC date}` | 40 / 3 |
| Reference bars | decisions | `ingest_reference_bars` (the worker's) | close + 45 min | `ingest_reference_bars:{S}` | `REFERENCE_PRIORITY` (1) / 14 |
| Regime | decisions | `jev_regime` | close + 50 min | `jev_regime:decision.regime@1:{S}` | 50 / 20 |
| Re-asks | the set's own | `jev_reask` | 24 h after the answer | `jev_reask:{request id}` | −10 / 3 |

A job that makes a call is planned only while its lane's share of the day's
budget has a call left once the day's calls and the jobs already waiting are
counted, and each job planned in a pass takes its call from what is left, so
one call left plans one session and not two
(`tests/unit/test_jev_plan.py::TestTheForwardClock::test_one_call_left_plans_one_session_not_two`);
a job that has finished is history, not a call coming, and never counts
against a share (`tests/integration/test_jev_repo.py::TestPendingJobs` and
`::TestThePlannerOnAQueueWithHistory`, on Postgres, where the planner's own
reads run: the unit rig fakes them). The daily probe closes open item 18: it
proves the key, the pin and the validator each day, and its `p(true)` is a
series the harness reports. The
reference job's attempts close open item 39: `attempts_spanning` finds the
fewest attempts whose backoff reaches the cutoff from the minute the bars
settle, fifteen minutes, which is 14. `tests/unit/test_jev_plan.py`: the whole
switch matrix, the key read before any switch, the probe once per UTC day, no
backlog, the calendar's end, the shares, and the re-ask sample;
`tests/integration/test_jev_dark.py`: each switch alone and every pair but one
plan and send nothing, the programme and Jev together plan and send exactly
the daily probe, and with the decisions area the clock's jobs are planned;
`tests/unit/test_job_ownership.py::TestThePlannerStep`. The planner asks
nothing itself: its import closure reaches no lane, client, handler that asks,
model runner, vault or decryption, so every call goes through the job loop's
claim, its one-call count and its shutdown grace
(`test_import_boundaries.py::test_the_planner_reaches_no_road_to_a_model_and_no_key`,
added in C4's review; the design required it and the first cut tested only
the harness's closure).

**Re-asks measure the noise.** The sample is pre-registered
(`jev_prereg.reask_sample`): the previous UTC day's canonical requests, the
uniform stratum by the request hash (`int(hash[:8], 16) % 20 == 0`), then the
low-margin stratum (any valid answer leading by less than 0.20), each in hash
order, at most ten a day and never beyond the probe lane's share, less any
whose set was reworded, whose model is not the pin, whose area is off or whose
text is quarantined. The ten are the day's, not a pass's: the re-asks already
queued for the day's answers count against them, so an area switched on or a
pin changed during the day cannot draw a second sample from the answers the
first left out, as C4's review found it could
(`tests/unit/test_jev_plan.py::TestTheReasks::test_the_cap_is_the_days_whatever_becomes_eligible`).
Each re-ask's payload records the stratum and the plan it was sampled under,
which the harness reads and the handler does not.
`jev_jobs.run_reask` asks the canonical row's exact state,
rebuilt through the set's own model, about its own subject and instant, once,
as a probe: recorded in the probe lane, never replayed and never canonical. It
completes `superseded`, asking nothing, when the words or the pin have changed,
since an answer to other words or from another judge measures nothing about
this one; no usable pin is not another pin, and fails the job through the
road's own refusal. It reports, per question, whether the argmax moved, and
`None` where either answer was not measured. `tests/unit/test_jev_jobs.py`.

**A job's verdict is its status.** `ask_verdict` gives every Jev ask the
probe's rule: an answer succeeds; a response refused whole fails for good, since
asking again would buy a second answer rather than check the first; a failed
call is retried only for no response, a rate limit or a vendor fault; a switch
turned off mid-job waits for the switch; every other status fails for good with
a reason of its own. `JobFailedError` moved to `job_errors`, beside the one set
of retried kinds, so the handlers outside `main` can raise it; `main`
re-exports it. `tests/unit/test_jev_jobs.py::TestAskVerdict`;
`tests/unit/test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall` runs
every handler through every status the road can return and every error kind,
counting asks, and reads each handler's module for a call to the road inside a
loop or a second call site.

**The analysis is registered before the answers.** `jev_prereg` is data and
pure functions, the standard library alone: the development and test split by
content, the size floors, the margin grid, each lane's target, the confidence
levels (95% two-sided to report, 99.5% one-sided to gate, Bonferroni over up to
ten set-and-question pairs), the bootstrap and its seed rule, the calibration
bins, the flip limits, the re-ask sample and the regime's baseline rule.
`plan_hash()` is sha256 of the whole as compact JSON with mappings' keys
sorted; `GOLDEN_PLAN_HASH` pins it beside the plan, and
`tests/unit/test_jev_prereg.py` holds both to `RELEASED_PLAN_HASHES`, an
append-only history kept in the test, so re-recording the golden after an edit
still fails. Every constant is in the hash — the test moves each and watches it
change — and the split, the strata and the rule are checked against copies
written in the test with their numbers as literals. Every lane's target is
met by the Wilson lower bound of its statistic, one-sided at the gate level,
never by a point estimate: the first cut registered the research lane's as a
bare 0.80, which 24 of the 30 covered items a threshold needs would have met
with a lower bound of 0.57, against the design's metric definition; C4's review
added the bound and re-pinned version 1 before the plan merged or any answer
existed (`tests/unit/test_jev_prereg.py::TestTheLaneTargets`). Plan version 1
hashes to `f744c2d88bded050e7b1b0fb946c9e29b502264d55ee6ac7c6a68b182daf7caf`.

**The regime's baseline and the sleeves are the agent's defaults.**
`REGIME_BASELINE_RULE` reads the equities sleeve alone: `risk_off` when its
trend is below, its momentum down and either its drawdown deep or severe or its
volatility in the top quintile; `risk_on` when its trend is above, its momentum
up, its drawdown none or shallow and its volatility in the lower three
quintiles; `neutral` otherwise. It is total over all 180 equities states and
never answers the escape, and it reads only fields and labels of the regime
state (`test_the_baseline_rule_is_total_and_never_abstains`,
`test_the_rule_reads_only_state_labels`). The sleeves, SPY, IEF and GSG, are
`src/data/reference.py`'s, held equal to the plan's copy. **Neither the rule nor
the sleeves is a choice the operator has reviewed: both are the defaults the
agent that built C4 chose.** Before the first regime answer exists — the
decisions area is seeded off, so none does — a change to either is a new
`PLAN_VERSION` with its hash appended, and costs nothing; a changed sleeve also
changes `src/data/reference.py` and starts a new signal series, since the
signal's symbol names the instruments. After it, the same bump, recorded as a
change of plan: the regime job writes the plan in force into its result as it
asks and the planner writes it into each re-ask's payload, so `forward` scores
agreement only over answers first recorded under the plan it runs and counts
the rest apart by the plan they were recorded under, and a flip rate counts
only the pairs sampled under it; the report names its plan, no answer is
scored by a rule registered after it, and the old rule is never rewritten to
match. The first cut said all this and built none of it.

**The harness reads, and holds no key.** `python -m src.programme.jev_eval`
runs `status`, `forward` and `forward-audit`, each in one read-only,
repeatable-read transaction on `DATABASE_URL`, the one variable it reads. Its
import closure reaches no lane, no client, no model runner, neither handler
that asks, and neither the vault nor the decryption
(`test_import_boundaries.py::test_the_harness_holds_no_key_and_reaches_no_client`).
`forward` accounts for every session since the first job of the registered
set's version whose cutoff has passed — a version bump starts a series of its
own, rather than counting every session since the old version's first job as
absent — as live measured, abstain or invalid, late (the database's
`backfilled`), or absent with its job's error or "not planned". Absent
sessions stay in the denominator of coverage; a late row is never live. Each
figure is quoted as the design's section 10.3 says it may be. Coverage carries
a Wilson interval (`jev_stats`), and so does each stratum's flip rate, each
pair a request of its own, with its n and median lag, never pooled. The share
served by a replay, the regimes' shares and agreement with the baseline rule
over sessions are counted, with the distinct states they rest on beside them,
and carry no interval: every session in one state replays one answer, so an
interval over sessions narrows with how often one judgement repeats, and the
first cut quoted a lower bound of 0.84 for twenty sessions resting on a single
answer. Agreement over distinct states, each one judgement, carries the
interval. Each model's answers are reported apart and named, since a
signal's name holds its set and version but not the model, and the first cut
pooled two pins' answers and kept only the first model's judgement of a
state. And each answer is scored under the plan that registered it: the
regime job writes the plan in force into its result when it asks, agreement
is scored only over answers first recorded under the plan the report runs, a
replay under the plan its answer was asked under, and the rest are counted by
the plan they were recorded under; the planner writes the stratum and the plan
into each re-ask's payload, and a flip rate counts a pair only in the stratum
it was sampled in and only under that plan. A re-ask refused whole, failed or
refused before it was sent is a pair that could not be compared, counted as
such (`jev_repo.probe_pairs` once joined only answered re-asks). The daily
probe's series closes it. Its field list is pinned by
`tests/unit/test_jev_eval.py`, which refuses a return, a P&L or a hit rate by
any name. A figure over nothing is `None`, printed as "not measured", and a
genuine zero prints as zero. `tests/integration/test_jev_harness.py` builds
all three reports on PostgreSQL from rows the planner, the forward job through
the programme's drain, the re-ask job and the daily probe wrote, with a late
session and an expired job among them, and `tests/integration/test_jev_repo.py`
holds each read beneath them to what it counts; the first cut ran none of
them on a database. `forward-audit` rebuilds each recorded state
from the bars stored now, with the sleeves the signal's symbol names, and says
agree, drift with the descriptors that moved, or why it cannot rebuild. A
re-basing cannot cause drift, since every descriptor is invariant under it, so
drift is data trouble in the history the answer was computed on (open item
48).
`jev_stats.wilson` returns exactly 0 at 0 of n and exactly 1 at n of n, where
the float formula left a residue that put the bound on the wrong side of its
own estimate; its test found it.

**No Jev output reaches a generative model's prompt** (invariant I8). The
model runners — `client`, `author`, `panel` and `tick` — name no Jev table
(`test_jev_table_boundaries.py::test_the_model_runners_name_no_jev_table`),
and, since a runner could read the ledger through `jev_repo`'s functions
without naming one, their whole import closures load no `jev_*` or `web_*`
module but `jev_catalogue`, the pin and vocabulary `flags` reads to answer a
Jev switch, which itself loads none
(`test_import_boundaries.py::test_no_model_runner_loads_a_jev_or_web_module`,
added in C4's review: the first cut's name scan alone let `tick` import
`jev_repo` with every test green).

**The daily report's data health reads the traded universe** (open item 38,
closed here). The latest session is the stalest traded symbol's newest, read
with `repo.traded_universe`; a universe that cannot be read, a traded symbol
with no bar, or nothing traded at all leaves it absent with a note saying which,
and the required actions name the first two. The row and symbol counts are
still the whole table's. The report page's absent latest session says why in
the same terms (`web/src/app/programme/report/page.tsx`).
`tests/unit/test_report_data_health.py` builds the case the item names: the
reference sleeves current and a traded symbol ten sessions behind.

**Restarts moved clear of the close** (the review's schedule change). Both
long-running workflows stopped each run after a fixed 5h45m while their crons
fired every five hours — `programme.yml` at `"30 */5 * * *"`, `worker.yml` at
`"0 */5 * * *"` — so a successor was always queued, each restart came 5h45m
after the last, and the restarts drifted 45 minutes a run round the clock:
every few days one landed between 20:30 and 22:15 UTC, where the live ingest
and the reference bars (close + 45), the collection (+ 50), the cutoff and the
live decision (+ 60) and the marks (+ 75) sit in both regimes of daylight
saving, and the programme's own cron fired at 20:30. Now each run stops at the
next of five slots — 02:30, 07:30, 12:30, 17:00 and 22:30 UTC — at least ten
minutes away and never later than 5h45m; the slots are at most 5h30m apart, so
a run always reaches one, and the process restarts at a slot and nowhere else.

The first cut of this fired the crons at the slots themselves, and the
review of C4 found what that cost: a trigger at the moment a run stops finds
nothing running to queue behind, so no successor was ever waiting, and every
restart lasted as long as GitHub was late with the event — late most at the
top of the hour, where `"0 17 * * *"` fired, and under load not at all. A
17:00 event lost on a summer half day, which closes at 17:00 UTC, would have
left neither process running from 17:00 to 22:30, through that day's ingest,
collection, cutoff, decision and marks. So each slot now has two triggers,
neither at the slot nor on the hour: 41 minutes before it
(`"49 1,6,11,21 * * *"`, `"19 16 * * *"`), while the run that stops there
still runs, so its successor waits pending in the `concurrency` group and
starts as it exits; and 3 minutes after it (`"33 2,7,12,22 * * *"`,
`"3 17 * * *"`), which ordinarily waits pending behind the successor until the
next slot's earlier trigger replaces it — five runs a day end "cancelled", by
design — stands in when that trigger is late past its slot or lost, and starts
the chain again when nothing is running at all. A restart is then the minutes
a runner takes to start, not a wait on the schedule. The review also suggested
a lone early trigger with runs skipping any slot closer than its lead; that
was not taken, because a run started cold by the early trigger would then
reach past the next slot, and across the 5h30m gap from 17:00 to 22:30 past
the 5h45m cap, stopping off the slots at about 22:00 — inside the winter
evening's working hours. The step works out today's UTC midnight as `now` less
its remainder of a day, since Unix time counts no leap seconds, so it no longer
depends on GNU `date` to parse one.

`tests/unit/test_jev_clock.py` holds it. `::TestTheRunsStopAtTheSlots` runs the
step's own lines under bash for a run starting at every minute of a day, in
four time zones and across both changes of the clocks, and each must stop at a
slot ten minutes to 5h45m ahead, where the Python model says.
`::TestASuccessorIsQueuedBeforeEveryStop` models GitHub's schedule and the
concurrency group from nothing running: with every event late by up to two
hours, each late by its own draw up to an hour, any one event of three days
lost with the rest up to 40 minutes late, and a cold start every seven
minutes round the clock, every stop after the first day finds its successor
queued and the process back within fifteen minutes; no trigger fires on the
hour. The fixed cron-equals-slot test it replaces enforced the defect.
`::TestTheRestartsLandOutsideTheWorkingHours` holds every slot, with those
fifteen minutes, outside every session's working hours — around the open and
from a quarter of an hour before the ingest to the marks — for every session
from 2007-03-12, the first under the daylight-saving rules in force, to the
calendar's end, so each kind of day those rules produce is checked, the summer
half days that close at 17:00 UTC among them (open item 50).

**Where C4 departs from the design.** The loader selects `adj_close` alone
rather than every price column, so no raw price can reach a state, and takes
the sleeves' symbols as an argument, so the audit reads a series with its own.
The handler reads the clock a second time before the one ask, quotes the last
pre-cutoff reason in its `expired` error, refuses a payload naming another
set, and waits for the live ingest (open item 40, which the task added).
`record_signal` also refuses an unregistered copy of a set, an unknown
question, a request of another lane, a session that is not a date and a naive
cutoff. The reference job gets 14 attempts where the design had 3 (open item
39). The planner counts the jobs already waiting against a lane's share, as
well as the calls made, for the probe and the regime as for the re-asks, and
reads the key before any switch. A re-ask with no usable pin fails through the
road rather than completing `superseded`. `GOLDEN_PLAN_HASH` sits in the module
beside the plan, as `GOLDEN_PACK_HASHES` does for the words, and `job_errors`
is in the pure-module check beside `jev_hash`, `jev_prereg` and `jev_stats`.
Each harness command takes `--json`, and the harness closure also excludes the
vault and `src.crypto`. The dark test's matrix: the design said each switch
alone and in pairs sends nothing, which its own daily-probe rule contradicts
for the programme and Jev together; the test holds that pair to exactly the
probe. Additions: `jev_repo.get_signal`, `probe_series`, `pending_jobs` and
`first_job_session` beside the design's five reads; `jev_stats`' exact ends;
the daily report on the traded universe (open item 38) with its page's
reason; `tests/fakes/reference_prices.py` for the tests that drive the clock
on a database; and the restart schedules. C4's review added two more: the
regime job's result names the analysis plan in force, and a re-ask's payload
the stratum and the plan it was sampled under — the design's payload was the
request id alone, which is still all the handler reads — so the harness can
keep each figure to the plan that registered it.

#### C6: web ingest, calling nothing

The job that takes C5's road: `src/programme/web_ingest.py`, the
`jev_web_ingest` job, fetches the one allow-listed page, reads its titles,
screens them, stores them, and asks nothing. It is dark twice over: the
planner plans it only while the programme, Jev, a usable pin, a key and the
research area all allow it, and the research area is seeded off; and nothing
reads what it stores until C7's injection screen, the first set to be asked
about web text. No page has been fetched: the switches are off, and this
environment's only way out is a proxy the fetcher ignores (open item 41).

**What each attempt does.** In order, the first that applies deciding. A
payload that is anything but `{"source": <a name on the allow-list>}` —
another key beside it, a URL, a name not on the list — is refused before a
switch is read, since the page fetched is the allow-list's entry and never one
a payload names. The programme's switch and the research area are read again,
each through its own fail-closed reader, the area's reading Jev's master
switch too; either off, nothing is fetched. The pin is read again too, by
`flags.jev_model`, and, in `main`'s wrapper before `run_job` is called at all,
whether a key is set, by the road's own test, a blank key being none: the
planner plans the job only under both (design R28, a page fetched for a lane
that cannot ask about it being a fetch for nothing), and a job it queued can
be claimed after either went (open item 53), so without them the job fails for
good, as the probe does, and fetches nothing. The first cut read neither, and
C6's review found such a job fetching the page and storing eight documents
with no key and with an alias where the pin was; the key still goes no further
than the wrapper (`tests/unit/test_web_ingest.py::TestThePin`,
`tests/unit/test_job_ownership.py::TestTheProgrammeRunsWhatItClaims::test_the_ingest_job_is_not_run_without_a_key`,
`tests/integration/test_jev_dark.py::TestAJobQueuedBeforeTheKeyOrThePinWentFetchesNothing`).
A connection inside a transaction is refused, so that no transaction is held
open across up to 20 seconds on the network; the programme's loop hands a
handler a pooled connection with none open, and
`tests/integration/test_web_ingest.py::TestTheFetchIsOutsideAnyTransaction`
watches `pg_stat_activity` from another connection while the page is in flight
and finds no backend of the database in a transaction. Then
`web_fetch.fetch(ALLOWED_SOURCES[name])`, looked up on the module so a test
can stand in for it; a `FetchFailure` fails the job, its error the source's
name, the failure's kind and its HTTP status, and nothing else. The source's
parser from `web_sources.PARSERS` reads the page; a `SnapshotRefused` fails
the job as "the parser needs review", with the refusal's reason, which is
counts and line numbers the parser wrote. None of these is retried: each would
come to the same thing again that day, and the next UTC day's job fetches the
page afresh. Only a failure while storing is retried, and it is reported by
its class, SQLSTATE and constraint alone, because a driver's message can quote
the value it could not take: asyncpg's `DataError` repeats the argument, a
title among them, and
`::TestTheSnapshotIsOneWrite::test_a_failure_part_way_leaves_nothing_stored`
provokes exactly that. Nothing is written before the store, and the store is
one transaction, so a failed job leaves the table as it found it.
`tests/unit/test_web_ingest.py` holds each step against fakes.

**What is stored.** Each row the parser kept is decided by
`web_sources.screen_cell`, and the job stores what it decides: `keep`, the
excerpt in use; `quarantine`, the excerpt quarantined for
`quarantine_reason(rule)`; `drop`, nothing, counted under its rule, or
`empty` for a row whose excerpt normalised to nothing. The same excerpt twice
in one snapshot, under two headings, is one document. A document holds the
text in `excerpt` and nowhere else: `jev_repo.insert_documents` writes
`title` and `published_at` NULL by the statement, whatever a caller would
have passed; `url` is the allow-listed URL as `web_sources` wrote it;
`content_sha256` is `web_sources.content_sha256` of the excerpt, which is
`jev_hash.text_sha256`, the address `jev_lane.ask` recomputes for a
`web_excerpt` subject — `TestAFirstIngest::test_the_address_is_the_one_the_lane_asks_by`
asks the lane about each stored excerpt by its stored address, which it
accepts, and its web gate refuses the quarantined one as quarantined. And
`fetched_at` is the database's clock as the storing transaction begins,
`now()`, not the fetcher's stamp: the ledger's other stamps are the
database's, a writer's clock can run early, and later is the safe direction;
the transaction begins once the page has arrived, so the stamp is never
earlier than the fetch, and it is one value for every row of a snapshot.
`insert_documents` is `ON CONFLICT (source, content_sha256) DO NOTHING`,
which fires no update trigger, so a page read again stores nothing
(`TestASecondIngest`), and a title that changed is a new snapshot, the old
document kept as it was read. What it hands back is `(id, content_sha256,
inserted)` for each row in the order given, a row already stored under the id
it was stored under and `inserted` false, which C7's labels are to key by
(`tests/integration/test_jev_repo.py::TestTheDocumentWriter`, added in C6's
review, which found no test of that half of the contract, nor any call of
`get_document`). The job returns counts and hashes only —
`source`, `bytes`, `sha256`, `rows` (kept by the parser), `unparsed` (rows the
parser could not read), `distinct` (distinct excerpts among the rows not
dropped), `new`, `dropped` by rule, `quarantined_by_code` and
`quarantined_earlier` (distinct excerpts of the snapshot) and
`quarantined_now` (documents already stored that it quarantined) — and logs
the same.

**Quarantine is by content, one-way and across sources.**
`jev_repo.quarantine_content` is the only update of `web_documents` in
`src/`, and `jev_repo` the only module that writes the table
(`tests/unit/test_jev_table_boundaries.py::test_only_the_repo_writes_web_documents`
and `::test_the_one_update_of_web_documents_is_quarantine_content`). The
writes are read by the scanner that holds `daily_bars` to the worker,
`test_import_boundaries._table_writes`, with the table as its argument:
literals, f-strings — a literal interpolated read as its text — and statements
assembled by `+` or `str.join`, read whole; an insert, an update, a delete, a
copy, a truncate, a merge, a drop or an alter of the table, and the bare name
a bulk writer takes; an insert that goes on `ON CONFLICT … DO UPDATE` as an
update too, since it rewrites the row it meets; and a write whose table the
scan cannot read — interpolated, formatted, a verb whose table is joined on
from elsewhere, a bulk writer handed a name — as a write of this one, since it
could be. Each spelling is proved to trip it, what is not a write is proved
not to, and the function each write is in is read from the tree around it.
The first cut read each literal on its own, and C6's review assembled a second
quarantine in `jev_jobs`, a release in the API and an insert in the worker by
`+`, and turned `insert_documents`' `DO NOTHING` into a `DO UPDATE` that
quarantined, each with every test green; each now fails a rule, and the
`jev_signals` scan, which predates C6 and read literals the same way, reads
through the same scanner. It reads spellings, and is not a sandbox.

`quarantine_content` quarantines every document holding exactly that content,
under any source, that is not quarantined already, which is also what makes a
concurrent second call harmless: under READ COMMITTED it waits on the first's
row locks, reads the rows again once the first commits, finds them
quarantined, updates nothing and raises nothing
(`TestQuarantineIsOneWay::test_two_concurrent_quarantines_raise_nothing`,
which holds the second on the first's lock and watches it wait). Migration
0012's trigger refuses a release, a new reason for a quarantined document and
an edit of its text, and the document reads as it was
(`::test_a_release_is_refused_by_the_trigger`). The ingest applies it three
ways (`TestQuarantineIsByContent`): an excerpt the screen quarantines is
stored quarantined and quarantined wherever else it is stored; an excerpt the
screen passes that any document of any source holds quarantined is stored
quarantined for `content quarantined earlier (document N)`, N the earliest
such document, read in one query by `jev_repo.earliest_quarantined`; and a
stored document the screen now flags — a rule added since it was stored — or
whose content another document holds quarantined is quarantined when the page
is read again.

Two writers at once take their locks in one order. An insert holds its key in
the unique index until it commits, and waits on another writer's uncommitted
insert of the same key; a quarantine holds every row of its content. As first
built, the job wrote a snapshot's documents in page order and its quarantines
in page order, the screen's before the earlier ones, so two ingests at once —
yesterday's job left queued beside today's (open item 53), or two versions of
the page listing the same titles in different orders — each held what the
other waited for, and PostgreSQL ended one with a deadlock (SQLSTATE 40P01),
failing that attempt: ten rounds of ten in C6's review. Nothing partial was
stored, since the loser rolled back whole, but the attempt, a second fetch and
an error on the jobs page were spent. Now `insert_documents` writes a batch in
the unique index's order, `(source, content_sha256)`, and hands its tuples
back in the order given, and the job makes its quarantines, the screen's and
the earlier ones together, in one pass in content order: each writer waits
only on a key or a content below every one it holds, so none waits on another
that waits on it. `TestTwoWritersAtOnce` holds another writer, which takes its
locks in content order, at a known point beside the job and shows each order
— the documents, the screen's quarantines, and the screen's with the earlier
ones in one order — rather than racing for them; with the first cut's orders
each ends in the deadlock. A job's documents are therefore numbered in content
order, not the page's.

**It asks nothing, and no key reaches it.** `main` registers
`jev_web_ingest` through `_jev_web_ingest`, which has the signature every Jev
handler has and drops the key the loop resolves before calling
`web_ingest.run_job(conn, payload)`, which has no parameter to take one; the
wrapper is marked as wrapping `run_job` and nothing else of it copied, so the
one-call scans, which unwrap each handler, read `web_ingest`, where the work
is (`tests/unit/test_job_ownership.py::TestTheProgrammeRunsWhatItClaims::test_the_ingest_job_is_handed_no_key`,
through the drain with a key in the vault and another in the environment).
`TestEveryJevHandlerMakesAtMostOneCall` now holds each kind to its own count,
one for the three that ask and none for this one, whose run through every
outcome of the road must reach its end so that none is a count and not a
handler that stopped early; its module holds no call to the road at all.
`web_ingest` joins `RUNNER_ONLY`, and Safety rule 5 in CLAUDE.md names it;
its closure reaches no lane, client, model runner, vault or decryption
(`test_import_boundaries.py::test_the_ingest_job_reaches_no_model_and_no_key`);
and C5's `test_nothing_imports_the_web_fetcher_yet` is now
`::test_only_the_ingest_job_imports_the_web_fetcher`. Its scan reads what
`_aiohttp_routes` reads for `aiohttp`: an edge to the fetcher, which the graph
draws for every spelling of an import it reads — `import`, `from … import`,
relative, inside a function, a loader with a literal name, a star import
through a literal `__all__`; a name the ingest job binds to the fetcher, or to
anything of it, taken from the ingest job (`from src.programme.web_ingest
import web_fetch`); and the fetcher read off anything by its name, as an
attribute (`web_ingest.web_fetch.fetch`, `src.programme.web_fetch.fetch`) or a
literal handed to `getattr`, `attrgetter`, a loader or a subscript
(`vars(web_ingest)["web_fetch"]`, `sys.modules[...]`), each of which reaches
the fetcher with no import of it once the ingest job is loaded. The first cut
read the edges alone, and C6's review put `from src.programme.web_ingest
import web_fetch` into `jev_jobs`, which holds the road to Jev, and read
`web_ingest.web_fetch.fetch` in `main`, with every test green; each spelling
is now in the scan's own tests (`::test_the_fetcher_importer_scan_finds_each_spelling`,
`::test_the_fetcher_scan_finds_what_is_taken_from_its_importer`), beside what
it must not read as one, `main`'s loading of the ingest job among them. It
reads spellings, and a name computed at run time is a reviewer's. And the
roads to Jev reach neither the fetcher nor the ingest job through anything
they load — the lane, its client and the two handlers that ask — and the
forward clock no web module at all, the limits design section 9 marked tested
and no test yet held (`::test_no_road_to_jev_reaches_the_road_to_the_web`).
The job reaches the fake server in its tests by a stand-in
for `web_fetch.fetch`, never through a seam of its own, so production still
never passes `session_factory` (C5's scan reads `src/`).

**The planner.** One rule, beside C4's:

| Rule | Area | Kind | When | Key | Priority / attempts |
|---|---|---|---|---|---|
| Web ingest | research | `jev_web_ingest` | now | `jev_web_ingest:{source}:{UTC date}` | 10 / 3 |

Once a UTC day for each source on the allow-list, keyed by the UTC date of the
pass, so no past day is ever planned and a job already under today's key,
finished or not, is never joined by a second; the payload is the source's
name and nothing else. Its kind is spelled as a literal at its one enqueue,
where `test_job_ownership.py`'s scan holds it to the planner; from C6's
review that scan also counts `enqueue` taken by name — the literal
`"enqueue"` handed to `getattr`, a `vars()` or `__dict__` subscript or
`attrgetter`, and the jobs module, however imported, read by a computed name
or as a whole namespace — as a kind it cannot read, since `getattr(job_repo,
"enqueue")(conn, "jev_web_ingest", …)` anywhere in `src/` was a second
producer of the kind with every ownership test green
(`TestTheEnqueueScan`). It makes no call, so it takes nothing from a lane's
share and is planned on a budget of 0, like the reference bars. Without a key
it is not planned, though it asks Jev nothing (design R28). Priority 10 puts
it behind the forward clock and the probe and ahead of the re-asks.
`tests/unit/test_jev_plan.py::TestTheWebIngest`, and the planner's dark
matrix now with the research area in it; `tests/integration/test_jev_dark.py`
turns four switches in all sixteen combinations, the programme and Jev with
the research area planning the day's ingest, which fetches once and asks
nothing, and `::TestTheResearchAreaAloneFetchesNothing`: with research on and
the programme or Jev off, or with no key, no job is planned and no page
fetched; and `::TestAJobQueuedBeforeTheKeyOrThePinWentFetchesNothing`: a job
already queued, claimed with no key or with an alias where the pin was, fails
for good and fetches nothing.

**The canary, ingest half** (invariant I7).
`tests/integration/test_web_ingest.py::TestTheCanary` serves a synthetic page
over local HTTPS to the shipped fetcher, every control of it the shipped one
but the three C5's own tests change (the route to the local server, the
authority it trusts, and the address check, which admits 127.0.0.1, where the
server listens, and refuses whatever else it refuses), runs the job through
the programme's loop — enqueued, claimed and run, a key available — and looks
for a token one title carried: in `web_documents.excerpt`, one row, and in no
other text or JSON column of any table in `public`, read from
`information_schema` so a column a later migration adds is read too, a column
of a type the test has not sorted into text or not text failing it; in no log
record at DEBUG, message, arguments or traceback; and in no job's payload,
result or error. A token in a line the parser refuses is found nowhere at all,
the failed job's error included; so is one in a row the parser cannot read,
one in an address inside a kept title, which the normaliser removes, and one
in a row whose decoration alone trips the screen, which is dropped. Every
title of the page carries a token of its own, each beginning with one marker,
and the marker is looked for too, so a title that leaves by any road is found,
not only the watched one's: the first cut watched a single title, and the
mutation check put the page's first title in the job's result and passed it.
Until C7 asks, that one column is the only one: CLAUDE.md's row said one
column for now, and says two from C7+C8 (below).

**Where C6 departs from the design and its scope.** C5 changed the contract
first: the job stores what `screen_cell` decides, rather than screening the
cell and the excerpt itself and quarantining on either (C5 above). The job
reads the programme's switch as well as the research area before it fetches,
as the road reads all three, where the design named the area alone; and, from
C6's review, the pin and whether a key is set, which the design's section 8
left to the planner and its section 6.2 ("handlers re-check every
precondition") did not. It refuses a connection inside a transaction rather
than only fetching outside one. It quarantines an unquarantined stored copy of
content another document holds quarantined, as well as one the screen now
flags, the scope's one case: quarantine is by content, and two writers a
moment apart could otherwise leave a copy in use (open item 52). The result
adds `unparsed` to the scope's counts, since a row the parser drops was
otherwise visible nowhere, and counts `quarantined_by_code` and
`quarantined_earlier` over the snapshot's distinct excerpts, so a second read
of an unchanged page reports what the screen decides rather than nothing. A
failure while storing is retried, and reported by its class, SQLSTATE and
constraint; every other failure is not. `fetched_at` is the database's clock,
chosen as above. `DocumentRow` computes its own content address from its
excerpt, so no caller can file a row under another text's. The one-call scan's
rule changed from exactly one call a handler module to each kind's own count,
zero for this one, and `main`'s wrapper is marked as wrapping `run_job` so the
scan reads the module that holds the work. The design's `jev_labels` writes
wait for C7, which records the README's grouping as labels with the catalogue
set.

#### C7+C8: the injection screen, the catalogue, hypothesis categories and the card check, in shadow

The first sets asked about text. Four are registered: `guardrail.injection`
v1, the injection screen, and `research.catalogue` v1, asked about a stored
web excerpt; `research.hypothesis` v1 and `guardrail.card` v1, asked about the
title of a hypothesis the programme's own model wrote. One job asks each of
them, `jev_ask` (`jev_jobs.run_ask`), about one subject, once an attempt; the
planner plans it behind each set's lane's area. Dark twice over: the
guardrails and research areas are seeded off, so nothing is planned, and no
call has been made. And in shadow: a card check's answer, and every answer
about a title, is recorded and changes nothing; what a web answer may change
is one thing, a quarantine.

**The four sets.** Design section 5's words, word for word, through the real
registration rules (`jev_questions.py`); the caps a question names,
`EXCERPT_MAX_CHARS` and `TITLE_MAX_CHARS` (300), are rendered from their
constants. The hashes of the words as merged are design section 5's table
exactly:

| Set | Lane, provenance, state | Pack hash | Questions hash |
|---|---|---|---|
| `guardrail.injection` v1 | guardrail, web, `WebExcerptState` | `85229106…84068ab6` | `99cdb403…1c00f746` |
| `research.catalogue` v1 | research, web, `WebExcerptState` | `d3872677…18a3976d` | `d2608515…8ebbfc18` |
| `research.hypothesis` v1 | research, model, `HypothesisTitleState` | `35124e76…4eb0e0eb` | `5a75a21d…03513a57` |
| `guardrail.card` v1 | guardrail, model, `HypothesisTitleState` | `3f98bbc1…e0ebd455` | `47c322e7…1b42c130` |

The screen satisfies `screen_problem`: it asks `addressed_to_ai`, as a Noul,
and nothing else. `GOLDEN_PACK_HASHES` gains the four, the test's append-only
`RELEASED_PACK_HASHES` and `RELEASED_QUESTION_HASHES` a row each, and the
registry test is an exact pin of the six sets. `HypothesisTitleState` (one
field, `title`, 1 to 300 characters) joins `STATE_SUBJECT` as
`hypothesis_title` and `TEXT_SUBJECT_FIELD` as `title`. The design's wording
rules are tests over the whole registry
(`tests/unit/test_jev_questions.py::TestEverySetIsWrittenPlainly`): the escape
option comes last, no question is asked with a negation, the instructions
open with the question, every backticked name is a field of the state, and
every cap is rendered from its constant — read by executing the module's own
source with the constant moved, so a cap typed as a literal fails.

**The performance-claim check leaves the model runner** (C8). `claims.py` is
new and pure: `PERFORMANCE_TERMS`, `find_performance_claim`,
`NUMERIC_BY_DESIGN`, `reject_performance_claims` and `PerformanceClaimError`,
moved verbatim, `author` re-exporting every name, so
`author.find_performance_claim` is `claims.find_performance_claim`.
`author.propose_hypothesis` now screens the title too, with
`reject_performance_claims({"title": title, **card})` (the design's F11), and
`claims` joins the modules a fresh interpreter proves load nothing
(`tests/unit/test_claims.py`, `test_import_boundaries.py::test_the_pure_modules_load_nothing`).

**The `jev_ask` job.** Its payload is the set, its version, the subject's type
and address, the row its text is read from — a document by its id, a
hypothesis by its ref — and the analysis plans it was planned under (below),
never the text, which the handler reads again from that row. In order, the
first that applies deciding:

| # | Condition | Outcome |
|---|---|---|
| 0 | The payload is not those nine names, its set is not one the job asks, or its subject type is not the set's | fail, no retry |
| 1 | Its version is not the registered set's | complete, `superseded` |
| 2 | The set has no analysis plan | fail, no retry |
| 3 | The plans its payload names are not the plans in force | complete, `superseded` |
| 4 | The row is not stored, or its text is not the subject | fail, no retry |
| 5 | The text may not be asked about (below) | fail, no retry |
| 6 | The state cannot be built | fail, no retry, nothing quoted |
| 7 | The one ask, its follow-up, then the verdict | as `job_errors.ask_verdict` |

Step 5, for web text: content quarantined under any source is asked nothing;
then the code screen reads the stored excerpt again, as it stands now, and a
hit is quarantined by content with `web_sources.quarantine_reason` and fails
the job, so a rule the screen gained since the page was read applies before
any model is asked. For a title: only one the programme's model wrote
(`origin = 'model'`; open item 28), and only within `TITLE_MAX_CHARS`, refused
by that number before any state is built, so the refusal is the cap's and
never pydantic's. Step 6: pydantic's `ValidationError` quotes the input it
refused, so it is replaced by an error naming the document's id or the
hypothesis's ref alone; anything else steps 4 to 7 raise — a read, a
quarantine's write, the ask, the follow-up — is reported by its class,
SQLSTATE and constraint (`job_errors.described`, moved there from
`web_ingest`) and retried. The result is labels and numbers: the subject, the
plans (below), the status, the request, whether it replayed, and per question
its validity, reason, argmax, margin and, for a Noul, its probability. A job
that fails after its ask wrote or read a row carries the same record on its
failure, stored beside the error (below).

What an answer changes is the design's table and nothing more:

| Set | Answer | Follow-up |
|---|---|---|
| `guardrail.injection` | valid, argmax `true` | the content is quarantined, under every source: `jev guardrail.injection v1: addressed_to_ai p=0.87 (request N, <model>); not calibrated` |
| | valid, argmax `false` | none; the catalogue may now be planned |
| | invalid, or a tie, in an `ok` response | none: held, under this version and pin, since the canonical row replays |
| any web set | a content block, this call's or one on record | the content is quarantined: `vendor content block on request N (a 403 whose body is not JSON; an unverified precaution, docs/08 fact 4)` |
| `research.catalogue`, `research.hypothesis`, `guardrail.card` | anything else | none: recorded, acted on by nothing |

A title is never quarantined: quarantine is a stored document's, and a
blocked title is held by the road alone. Nothing that writes `hypotheses`,
`candidates` or `findings` is reachable from `jev_jobs`
(`tests/unit/test_jev_jobs.py::TestTheCardCheckChangesNothing`, below).

**A block's quarantine survives a failed write.** The block's `error` row
commits on its own before the follow-up runs, so a quarantine that then fails
— a deadlock, a dropped connection — leaves the block on record and the
content in use. So the block is found two ways: this call's row of kind
`content_block`, or, on any later ask about the same text, which the road
refuses before a call as `content_blocked`, the earliest block on record for
the content (`jev_repo.content_block_request`). The failed attempt is retried;
the retry makes no call and quarantines. And when every attempt fails,
`jev_repo.documents_to_screen` plans the screen, on a later pass, for any
content still in use that a block is on record for, whatever its screen rows
say — the catalogue's block of text the screen had cleared among them — and
that job, too, makes no call and quarantines
(`tests/unit/test_jev_jobs.py::TestWhatAnAnswerChanges::test_a_quarantine_that_failed_to_write_is_made_by_the_next_attempt`;
`tests/integration/test_jev_research.py::TestABlocksQuarantineSurvivesAFailedWrite`,
both ways, on PostgreSQL). The repair is planned whatever the vendor holds:
the first cut planned nothing of a set refused with a 422, nor anything while
an authentication failure held the day, since the road would refuse each such
ask before any call — true of every ask but the repair, which the road refuses
for its block, with no call, before it reads a standing refusal. A 422 holds
the screen's version until a new one, so a block whose quarantine failed
stayed in use for as long. Now, under either hold, the screen's repairs, and
nothing of a held set that would make a call, are planned
(`tests/unit/test_jev_plan.py::TestTheAsks::test_a_refused_screen_still_plans_its_repairs`
and `::test_nothing_that_calls_is_asked_while_an_authentication_failure_holds`;
`tests/integration/test_jev_research.py::TestABlocksQuarantineSurvivesAFailedWrite::test_the_repair_is_planned_whatever_the_vendor_holds`,
for a 422 and for a refused key).

**The screen's own quarantine survives a failed write** (from this part's
review). A valid `true` from the screen is canonical, and committed before its
quarantine is written, so a write that failed on every attempt left the text
in use for good: answered `ok`, the first cut never planned it again, and the
next day's re-ask, sampled in the low-margin stratum, sent the flagged text to
the vendor once more as a probe. Now the answer on record is read back as a
block is: `jev_repo.screen_flag` is the earliest canonical, valid `true` from
the screen about the content, under any version and any pin, since quarantine
is one-way and by content — where a clearance is read under the registered
screen and the pin alone. Before any ask about stored web text, a re-ask's
included, the handler reads it and, finding one, quarantines the content in
the screen's own words, uncalibrated, and fails the job asking nothing, after
the quarantined check and the code screen (`jev_jobs.screen_stored_excerpt`);
read before the ask rather than replayed by it, so a pin moved since asks the
new model nothing about the flagged text. `documents_to_screen` plans that
repair for flagged content still in use, first, with no call, beside the
block's; `documents_to_describe` never describes flagged content; and the
planner re-asks no flagged text
(`tests/unit/test_jev_jobs.py::TestWhatIsNotAsked::test_text_the_screen_flagged_is_quarantined_before_any_ask`,
`::TestAReaskOfText::test_web_text_the_screen_flagged_is_quarantined_and_not_asked_again`,
`tests/unit/test_jev_plan.py::TestTheReasks::test_text_the_screen_flagged_is_not_asked_again`,
`tests/integration/test_jev_repo.py::TestDocumentsToScreen::test_nothing_but_the_screens_canonical_true_is_a_flag`,
every filter of the flag by a case only it refuses, and
`tests/integration/test_jev_research.py::TestTheScreensQuarantineSurvivesAFailedWrite`,
the write failing on every attempt and, once, the pin moved after it).

**Re-asks of text.** `run_reask` reads a re-asked web excerpt through the code
screen first, as `run_ask` does, quarantining it on a hit and asking nothing,
and asks nothing about content quarantined since or flagged by the screen,
quarantining the flagged (the scope's 10c; C4's planner checked quarantine
alone, and now checks the flag too). A content block met by a re-ask of web
text quarantines it; a block met by a re-ask of a title or of an enumerated
state touches nothing, tested against a regime state and a hypothesis title
both, so widening the condition to every text state fails a test (10g). A
probe's answer never quarantines. Since a state may now hold text, a stored
state that no longer validates fails the re-ask without quoting it, and a
failure of the screen, the ask or the follow-up is reported by its class and
retried, where C4's let it propagate.

`ask_verdict` and `NOT_ASKED` moved from `jev_jobs` to `job_errors`, which
`jev_jobs` re-exports: `jev_jobs` now loads the code screen, and the forward
clock, which reads the verdict too, may load no web module at all. The
one-call scan counts per handler now that one module holds two that ask: every
call to the road reachable from a handler within its module, through a table
of follow-ups as well, one each for the ask and the re-ask, and none in the
module unreached (`tests/unit/test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall`).

**The card check changes nothing** (the scope's 10f). The design's test read
`raise_finding`, `decide_hypothesis` and `create_candidate` by name, and the
first build's version of it missed a writer taken under an alias. Now it is a
walk over `test_import_boundaries`' import graph from every definition in
`jev_jobs`: a definition is reached when anything reached refers to it,
called or not — by its module's name for it, an import under any alias, a
chain of attributes, a re-export through a module or a package, a star import,
`getattr` with a literal — and a module referred to as a value (passed,
stored, read through `vars` or `__dict__`, handed to `getattr` with a computed
name, or loaded by a literal name) is reached whole; a load by a name the scan
cannot read is refused. Every reached definition is checked by the shared
write scanner, `_table_writes`, for a write of `hypotheses`, `candidates` or
`findings`. It reaches the lane's `ask`, the quarantine, `repo.get_hypothesis`
and the code screen, and none of the writers the scan finds in `repo`; each of
21 spellings must trip it on a synthetic tree, and 3 that only read must not.
The tick's half of design C8 — it loads no `jev_*` or `web_*` module — is
`test_import_boundaries.py::test_no_model_runner_loads_a_jev_or_web_module`,
as before.

**A plan for each set, and the plan recorded with each answer.** `jev_prereg`
gains one plan per set, beside it, golden-hashed with an append-only released
history in the test; a registered set asking a question with no plan fails a
test, the connectivity probe exempt and `decision.regime` under the global
plan's regime section. Each target is its lane's target or higher, never
lower, and is met, as the global plan's are, by its statistic's Wilson lower
bound at the gate level. The global plan did not change: `PLAN_VERSION` 1, `GOLDEN_PLAN_HASH`
`f744c2d8…2daf7caf`.

| Set, question | Acting class | Target | Keyword baseline | Set plan hash |
|---|---|---|---|---|
| `guardrail.injection`, `addressed_to_ai` | `true` | covered precision ≥ 0.90 | the code screen, version 1, its rule data's hash in the plan | `2ba46f37…14eff8f7` |
| `research.catalogue`, `asset_class` and `mechanism` | — | covered accuracy ≥ 0.80 | the ordered keyword rules of design C7, as data | `9ab204c8…a5292deb` |
| `research.hypothesis`, `asset_class` and `mechanism` | — | covered accuracy ≥ 0.80 | the same rules, on the title | `1f7274a6…6a07f050` |
| `guardrail.card`, `performance_claim` | `true` | covered precision ≥ 0.90 | `claims.find_performance_claim(title) is not None`, its terms, proximity and number pattern in the plan | `a72753b5…d231956d` |

The keyword baselines are pure and deterministic, and match whole words of the
casefolded text, so "Turmoil in the Soil" holds no "oil"; the design's "crypto
words" are `crypto`, `cryptocurrency`, `bitcoin`, `ethereum` and `blockchain`.
The first build's docs claimed a plural rule its data broke (10b); now the
plurals are generated in code by one stated rule — a `y` after a consonant
becomes `ies`, a word ending `s`, `x`, `z`, `ch` or `sh` takes `es`, every
other takes `s` — applied to every keyword's last word that is not "of", a
keyword ending `*` being a stem matched at the start of a word (`diversif*`),
and the test holds the forms of the whole list to a table written there and
the labels to a copy of the rules written as literals
(`tests/unit/test_jev_prereg.py::TestTheKeywordRules`).

**The plans an answer was recorded under, however its job ends** (10a). The
plans in force — the global plan's version and hash and the set's own
(`jev_prereg.plans_in_force`) — are recorded for every answer twice over. The
planner writes them into each `jev_ask` payload, as it writes the global plan
into each re-ask's, and the handler asks nothing under any others (step 3), so
every row any attempt of the job records — an answer, a response refused
whole, a failed call — was recorded under the plans its payload has named
since before its first attempt, whatever becomes of the job. And the job's row
names the request its attempt recorded beside them: in the result of a job
that succeeds, as the regime job writes its plan into its result, and, from
the fixes to this part's review, in the result of one that fails after its ask
wrote or read a row — a response refused whole, which the harness counts
among the answers that were not valid and against the figure compared with
the baselines, or an answer whose follow-up failed on every attempt. A
handler's `JobFailedError` carries that record, the loop hands it to
`job_repo.fail`, which stores it beside the error, and an attempt that
recorded nothing leaves an earlier attempt's in place; every other caller of
`fail`, the worker's among them, passes none and writes none. The first cut
wrote the plans into a succeeding job's result alone, so neither of those
answers was recorded under any plan. A set with no plan is planned nothing and
asked nothing. **The harness (C9) scores an answer only under the plans in
force when it was recorded**, never by a baseline chosen after the answers: it
reads them from the job whose result names the answer's request, and, for an
answer no result names — a lease that expired after the ask, an attempt
superseded after an earlier one recorded — from the payloads of the jobs that
asked about its subject, which every row they recorded was recorded under.
`tests/unit/test_jev_jobs.py::TestTheAsk::test_a_response_refused_whole_is_recorded_with_its_plans`,
`::test_an_answer_whose_follow_up_failed_is_recorded_with_its_plans`,
`::test_a_job_planned_under_other_plans_asks_nothing` and
`::test_an_attempt_that_recorded_nothing_names_nothing`;
`tests/unit/test_job_ownership.py::TestTheProgrammeClaimsOnlyItsOwnKinds::test_what_a_failed_attempt_recorded_is_kept_beside_its_error`;
`tests/unit/test_jev_plan.py::TestTheAsks::test_a_set_with_no_plan_is_planned_nothing`;
and on PostgreSQL, through the loop,
`tests/integration/test_jev_research.py::TestEveryAnswerIsRecordedWithItsPlans`.

**The planner.** Four rules beside C4's and C6's, each set behind its own
lane's area:

| Rule | Area | Kind | When | Key | Priority / attempts | Most a pass |
|---|---|---|---|---|---|---|
| Injection screen | guardrails | `jev_ask` | now | `jev_ask:{set}@{v}:{subject_type}:{subject_id}:{UTC date}` | 0 / 3 | 25 |
| Card check | guardrails | `jev_ask` | now | as above | 0 / 3 | 10 |
| Catalogue | research | `jev_ask` | now | as above | 0 / 3 | 25 |
| Hypothesis categories | research | `jev_ask` | now | as above | 0 / 3 | 10 |

Each within its lane's share, the `jev_ask` jobs already waiting in a lane
counted against it (`jev_repo.pending_asks`); the kind is spelled as a literal
at its one enqueue, and the key is spelled once, `jev_repo.ask_job_key`, for
the planner and for the reads that exclude by it. The subjects are
`jev_repo`'s: `documents_to_screen` — content in use, quarantined under no
source, the screen has not answered `ok` under the pin, and first, its
repairs: content a block or the screen's own `true` is on record for (above),
whose ask makes no call and is planned with no call left; `documents_to_describe` — content the screen cleared, as
`screened_clean` reads a clearance, a *valid* answer of the clear argmax, and
nothing else, so the catalogue is never planned for text that is not screened
clean, nor for text the screen flagged under any pin; and `hypotheses_to_ask` — model-written titles of 1 to
`TITLE_MAX_CHARS` characters, by the content address computed in SQL
(`encode(sha256(convert_to(title, 'UTF8')), 'hex')`, which the tests hold to
`jev_hash.text_sha256` beyond ASCII), one subject per title, newest first.
Each leaves out a subject whose job is waiting, whatever day planned it, or was
planned today, finished or not, and retires one after three failed calls for
the set, its version and the pin; a failed call is a response refused whole
(`invalid`) or a call that failed (`error`). An `invalid` row is never
canonical, so it replays nothing and the subject is asked again on a later day
until the third; an `ok` answer is not asked again, whatever it said (the
first build's docstring said a response refused whole was not asked again
because its canonical row replays, which was false: 10h). The screen's repairs
are the exception to both: content a block or the screen's `true` is on record
for is returned until it is quarantined, whatever its answers and failed calls
(the reads' section comment said "never", which the blocked branch already
contradicted; corrected in this part's review). Nothing that would call is
planned while an authentication failure recorded today holds every lane, nor
of a set the vendor refused with a 422 at its version under the pin; the
screen's repairs, which make no call, are planned under either.
`tests/unit/test_jev_plan.py::TestTheAsks`, the planner's dark matrix now with
the guardrails area and a subject waiting for every set, and every filter of
each read on PostgreSQL by a case only it refuses
(`tests/integration/test_jev_repo.py::TestDocumentsToScreen`,
`::TestDocumentsToDescribe`, `::TestHypothesesToAsk`) — a screen answer that
is not valid but names `false` among them (10i).

**The README's own headings, as labels.** The ingest now records, in the
snapshot's one transaction and in content order, the source's heading for
each excerpt stored and in use that the snapshot lists under exactly one
heading: `jev_repo.record_label_once` — `ON CONFLICT ON CONSTRAINT
jev_labels_once_per_labeller DO NOTHING RETURNING id` — with the catalogue at
its registered version, question `asset_class`, the excerpt's address, the
heading's label from the parser's `Entry.label`, the labeller
`web_sources.dataset_labeller` of every kept row's heading label and excerpt,
and the note "the README's own section heading". The label is written to
`jev_labels` and never into the excerpt. The headings are counted over every
row the parser read, a copy the screen dropped as decoration included, so a
title under two headings anywhere in the snapshot has no one label, and is
counted (10e). Reading the same page again records nothing; a changed grouping
is a new labeller. The result gains `labels`, counts only — `recorded`,
`already`, `several_headings` — and `test_jev_table_boundaries.py` holds
`jev_labels` to `jev_repo`'s two inserts with the shared write scanner.

**Tests.** Beside those named above: `tests/integration/test_jev_research.py`
drives the whole of it through the programme's loop on PostgreSQL, with a
fake of `jev_client.ask` — a page ingested, screened content by content and
described only once cleared, a flagged text quarantined in the design's
words; a tie held, never screened again nor described, on any later day; one
ask quarantining a text stored under two sources; three failed calls retiring
a subject, which is planned again by its own key on a later day and not while
its job waits; the labels recorded once; the two ways a block's quarantine
survives; and the hypothesis and card asks leaving `hypotheses`, `candidates`
and `findings` as they were under every outcome — `true`, `false`, a response
refused whole, a timeout, a content block. `tests/sdk/test_jev_research_over_http.py`
screens and describes one stored excerpt through the planner, the handler,
the lane, the real client and SDK and the fake TypeSafe server, each request
exactly `{"excerpt": …}`, and replays the screen with no request leaving. The
integration dark matrix turns five switches in all 32 combinations: a stored
text is asked about only with both the guardrails and the research areas on,
and either alone sends nothing about it. Every new control was mutated and
restored in turn, and each mutation failed a test; one, the planner's repair
of a blocked text, first survived, because the test's blocked text had one
failed screen call and was planned again by the ordinary rule anyway, and the
test now blocks the catalogue's call after the screen cleared the text, which
only the repair brings back.

**The canary, end to end** (invariant I7). A page whose every title carries a
token under one marker is fetched over local HTTPS by the real fetcher —
admitting 127.0.0.1 in the address check inside the test alone, as C6's
canary does — read, screened and described through the programme's loop; the
marker is then in `web_documents.excerpt` and `jev_requests.state` and in no
other text or JSON column of any table, read from `information_schema`
(`programme_runs.actions`, `jobs.payload`, `jobs.result` and `jobs.error`
among them), in no log record at DEBUG and in no job's payload, result or
error. One title is refused as its state is built, by a validator whose
message quotes it, and its job's error names the document and nothing more.
Two columns hold web text now, and CLAUDE.md's row says so.

**The first build's review, item by item** (the scope's section 10). (a) The
plans are recorded with each answer, in its job's payload and its result,
whether the job succeeds or fails, and C9 scores under them. (b) The
plurals are generated by the stated rule and tested over the whole list, and
keywords match whole words. (c) A web re-ask is read through the code screen
first. (d) A block's quarantine is derivable and repeated: the next ask about
the text makes it, and a later pass plans the ask that will. (e) Headings are
counted over every row read. (f) The card-check scan follows references,
aliases included, over the import graph, proved on synthetic trees. (g) The
re-ask's block follow-up is tested against a title as well as a regime state.
(h) The reads' docstrings say what they do, and the behaviour they describe is
tested. (i) The title cap is held by a spy on the state's construction and by
a cap lowered below the state's own limit, and the clearance's validity by an
invalid answer naming `false`.

**Where C7+C8 departs from the design and its scope.** `Askable` carries what
the handler needs beyond the design's five fields — the text in the row, an
admission step that may refuse it, and how an error names the row — and
`run_ask` reports anything steps 4 to 7 raise by class, a read or a
quarantine's write as well as the ask. The payload carries the plans beyond
the design's five names, and a job planned under plans no longer in force
completes `superseded`, as one planned under another version does; and a
failed job's result holds what its attempt recorded, where the queue stored
an error alone. `ask_verdict`, `NOT_ASKED` and
`described` moved to `job_errors`. The re-ask's state rebuild is guarded and
its failures reported by class, where C4's propagated. `documents_to_screen`
plans content a block, or the screen's own `true`, is on record for, where
the design's row left such content out: that is the scope's 10d repair,
extended in this part's review to the screen's flag, and the ask makes no
call; the handler reads the flag before any ask about stored web text, which
the design's step 4 did not. `documents_to_describe` and `hypotheses_to_ask`
leave out blocked subjects, which the road refuses for good, and
`documents_to_describe` flagged ones; the reads match a clearance by the
content's address rather than the state's hash, which name the same text;
only `invalid` and `error` rows are failed calls, a refusal recording no call.
The planner reads the authentication hold and the 422 hold, which the design
left to the road, so that it plans no job, a subject a day, that could only
fail — the screen's repairs excepted, which make no call. The
labeller is computed over every kept row, a quarantined one included, as C6's
`kept` reads; the injection reason names the model that answered, read back
from its request. The scope's `test_the_card_check_changes_nothing` is a class
of tests, the walk and its proofs. The set plans landed before the job, since
the job records them. The SDK test calls the handler itself rather than the
loop's drain, so the probe the planner also plans takes none of the scripted
replies. And the Lanes table above now names the questions the catalogue asks
(open item 29).

### Open items Phase C found

Numbered on from Phase B's.

23. ~~**The live ingest stitched `adj_close`.**~~ *Closed by W:*
    `run_ingest_bars` refetched ten days, so every distribution left a step at
    the ten-day boundary and a stored series drifted from any fresh fetch of
    the same history. It now refetches each owned symbol's whole stored span
    and every stored row takes that fetch's `adj_close`; see W above.
24. **The live path's `daily_bars` readers have no `source` filter.**
    `live_job._load_panel` and `shadow_job._price_map` read every source's rows
    for a symbol, and `PricePanel.from_bars` keeps the last of two rows for one
    session, so a second vendor's rows would be mixed into the live panel
    without a word. Latent while `yfinance` is the only source written — the
    live ingest and the reference job both write it, and nothing in
    `src/programme` writes the table at all — but a second vendor needs the
    filter first. The reference job's backfill of a live-owned symbol assumes
    the same: it writes `yfinance` rows that only a live ingest writing
    `yfinance` would re-base.
25. **Phase E needs an allow-list of the `jev_repo` functions the API may
    call.** The API may import the module, and nothing yet says which of its
    reads a route may serve.
26. **`decision_cutoff` moves to `src/core`** with phase F's
    `src/db/repos/signals.py`, which must compute the cutoff from the
    calendar rather than read it from the row.
27. **Forward coverage.** The collection window is ten minutes, the worker runs
    one job at a time, the programme restarts on a schedule and Yahoo can be
    late; each missing session will say why, and phase H's coverage target is
    judged on that record.
28. **Operator-written hypotheses are not sent, by design.** Categorising them
    needs an `operator`-provenance set with words of its own, and a subject
    type of its own: a hypothesis title is recorded as `model`
    (`jev_questions.TEXT_SUBJECT_PROVENANCE`), whichever set asks about it.
29. ~~**The Lanes table's catalogue set is the plan's, not the design's.**~~
    *Closed by C7+C8:* the table named four `research.catalogue` questions, a
    rebalancing horizon among them; it now names the two the registered set
    asks, asset class and mechanism, and says which sets are built.
30. **The trading calendar's end moves with the process.** `calendar.nyse`
    passes no `end`, so `exchange_calendars` builds XNYS to its default, one
    year from the day the library was imported (`GLOBAL_DEFAULT_END`); XNYS
    computes its holidays by rule and has no maximum of its own. So no upgrade
    is due by any date, and 2027-09-27 was only the end as of a process started
    on 2026-09-27. What is true instead: a process that ran for a year would
    reach its calendar's end, and the forward clock's planner would plan
    nothing past it. Passing an explicit `end` widens it, holidays still right
    years ahead. The scheduled programme runs for under six hours at a time
    (`programme.yml`), so it is far from that today.
    `test_calendar_bounds.py::TestTheUpperBoundMovesWithTheProcess` holds the
    end to a year from the day the tests run.
31. **Crafted injection positives.** Whether TypeSafe's terms (MCA 2.3, AUP
    3.7) allow the injection screen to be evaluated on text written to trip it
    is a question for the operator. Until it is answered none is sent, and the
    screen is evaluated only on what the allow-list fetched and on operator
    labels.
32. **Operator cards posted to `POST /programme/hypotheses` never pass
    `reject_performance_claims`.** C8 has moved the check into the pure
    `claims` module, which loads nothing, so the API may now import it to
    close this; the route is phase E's, and unchanged.
33. **A 422 hold is permanent per set version and pin.** A spurious 422 from
    the vendor disables a set until a reworded version, which the released
    questions hashes force to change its words. Deliberate: it fails closed.
34. **The Score legend's wire format is unobserved.** The check accepts a list
    of the levels or an object keyed by index, and refuses anything else; the
    first recorded Score answer settles it. Until then a Score of five to ten
    levels also waits for a measured sum tolerance.
35. **`findings.raised_by`'s migration comment says `programme:<role>`**, and
    the code writes the bare role key. Found in passing; unrelated to Jev.
36. **A content block holds its text for good, on a heuristic.** The client
    classes any 403 whose body is not JSON as `content_block`, and an edge's
    page — a firewall's, a CDN's — is one. For text that is the design's
    precaution: the text is never sent again, by any set, and its canonical
    answer is not read back, with no release but a migration, since the ledger
    refuses DELETE. It binds text only: the first draft held enumerated states
    too, and one such page would have taken a regime state out of the forward
    clock for good, which is why an enumerated state is now held by nothing.
    Beside item 33's 422 hold, the other refusal that does not lift.
37. **An authentication hold outlasts a replaced key.** The hold reads "any
    authentication failure since 00:00 UTC", and nothing records which key
    failed, so after an operator replaces a refused key every ask, the
    connectivity probe's included, is `auth_held` until midnight: the
    `jev_probe` job fails without a retry, and once the forward clock runs,
    that day's session would be lost with it. Until then the dispatch-only
    `jev_check` (`jev-check.yml`), which records nothing, is what proves the new
    key; the probe's error says so. Lifting the hold on a later success would
    need the probe exempt from it, which is the design's "every lane" undone,
    so it is left for an operator to decide.
38. ~~**The daily report's data health reads every symbol's rows.**~~ *Closed
    by C4:* the latest session is the stalest traded symbol's newest, read as
    the live ingest reads the traded universe, and a universe that cannot be
    read, a traded symbol with no bar or nothing traded leaves it absent with
    a note; `tests/unit/test_report_data_health.py`. See C4 above.
39. ~~**C4's planner must give the reference job attempts enough to reach the
    cutoff.**~~ *Closed by C4:* `jev_plan.REFERENCE_ATTEMPTS` is
    `attempts_spanning(15 minutes)`, 14, the fewest whose `attempts × 10 s`
    backoff reaches the cutoff from the minute the bars settle;
    `tests/unit/test_jev_plan.py::TestTheReferenceJobsAttempts`.
40. ~~**A day the live ingest could not refetch its span is a failed
    `ingest_bars:{S}`, and the forward clock should read it.**~~ *Closed by
    C4:* while an enabled operator deployment trades a sleeve's instrument,
    the regime job treats a session whose `ingest_bars:{S}` has not succeeded
    as a missing close, retried until the cutoff and then absent, the job's
    error its reason; a deployment that cannot be built counts every sleeve as
    live-owned. And since who owns a sleeve now is not who owned it when the
    ingest ran, once an attempt of the ingest has not succeeded a sleeve
    nobody trades now waits too, unless the reference job for the session
    re-based it whole (C4's review).
    `tests/unit/test_jev_forward.py::TestALiveOwnedSleeveWaitsForTheLiveIngest`,
    `::TestASleeveTheLiveIngestHeldWhenItFailedWaitsToo` and their integration
    counterpart.
41. **The web fetcher ignores the environment's proxies,** by design, so it
    cannot fetch where the only way out is a proxy — the development sandbox
    C5 was built in is such a place. The scheduled programme connects
    directly. A proxy the fetcher had to use would be named in code, like the
    allow-list, and never read from the environment.
42. **The address check sees names only.** aiohttp connects to an address
    written in a URL without resolving it. Nothing today can hand the fetcher
    one — the allow-list refuses an address as a host, and no redirect is
    followed — but a change to either reopens the route to the metadata
    service, and should arrive with its own check.
43. **HTML's legacy references are decoded without their semicolon.**
    `html.unescape` reads `&notes` as `¬es`, which GitHub's renderer does
    not, so a title holding such text would be stored a little differently
    from how it reads. No title on today's page has one.
44. **The code screen quarantines a paper that names Claude, GPT or OpenAI in
    its title.** Friction only — Jev is not asked about it — and how often it
    happens is measured once C7's injection screen is evaluated against the
    code screen as its baseline.
45. ~~**An excerpt can normalise to nothing.**~~ *Closed in C5's review:* a
    title that was only an address, text that never settles, or text past the
    normaliser's bound has no excerpt, and `web_sources.screen_cell`, whose
    decision C6 stores, drops such a row as it drops one whose decoration alone
    tripped the code screen, rather than leaving the rule to the ingest job.
46. **The code screen's skeleton reads the lookalikes it lists.** 254 letters
    of other scripts and Latin letters no decomposition reaches, after UTS #39,
    and not the whole confusables table, so a keyword spelled with a lookalike
    it does not list passes the keyword rules and meets only the mixed-script
    rule, which a word of lookalikes from one script does not trip. A baseline's
    known limit rather than a defence's: Jev's own injection screen (C7) is
    measured against it, and a longer table is a new version of the screen.
47. **Two runs of 16 split by whitespace is the shortest base64 the screen
    reads as split.** A payload broken into shorter runs passes
    `encoded_payload`; reading shorter runs would read ordinary titles, whose
    words are runs of letters, as payloads. Recorded so C7's evaluation counts
    it against the baseline rather than for it.
48. **`forward-audit`'s drift is data trouble, and it cannot say which.**
    *Corrected in C4's review*, which found this item teaching the opposite:
    it said a re-basing could move a recorded state, so that drift might be
    harmless basis movement. It cannot. Every descriptor is a ratio of the
    sleeve's adjusted closes or a statistic of their log returns — trend is
    the latest over the average, drawdown the latest over the high, momentum
    the latest over an earlier close, volatility the spread of log returns —
    and a distribution after session S multiplies every close S's state was
    computed from by one factor, so it leaves every descriptor as it was
    (exactly, in exact arithmetic; a vendor that rounded re-based prices could
    flip only a label sitting within that rounding of its band's edge).
    `tests/unit/test_jev_features.py::TestARebasingMovesNoDescriptor` re-bases
    each sleeve by its own factor at every half year of a synthetic market
    and finds no state moved, and a 3% stitch at the ten-day boundary moving
    some. So drift always means the stored window changed unevenly since the
    recording: a vendor revised a price, an adjustment was applied after the
    recording (the table was stale when the state was computed), a stitched
    window was mended, or a gap was filled. What stays open is which: the
    audit names the descriptors that moved, and telling a revision from a
    history that was stale or stitched at recording would need the bars as
    they stood then, which nothing keeps.
49. **The programme reads the traded universe by a copy of the worker's
    rule.** It may not import the worker, so `repo.traded_universe` repeats
    `maintenance_jobs._deployed_universe`'s query and strategy build, and
    `tests/integration/test_jev_forward.py::TestTheTradedUniverseIsTheWorkers`
    holds the two to one answer on one set of rows. A change to the worker's
    rule that the test's rows do not exercise would pass it; the rule belongs
    in a module both may import, which phase F's move of the cutoff into
    `src/core` is the occasion for.
50. ~~**The restart slots are UTC, and the busy windows are checked over two
    years only.**~~ *Closed in C4's review:* the test walked every session
    from a year before the day it ran, a span holding no summer half day, so
    a July 3, which closes at 17:00 UTC, would have been checked only when it
    came into reach. It now walks every session from 2007-03-12, the first
    under the daylight-saving rules in force, to the calendar's end, and
    fails if no summer half day is among them. The 17:00 slot restarts at
    such a close, half an hour before the evening's first window opens, which
    the test allows; the restart is the queued successor's, not a wait on
    the 17:00 event, which is no longer a trigger (see C4 above).
51. **The report page was changed without its captures.** The absent latest
    session now says why in the report's terms; `tsc`, `next build` and the
    design-token, component and formatting tests pass, but the route was not
    captured or scanned with axe (`web/CLAUDE.md`), the change being words in
    an existing `Absent`.
52. **A copy stored as another writer quarantines its content stays in use
    until the page is read again.** The ingest reads which of a snapshot's
    excerpts are quarantined anywhere and then inserts, in one transaction
    under READ COMMITTED; a quarantine another writer commits between the two
    — C7's injection screen, or a second source's ingest — cannot see a copy
    not yet committed, and that copy is stored in use. The next read of the
    page quarantines it, naming the earliest quarantine (C6 above), and until
    then the web gate, which looks quarantine up by content at the moment of
    asking, refuses it all the same, so no set is asked about it. Serializable
    isolation would close the gap at the price of a retry on every conflict;
    not taken.
53. **A day whose fetch failed waits for the next day.** A failed fetch and a
    refused page fail the job without a retry, so a transient network fault
    costs that day's snapshot, and the next UTC day's job fetches afresh. A job
    left queued past its day — the programme or Jev switched off between the
    plan and the claim — runs beside the next day's once they are back on,
    fetching the page twice in a day, the second storing nothing, unless the
    key or the pin went in the meantime, when it fails without fetching; and
    two such jobs run at once take their locks in one order, so neither ends
    in a deadlock (both from C6's review). Neither changes what is stored, and
    both are on the jobs' rows.
54. **The injection screen quarantines on an uncalibrated argmax.** A valid
    `true` — any probability above one half — quarantines the text, as design
    C7's table says, and its reason says it is not calibrated. Whether one half
    is the right line is C9's to measure, against the code screen as baseline
    and the 0.90 covered-precision target; a different line would be a change
    to the follow-up, recorded as a change of the set's plan.
55. **A held text stays held for its version and pin.** A tie, or another
    screen answer that measured nothing, is canonical and replays, so the text
    is never screened again and never described until a new version of the
    screen or a new pin. Nothing lists held texts yet; phase E's status page
    is the place.
56. **The screen is planned before the card check in the guardrail lane's
    share.** A backlog of stored text that fills the lane's calls each day
    would hold the card checks back until it clears. At the seeded budget the
    lane has 175 calls a day and the page about sixty titles, so it is not
    reached today.
57. **A source's labels accumulate a labeller per version of its page.** The
    labeller is the snapshot's grouping at its hash, so a title added or moved
    is a new labeller, labelling every item again; each labels an item once.
    The harness (C9) must choose which labeller an answer is measured against
    — the one in force when the answer was recorded, say — rather than pool
    them.
58. **Content whose quarantine keeps failing is planned once a day.** Content
    a block or the screen's own `true` is on record for: the screen's ask
    about it makes no call, is planned whatever the vendor holds (a 422 on the
    screen, an authentication failure), and the job stops once the write
    succeeds; it repeats only while the database refuses the quarantine. Such
    a repair ends its job `failed`, saying the content is now quarantined, as
    the code screen's quarantine before an ask does: the job asked nothing.
59. **The canary cannot see what a real vendor echoes.** It runs against a
    fake of `jev_client.ask`, and the SDK test against a fake server modelling
    the documented contract, whose response holds answers and no state. A
    vendor that echoed the request into its response would put web text in
    `jev_requests.raw_body`, a third column; the first real answer settles it,
    and the canary reads that column like every other.

## Inputs needed from the operator

Inputs, not approvals.

1. **A TypeSafe API key** from an existing `console.typesafe.ai` account, since
   new signups are paused. It is set on System > Configuration, which phase B
   connected to the vault, or, for the scheduled programme, as the
   `TYPESAFE_API_KEY` repository secret, which `programme.yml` passes. A key
   alone calls nothing from the programme: its first call is the connectivity
   probe, which the planner enqueues once a UTC day from C4, and only once
   `programme_enabled` and `jev_enabled` are both on. The key itself is checked
   first, by hand, with the dispatch-only `jev-check.yml`, which records
   nothing. The operator set the repository secret on 2026-09-26, and the key
   check passed against TypeSafe the same day. Phases A to G are built and
   tested against fakes regardless, and the programme makes no live call until
   both switches are on; the forward clock asks nothing until the decisions
   area is on as well.
2. **A review of `REGIME_BASELINE_RULE` and the reference sleeves** (SPY,
   IEF, GSG). Both are the defaults the agent that built C4 chose (see C4
   above). Before the decisions area is first switched on, a change is a plan
   version bump that costs nothing; after the first regime answer, the same
   bump is recorded as a change of plan.
3. **A replacement Alpaca paper key** for the revoked one.
4. **For phase H, a second Alpaca paper account's key**: a `PK` key, checked
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
