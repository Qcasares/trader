# The Jev integration

Specification and record of wiring TypeSafe AI's Jev into the AI programme.
Owner: Quentin Casares. Phases A, B and C of eight are built. In phase C,
C1+C2 hardened the one road every lane takes, W gave the worker the forward
clock's reference bars, C4 started the forward clock — a planner, the
`jev_regime` job, a daily connectivity probe, flip re-asks, the
pre-registered analysis plan and a read-only harness — C5 and C6 read the
web, C7+C8 asked the first sets about text, in shadow, and C9 measures the
answers against labels, with migration 0014. D to H are not built. The code
is dark: every Jev switch is seeded off, no lane is wired into the
programme's tick, the planner, the only producer of a job that can make a
call, plans nothing until an operator switches the programme and Jev on, and
no evaluation arms anything. A TypeSafe key exists, as the `TYPESAFE_API_KEY`
repository secret set on 26 September 2026, and the dispatch-only key check
proved it against TypeSafe's own host the same day: the listing named the
aliases only, and the pinned `jev-1.13.0` answered the connectivity probe as
expected. The programme itself has made no call. Last revised 1 October 2026.

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
| A 403 whose body is not JSON | 403 | `TypeSafePermissionDeniedError` | For text — a web excerpt, a hypothesis title or, from D2, a finding title — the state is not sent again, and a web document it came from is quarantined, as a possible content block. A precaution: it rests on one unverified third-party report, and the verification found no primary evidence for it. An enumerated state is not held: it is labels computed in code, nothing a filter could object to, so an edge's 403 page is the likelier cause, and holding it for good would take it out of the forward clock |

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
| `jev_catalogue.py` | Pure, and importable by the API. `JEV_BASE_URL`; `KNOWN_MODELS`, the pinned IDs this repository has chosen to call, today `jev-1.13.0` alone, each matching `^jev-\d+\.\d+\.\d+\Z` under `re.ASCII` (with `$`, `"jev-1.13.0\n"` would pass); the refused aliases `jev-latest`, `jev-preview`, `jev` and `jev-1.13`, by name in any case or spacing; the size limits, 56k tokens in total and 28k for state plus the longest question, on an estimate of one token per three ASCII bytes and one per byte of anything else, the byte-level worst case, since the vendor's tokenizer is undisclosed; the client's rate ceilings; the lane, provenance, subject-type and area vocabularies and `LANE_AREA`; `LANE_BUDGET_PERCENT`, each recorded lane's share of the daily budget, in code so that no database write can raise one (phase C); and one `settings_problem()` shared by the form and the runner, which caps the daily budget at 10,000. From C9, `MODEL_FIRST_OBSERVED`, the UTC day each pinned model was first seen answering — `jev-1.13.0` on 26 September 2026, by the key check — against which an evaluation's items are dated; a model in `KNOWN_MODELS` without one fails its test. From D1, phase D's shares (research 25, guardrail 25, findings 10, ops 10, decision 20, probe 10), `smallest_shares`, which a refused budget's message names, and provenance `system`. From D2, the subject type `finding_title`, and from D3 `job_error` |
| `jev_questions.py` | Pure. Versioned question sets: name, version, lane, provenance, questions as ordered pairs, a `state_model` (pydantic, `extra='forbid'`, frozen, strict) and a purpose. Each has a golden hash. Every Choice has exactly one escape option, last, and a frozen option order. Phase B registers `probe.connectivity` v1 and `decision.regime` v1. Phase C adds `WebExcerptState`, the one state web text is asked about in, of 1 to 300 characters; each state model's subject type, and for text who writes it (`TEXT_SUBJECT_PROVENANCE`); the injection screen's name, its one question and clear answer (`screen_problem`); and `registration_problem`, which holds a set to the sets already registered and to the rules the lane relies on. A set's state is read twice for this system's own detail: from its model at registration, failing closed, and from what `dump_state` would send. A Score question registers with at most four levels. C7+C8 register `guardrail.injection`, `research.catalogue`, `research.hypothesis` and `guardrail.card`, v1 each, and `HypothesisTitleState`, a title of 1 to `TITLE_MAX_CHARS` (300) characters. D1 adds two rules with no registered set under them yet: `STATE_ADDRESSED`, the models whose subject is their whole state, its id `state_hash` of the state sent, and `TEXT_FREE_LANES`, the ops lane, whose sets declare `internal_detail` and send no text, read on every dump whatever they declare. D2 registers `findings.owner` and `findings.severity`, v1 each, lane `findings`, provenance `model`, about `FindingTitleState`, a title of 1 to `FINDING_TITLE_MAX_CHARS` (200) characters, `roles.ProposedFinding`'s cap. D3 registers `ops.job_error` v1, lane `ops`, provenance `system`, declaring `internal_detail`, about `JobErrorState`: a failed research or ingest job's kind and its error's skeleton, the redactor's tokens and nothing else, addressed by its whole state (`STATE_ADDRESSED`), with `job_error_text` and `job_error_from_text`, its text and the one state a text names |
| `jev_validate.py` | Pure, and never raises. The response rules in fact 3, and from phase C a Score's legend and its agreement with its own probabilities |
| `jev_hash.py` | Pure; importable by the programme, the API and the harness, and, like every module here, never by the worker or the decision path. A request's identity: `state_hash`, `request_hash`, `questions_hash` — the part of the request hash a set contributes — and `text_sha256`, a text subject's content address. Moved out of `jev_lane` in phase C, which re-exports the first two, so the API and the harness can compute one without loading the client |
| `jev_features.py` | Pure. `regime_state` turns a `PricePanel` into enumerated descriptors of three sleeves, computed in code from `adj_close` — trend relative to the 200-session average, a volatility quintile, a drawdown bucket, the direction of 63-session momentum — or `None` when the data cannot support them. The decision lane's only state. From C4, `regime_state_problem` says why it would be `None`, for a job's error |
| `jev_repo.py` | Queries for the Jev tables. No SDK, so the API can import it. A request and its answers are one write. From phase C, the road's reads: the calls a lane made today, whether the vendor refused a key today, a set's version or a state, whether content is quarantined, and whether the injection screen cleared a text; from C4, the clock's, the planner's and the harness's: whether a session has a signal, a series' signals with their answers, the canonical requests of a day, each canonical answer beside its re-asks, the probe's series, and the jobs behind a list of keys. Inside the programme it is the one reader of `jev_signals`. From C6, the one writer of `web_documents`: `insert_documents`, `ON CONFLICT DO NOTHING`, `title` and `published_at` NULL by the statement, and `quarantine_content`, the one update the table allows, by content and one-way; with `get_document` and `earliest_quarantined`. From C7+C8, the one writer of `jev_labels` (`record_label`, and `record_label_once` for a source's headings), what each set is to be asked about (`documents_to_screen`, `documents_to_describe`, `hypotheses_to_ask`), the `jev_ask` jobs waiting, the earliest content block on record for a subject, and `ask_job_key`. From C9, the harness's reads — a question's labels, each subject's answer (the `ok` non-probe row's, else the newest `invalid` one's), the items' dates, their texts, the subjects a labeller is shown, the `jev_ask` jobs about them, the words a version was asked with, and what quarantined each content — and the one writer of `jev_evaluations`, `record_evaluation`, which takes exactly `EVALUATION_COLUMNS`, with `evaluations_for` and `latest_evaluations`. From D1, `get_hypothesis_title`, the title sets' read: a hypothesis's ref, title, origin and creation time, by column list. From D2, `get_finding_title`, the findings sets' read: a finding's ref, title, origin and `opened_at`, by column list; `findings_to_ask`, the titles of model-written findings each findings set is to be asked about; the harness's finding-title dates, texts and labelling population, read over the sets' population, and `finding_records`, who raised the earliest model-written finding holding a title and its severity, which only the harness reads; and `suggestions`' reads, `open_findings`, `jev_findings_raised` and `ask_outcomes`, which read no option, probability or margin. From D3, the ops set's reads: `get_failed_job`, a job by its id, as its id, kind, status, error and finish time; `failed_jobs_for_triage`, the planner's; `unasked_subjects`, C7's filters over addresses computed in code; `job_error_since` and `job_error_population`, where the population starts and what it holds, each skeleton by its state's address; the harness's job-error dates and texts, read over that population; and `recent_failed_jobs`, what `suggestions` lists. None reads a job's error but to hand it to code's triage and the redactor |
| `jev_clock.py` | C4. Holds no client and is not runner-only, so phase E may read the cutoff. The forward clock's times — the reference bars at a session's close plus 45 minutes (the worker's ingest time), the collection at plus 50, the cutoff at plus 60 (the worker's decision time) — the sessions the planner plans, the signal's and the jobs' names, `sleeve_symbol`, and the bar loader, which reads `adj_close` from `yfinance` alone |
| `jev_forward.py` | C4, runner-only. `collect`, the `jev_regime` job: one session's regime, asked before the cutoff by the database's clock, at most one call an attempt — an attempt whose call got no response is retried and asks again — and one answer recorded at most once; never a backfill and never a `missing` row |
| `jev_jobs.py` | C4, runner-only. `run_reask`, the `jev_reask` job; from C7+C8, `run_ask`, the `jev_ask` job — one registered set asked about one stored text, a web excerpt read through the code screen or a model-written title within its cap — and what an answer changes (`ASKABLE`), a quarantine and nothing else. Re-exports `ask_verdict`. From D2, `ASKABLE` holds the findings sets: a finding's title read by column list, admitted only when the programme's model wrote it and it is within its cap, and no follow-up, so an answer changes nothing. From D3, `ASKABLE` holds `ops.job_error`: a failed job read by its id and admitted rule by rule, its state the skeleton, its subject the state's address, checked once the state is built (`Askable.address`), and no follow-up |
| `jev_plan.py` | C4, runner-only. The planner: the daily probe, the worker's reference bars, the regime job and the re-asks, each behind its switches, enqueued with literal kinds and nothing else; from C6, the web ingest, once a UTC day for each allowed source, behind the research area; from C7+C8, the `jev_ask` jobs, each set behind its lane's area; from D1, a set declaring `internal_detail` only while `jev_send_internal_detail` is on; from D2, the findings sets behind the findings area, ten a pass each, from the findings share; from D3, the ops set behind the ops area and the detail switch, ten a pass, from the ops share, each skeleton once by its newest job |
| `jev_prereg.py` | C4. Pure, the standard library alone, importable by the API. The analysis plan and `REGIME_BASELINE_RULE`, registered before any answer and golden-hashed, with an append-only release history kept in its test; from C7+C8, a plan for each set asked about text, with its keyword baseline, recorded with every answer (`plans_in_force`). From D1, plan version 2, and the regime's rule and sleeves a plan of their own (`regime_plan`, `REGIME_PLAN_VERSION`). From D2, the findings sets' plans, whose baseline is `findings.recorded`, the value already recorded, and which name the population they are asked about (`FINDINGS_POPULATION`); and `keyword_label`'s `fallback`. From D3, the ops set's plan, its baseline the keyword rule on the skeleton's text (`OPS_KEYWORDS`, every keyword held to an evidence corpus), its population named with the redactor's and the shapes table's versions and hashes (`OPS_POPULATION`) |
| `jev_stats.py` | C4. Pure. `proportion` and `wilson`; a figure over nothing is `None`. C9 adds the Brier scores, a percentile bootstrap seeded by the caller, calibration bins, the threshold search on the development split, Cohen's kappa and the flip count, each `None`, never 0, over nothing |
| `jev_eval.py` | C4, runner-only CLI. `python -m src.programme.jev_eval status`, `forward` and `forward-audit`: read-only, `DATABASE_URL` and nothing else, no key, and a closure that reaches no client. C9 adds `evaluate`, `labels export`, `labels import`, `labels copy` and `report`: one question against one labeller's labels, the labels themselves, and the newest evaluations. Only `labels import`, `labels copy` and `evaluate --record` write, each in one transaction and through `jev_repo` alone; every other command reads in a read-only snapshot. `evaluate --record` alone reads a second variable, `GIT_COMMIT`, which names a commit and holds no secret. From D1, `evaluate --split` has no default, a look at the held-out items is taken only with `--record`, and `report` prints the looks each set, version and question has spent. From D2, a finding's title is a labelled subject, measured against `findings.recorded`; and two more reading commands: `preview`, what a title set would be asked about and the exact state that would leave, and `suggestions`, how each findings set's ask about each open finding came out, never an answer. From D3, a failed job's skeleton is a labelled subject, its label read back through the state its text names and its date over the population's rows; `preview` takes the ops set, and `suggestions` lists each failed job of the week with code's chip |
| `jev_calibration.py` | C9. Pure, `jev_prereg` alone. `usable`, whether a recorded evaluation could arm a threshold and every reason it could not; `card_verdict` and `document_path`, what an armed threshold would be allowed to do, which is add friction and never remove it; and `analysis_plan_hash`, the identity of the plans an evaluation is computed under. Loaded by the harness, to report, and by nothing that acts: phase C arms no threshold. From D1 `usable` counts the looks taken before an evaluation, across every model, and reads a flip limit in the worst case |
| `jev_chips.py` | D2. Pure, the standard library alone, importable by the API. What phase E may show beside a finding, computed when the page is read and stored nowhere: `severity_chip`, only where Jev's valid suggestion is more serious than the severity recorded; `route_chip`, a suggested reviewer, which on a finding that blocks names only a role in `VETO_ROLES`; and `duplicate_chips`, code's, by exact normalised title, from a newer finding to the earliest older one on the same candidate that blocks at least as much. A chip is labels and numbers, never a title. `VETO_ROLES`, the blocking severities, the severities and the role keys are copies of `gates`' and `roles`', which load pydantic, held equal to them by test. Nothing in phase D shows a chip. From D3, code first for a failed job: `code_cause` places an error by `JOB_ERROR_SHAPES`, a pinned, hashed table of the shapes this system's raise sites write, and returns `None` only for a triaged kind's residue, which `residue_skeleton` turns into what may be sent; and `reconciliation_chip`, `data_health_chips` and `ingest_chips`, code's labels of structured rows, never sent. It loads `jev_redact` and nothing else of the programme |
| `jev_redact.py` | D3. Pure, the standard library alone, importable by the API. `skeleton`: a failed job's error, its first 4,000 characters, reduced to at most 48 tokens of a closed vocabulary — 393 words, the exception names and the HTTP tokens — in order, everything else a placeholder saying what kind of thing stood there, never what it was. The one way any part of `jobs.error` can become state: an allow-list of numbered rules, idempotent, total and never raising, its vocabulary, never-list, placeholders and rules hashed (`redactor_sha256`) and pinned (`GOLDEN_REDACTOR_SHA256`). `TRIAGED_KINDS`, the research and ingest kinds whose residue Jev may be asked about, and `admissible`, at least three words of content |
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

Migration `0014_jev_evaluations_measured.sql`, phase C9's, adds to
`jev_evaluations` what design section 10.1 defines and 0012 had no column
for: the split (`all` or `test`, required, `all` by default), the analysis
plans' hash, the keyword baseline's name, the answers' hash, the reporting
level and the gate level; the answers counted valid, escape, not valid and not
asked, beside the items contested, answered under other plans and under plans
unknown, and the distinct states; accuracy over every item with its interval,
the per-class figures and the Brier score's climatology; the threshold's
outcome, statistic, target, development dataset and the test items measured
at it, with accuracy there; each baseline's paired difference with its bounds
and the discordant items it is made of; the low-margin and near-threshold
flip rates and every rate's pair count and re-asks not compared, with the
median lag; and labeller agreement, kappa and its n. Every measurement is
nullable, NULL meaning not measured, and eighteen named CHECKs hold the rest
(C9 below),
**`NOT possibly_in_training OR threshold IS NULL`** and
**`model ~ '^jev-[0-9]+\.[0-9]+\.[0-9]+$'`** among them. Added while no
database holds an evaluation; over one holding a row its rules refuse, 0014
fails whole and leaves it at 0013.

Migration `0015_jev_phase_d.sql`, phase D's first (D1), exactly as
docs/09 section 7 gives it, gives `findings` its writer and keeps what was
raised. `findings.origin` is `NOT NULL`: the rows already stored read
`'unknown'`, which means raised before 0015 by a writer nobody can now prove,
and the default that gave them it is dropped at once, so an insert naming no
writer fails on the column, and a trigger refuses one naming `'unknown'`. From
then on a finding is `'model'` (the tick's panel), `'operator'` (the API) or
`'jev'`, the card check's, which only phase D4's writer is to raise. A Jev
finding names the request it rests on (`source_request_id`,
`findings_jev_names_its_request`), and a trigger,
`findings_jev_rests_on_its_answer`, holds it to a valid `true` to
`performance_claim` on an `ok`, non-probe `guardrail.card` request, raised as
`jev:guardrail.card`; CHECKs keep the `jev:` raiser to Jev's findings alone, a
Jev finding at `low` or `medium`, so that it never blocks, and on a candidate;
and `findings_one_per_jev_answer` admits one per candidate per answer.
`findings_keep_what_was_raised` lets only the closure's columns change and
refuses a reopen, which 0008's CHECK always admitted; and DELETE and TRUNCATE
are refused with an exception, so a candidate's delete, which would cascade
to its findings, fails with them. Every comparison of `origin` in a trigger
is NULL-safe, so an insert naming none fails on `NOT NULL` rather than on a
trigger's message. 0015 also seeds the card check's arming switch off; adds
provenance `system` to `jev_requests_provenance_check` alone, under its own
name, so a request may be recorded as this system's own records computed in
code — the ops lane's skeletons, from D3 — while `jev_signals`, whose CHECK
stays as 0013 wrote it, can never hold a signal resting on one; and moves
0014's flip conjuncts out of `jev_evaluations_counts_within_n` into
`jev_evaluations_flip_counts_are_counts`, since under plan version 2 a flip
rate counts the question's whole population and its pairs are no longer
bounded by the scored items. Applied over a database at 0014 holding rows, it
keeps every row as it was; over one holding a finding raised under a `jev:`
raiser, which no writer has ever written, it fails whole and leaves it at 0014
(`tests/integration/test_phase_d_schema.py::TestTheMigration`).

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
down, and below 10 the smallest shares — the probe lane's, and from D1 the
findings and ops lanes' as well — would be none while the setting read as one
that permitted calls, so a budget is 0 or at least 10
(`jev_catalogue.MIN_DAILY_REQUEST_BUDGET`, derived from the shares), and the
refusal names the lanes with the smallest share. The programme's Jev loop asks
`programme_enabled` as well as `jev_enabled`: two independent switches, both
required, neither derived from the other. From phase C the road asks them
itself, on every ask, with the area of the set's own lane and, for a set that
carries this system's own detail, `jev_send_internal_detail`, so a caller that
forgot to is held to them anyway.

Migration 0015 seeds one more, `jev_arm_card_check`, false: whether the card
check may add a finding, from phase D4, and one of two independent conditions
for it beside a usable, person-labelled evaluation, neither derived from the
other. `flags.jev_arm_card_check` reads it through the same `_switch`, on only
for a stored JSON `true`, and `JEV_KEYS`, held to the seeds of 0012 and 0015,
gains it; in D1 nothing reads it to act. From D1 the planner reads
`jev_send_internal_detail` too, through its own reader, as the road does: a
set declaring `internal_detail` is planned only while it is on, so no job is
queued only to end `disabled`. No registered set declares it until D3's
`ops.job_error`, so a set of the ops lane will go only while the ops area and
the detail switch are both on.

From D2 the findings area has its consumers: the road, for `findings.owner`
and `findings.severity`, and the planner's findings rules, each reading it
through `flags.jev_area_enabled(conn, "findings")`, which needs the master
switch too. A finding's title goes only while the programme, Jev and the
findings area are all on, each read by its own reader; neither findings set
declares `internal_detail`, so the detail switch is not read for them.

From D3 the ops area and the detail switch have their consumers: the road, for
`ops.job_error`, and the planner's ops rule, each reading the ops area through
`flags.jev_area_enabled(conn, "ops")`, which needs the master switch too, and the
detail switch through `flags.jev_send_internal_detail`, each its own fail-closed
reader, neither derived from the other. A failed job's skeleton goes only while
the programme, Jev, the ops area and the detail switch are all on: the ops area
on with the detail switch off plans and sends nothing. That is the default the
scope chose for the owner's item 9.1, which is still open, and fact 7 is not
amended (open item 89).

## Lanes

Planned, except where a row says what is built. Phase B built the one road
every lane takes, `jev_lane.ask`, and registered two question sets: the
connectivity probe, and `decision.regime` v1, which the forward clock asks
from C4. Phase C's first pull request moved every rule a lane could forget
into that road, and C7+C8 registered the research and guardrail sets below,
dark and in shadow; C9 measures their answers against labels, and arms
nothing with what it finds. Phase D2 registered the two findings sets, dark,
asked about the title of every finding the programme's model raised, and
recorded with nothing changed. Phase D3 registered `ops.job_error`, dark, asked
about the skeleton of a failed research or ingest job's error that code cannot
place, and recorded with nothing changed. A set's version is a field of its own, pinned
with its golden hash, so the sets below are named without one.

| Lane | Question sets | State | What Jev may do | What it may never do |
|---|---|---|---|---|
| Research | `research.catalogue` (asset class, mechanism), built in C7; `research.hypothesis` (the same two questions about a hypothesis's title), built in C8; `research.news` (relevance, event type, tone), not planned | Allow-listed web excerpts; the programme's model-written hypothesis titles | Today: be recorded and planned on, the catalogue only for text the injection screen cleared, which it asks under the research area alone. Later: label the catalogue page; rank a shortlist `author.py` may use to prioritise | Satisfy any gate criterion |
| Guardrails | `guardrail.injection` ("addressed to an AI system"), built in C7, asked before any other set about a stored web excerpt, under the guardrails area alone; `guardrail.card` (a performance claim), built in C8 beside `find_performance_claim`, in shadow; an untestable falsification test, planned | Allow-listed web excerpts; hypothesis titles; cards as titles unless the detail switch is on | Today: the injection screen quarantines what it flags, uncalibrated, and its clearance is what lets the catalogue ask; the card check is recorded and changes nothing. Later, once calibrated (phase D): a "yes" from the card check rejects or raises a finding | Accept anything. A "no" changes nothing, so the accepted set with Jev is a subset of the set without it — a property test |
| Findings routing | `findings.owner` (the owning role: the twelve, in `roles`' order, then "unclear") and `findings.severity` (low to critical, then "insufficient_evidence"), two sets so that rewording one re-asks nothing of the other, built in D2; a likely-duplicate question, deferred (open item 71), duplicates being code's alone | The title of each finding the programme's model raised, whatever its status, of 1 to 200 characters, under the findings area alone: never an operator's, Jev's or one raised before 0015, and never a finding's detail, remediation, close note, raiser or recorded severity | Today: be recorded and change nothing; measured against the value already recorded, who raised the finding and at what severity (`findings.recorded`). For phase E, `jev_chips` computes a suggested reviewer, a suggested severity shown only where it escalates, and code's duplicate pointer, shown beside the recorded raiser and severity and never instead | Write a finding's severity, status or anything else, close or remove one, or argue against a veto: on a finding that blocks, a suggested reviewer names only a role holding one, and a duplicate points only to an older finding that blocks at least as much. Findings Jev raises (D4, the card check alone) carry `raised_by='jev:<set>'`, never in `VETO_ROLES` |
| Ops triage | `ops.job_error` (the likely cause of a failed job: the ten causes code shares, `jev_chips.CAUSES`, then "unclear"), built in D3; reconciliation discrepancies, data health and the ingest get code's chips alone | A failed job's kind and its error's skeleton, the redactor's tokens and nothing else, recorded as provenance `system`: only for a research or ingest job whose error code's table cannot place, and only while the ops area and the detail switch are both on. Code places every error it can first; a venue, shadow or programme job, or an account's data, is never sent | Today: be recorded and change nothing, measured against the keyword rule on the skeleton's text. For phase E, code's chip beside every failed job on System > Jobs, and Jev's suggestion beside the residue's | Resume, retry, cancel or change any job, touch the kill switch, or see an error's own words |
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
| C. Research lane | Web ingest, the injection screen, catalogue labels, hypothesis categorisation, guardrails; the evaluation harness (`python -m src.programme.jev_eval`, never `src/cli.py`). **The forward clock starts:** `decision.regime` v1 is collected, recorded and not consumed | **Done**: C1+C2, W, C5, C4, C6, C7+C8 and C9, all dark |
| D. Ops triage and findings routing | Triage chips for job errors, reconciliation discrepancies and data-quality alerts; suggested reviewer, duplicate and severity for findings, which needs the panel to sit (phase A); and the card check armed. Designed in `docs/09-jev-phase-d-design.md`, with its build scope beside it | **In progress**: D1, D2 and D3 done, dark |
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
| C9 | The evaluation harness, migration 0014 | C4, C7+C8 | **Done** |

Phase D lands as four pull requests, each dark, each with its own subsection
under "Phase D, as built" and its own CLAUDE.md rows. D1 merges first, before
any Jev area is first switched on: plan version 2 is free only while the
ledger holds no answer.

| Pull request | Contents | Depends on | Status |
|---|---|---|---|
| D1 | Plan version 2 and the regime's plan apart, looks counted; migration 0015 and a finding's writer; the title sets read by column list; subjects addressed by their state and the text-free ops lane; the arming switch; phase D's shares; the detail switch in the planner; the walks that hold what Jev's code reads and writes | — | **Done** |
| D2 | Findings routing: `findings.owner` and `findings.severity`, the chips, the harness's `preview` and `suggestions` | D1 | **Done** |
| D3 | Ops triage: the redactor, code triage first, `ops.job_error` behind the ops area and the detail switch | D1 | **Done** |
| D4 | The card check armed, behind the arming switch and a usable person-labelled evaluation | D1, D2, D3 | Not started |

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
`REGIME_PLAN_VERSION` with its hash appended, which sets aside regime
agreement alone and costs nothing; a changed sleeve also changes
`src/data/reference.py` and starts a new signal series, since the signal's
symbol names the instruments. After it, the same bump, recorded as a change of
plan: the regime job writes the plans in force into its result as it asks,
the regime plan beside the global one, and the planner writes the global plan
into each re-ask's payload, so `forward` scores agreement only over answers
first recorded under the regime plan it runs and counts the rest apart by the
regime plan they were recorded under (a result naming none, as C4's jobs
wrote them, as plan unknown), and a flip rate counts only the pairs sampled
under the global plan in force; the report names both plans, no answer is
scored by a rule registered after it, and the old rule is never rewritten to
match. The first cut said all this and built none of it. As C4 built it, the
rule and the sleeves sat inside the global plan, so a change was a new
`PLAN_VERSION`, which would have set aside every lane's answers as well; phase
D1 moved them into a regime plan of their own (M4, under "Phase D, as built").

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
and the code screen, and none of the writers the scan finds in `repo`.

This part's review found it read a module's bindings alone, so a writer stored
into a table by code the module runs when imported — a subscript, a method
call such as `update`, a loop, `setattr` — was never reached, nor one looked up
in `globals()` or `sys.modules` by a literal. Now every module the walk enters
— anything of it reached, or imported by a module entered — has its
import-time code read: everything it runs on import but a binding reached by
its name, so stores, calls, loops, tests, decorators, default arguments, a
class's bases and its body's own such code, and an assignment whose value
calls anything, a `__name__ == "__main__"` block excepted, which runs as a
script only. Every binding of a name is read, not its last alone. A literal
looked up in `globals()`, `vars()`, `locals()` or `sys.modules`, subscripted or
through `get`, is the name or the module it names, and any other key, or any
other use of a namespace, is refused as a load the scan cannot read. In the
real tree it now enters 33 modules, the closure of `jev_jobs`' imports, reads
400 pieces of their import-time code, and finds no writer. Each of 34
spellings must trip it on a synthetic tree, and 6 that only read, or run as a
script only, must not; six mutations of the walk, each removing one of these
readings, fail them. The tick's half of design C8 — it loads no `jev_*` or
`web_*` module — is
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

The card's baseline is held the same way, from this part's review. Its plan
hashes the claims check's terms, reach and number pattern, and nothing held
how the check applies them: a rule that read a term only before its number
left the card's plan hash golden and every suite green, and an answer
recorded under plan version 1 would have been measured against another
baseline still calling itself version 1. Now the test holds
`claims.find_performance_claim` to a copy written there as literals, read by
hand, over 5,000 seeded invented titles built on the rule's edges — a term
before and after its number, at the reach and one beyond, inside a longer
word, in any case, numbers negative, decimal, in percent, run together and in
other scripts' digits — and to its verdicts on invented titles recorded under
the plan version that registered them, so a change to what it decides fails
until the card's plan version is bumped and a row of verdicts added
(`tests/unit/test_jev_prereg.py::TestTheCardBaselineIsPinnedByWhatItDoes`;
the reviewer's mutation and five others each fail it).

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
the guardrails area and a subject waiting for every set, and every filter and
order of each read on PostgreSQL by a case only it refuses
(`tests/integration/test_jev_repo.py::TestDocumentsToScreen`,
`::TestDocumentsToDescribe`, `::TestHypothesesToAsk`) — a screen answer that
is not valid but names `false` among them (10i). As first written that was not
so: this part's review found a waiting job's version and a block's subject
type held by nothing, and loosening each of the three reads' 54 filters and
orders in turn, the flag's among them, found seven more — a waiting job's
kind; the subject type of an answer, of a failed call and of a clearance; the
statuses a failed call is counted from, a refusal being no call; a
clearance's argmax, which the flag read had left the second of two refusals
of a `true`, now held by a valid argmax the schema admits and the validator
never writes for a Noul; and the catalogue's earliest first. Each is now held
by a case only it refuses.

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
integration dark matrix turns five switches in all 32 combinations from an
empty ledger, where only the research area's ingest stores text: a text the
ingest stored is asked about only with both the guardrails and the research
areas on. With text already stored, each area asks its own lane's sets alone,
as the road reads them (design section 8): the guardrails area alone screens
a stored text the screen has not answered, sending it, and the research area
alone describes one the screen cleared earlier; turning research off stops
the catalogue and the ingest, not the screen
(`tests/integration/test_jev_dark.py::TestATextAlreadyStoredIsAskedAboutByEachAreasOwnSets`,
the four combinations of the two areas over a cleared text and an unscreened
one). The first record said a stored text was asked about only with both
areas on and either alone sent nothing about it, which held only from an
empty ledger — this part's review found it, and the design's own C7 line,
"two areas must be on for a document to be described; either off and nothing
is sent", is true of a document the ingest has just stored and of nothing
else. Every new control was mutated and
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
replies. The Lanes table above now names the questions the catalogue asks
(open item 29), and, from this part's review, lists the injection screen
under Guardrails, its lane and area, where the first record put it under
Research. And design C7's Dark line — "two areas must be on for a document to
be described; either off and nothing is sent" — holds for a document the
ingest has just stored, not for one already stored: the binding rule is the
design's section 8, each set's own lane's area read by the road, which the
code follows and the dark tests now hold both ways (above).

#### C9: the evaluation harness, against labels

The last part of phase C measures what the sets C7+C8 registered answered,
against labels a person or a dataset gave the same texts, and arms nothing
with what it finds. `python -m src.programme.jev_eval` gains five commands
beside C4's three, which are unchanged; migration 0014 gives an evaluation
the columns design section 10.1 defines; `jev_stats` gains the statistics,
and `jev_calibration`, new and pure, says when an evaluation could arm a
threshold and what an armed one could do, for the harness to report and for
nothing that acts to read. Dark: the harness asks nothing, holds no key, and
writes labels and evaluations, through `jev_repo`, in three commands alone.

**The commands.**

| Command | What it does |
|---|---|
| `evaluate --set S --key K --labelled-by L --split dev\|test\|all [--model M] [--record [--commit SHA]] [--json]` | One question of one registered set against exactly one labeller's labels, for one pinned model — the pin by default — over the split named. As C9 built it, `--split` took `test` or `all`, defaulted to the held-out test split, and ran as a dry run, printing every figure with its n and interval and "dry run: nothing recorded", unless `--record`; from phase D1 (plan version 2, M3) `--split` has no default, `test` and `all` are looks at the held-out items, each taken only with `--record`, and `dev`, the development split's search, is never recorded, all refused in `jev_eval.execute` before any connection (see Phase D, as built). `--record` writes the row and refuses without a commit: `--commit`, else `GIT_COMMIT`, else `git rev-parse HEAD` on a tree with nothing uncommitted, 40 lowercase hex digits in each case. Refuses `decision.regime` ("its numbers are forward's"), a question no set plan registered, a labeller that is no labeller, a model that is not pinned, and nothing labelled under the plans in force: "not measured: no labelled items", with how many items were set apart, on standard error, and nothing written |
| `labels export --set S --key K --blind [--sample N] [--include-quarantined]` | CSV of `subject_type, subject_id, text` and nothing else: every stored subject of the set's kind — web content, each once by its earliest document's excerpt, or each title the programme's model wrote within the cap — in the order of their addresses, the first N where a sample is asked for. Which subjects is decided by the stored texts and the code alone: web text the code screen, run on it now, flags is left out unless `--include-quarantined`, a quarantine made by code from the words, which no set is ever asked about, and nothing else is. Content Jev's own injection screen quarantined, or a vendor's content block, is exported like any other, since leaving it out chose the subjects by what was answered: the first cut left out every quarantined content, so a labeller of the screen never saw one of its `true` answers (C9's review). No answer, request or quarantine is read, so neither what a labeller sees nor which subjects can depend on what Jev or the vendor said. For the catalogue, content the screen quarantined is never described, and counts as not asked. `--blind` is required, so no export can be asked for that is not |
| `labels import --file F (--as operator:NAME \| --source DATASET)` | A UTF-8 CSV of `question_set, question_set_version, question_key, subject_type, subject_id, label`, optionally `note` and `text`, and no other column, an answer column above all. Every row is checked first: the set registered and the version its own, a question its plan plans, the subject its kind of text by a content address that is stored, the label one of the question's options and never its escape, a `text`, where given, the text the address names, each item once; and no item this labeller has labelled otherwise, since a label revised after the answers are seen is not ground truth. One refused row and nothing is recorded. A person is `operator:NAME`, lower case; a dataset is `source:DATASET@` the first twelve hex digits of the file's sha256, and an allow-listed source's name is refused, its labeller being the ingest's |
| `labels copy --set S --key K --from-version A --to-version B` | Each label of the key at A, by its own labeller, to B, the registered version, noted "copied from vA", where the key's type and options, with their descriptions and in order, are A's exactly. A version no longer registered has its words only in the requests it was asked with, so they are read from there, and a version never asked is refused |
| `report [--json]` | The newest evaluation of each set, version, key, model, labeller and split, every figure with its n and interval, "UPPER BOUND" wherever it may be in training; whether it could arm a threshold and each reason it could not (`jev_calibration.usable`, against the pin and the plans in force now); and the quarantines, in design section 10.3's words only: "k by the code screen v1; k by Jev's screen (not calibrated); k by vendor content blocks" |

`main(argv)` exits 0, 1 for a refused command and 2 for a usage error,
`--commit` without `--record` among them. The three commands that write each
run in one repeatable-read transaction, through `jev_repo.record_label` and
`jev_repo.record_evaluation`; every other command runs in one read-only
snapshot, and on PostgreSQL a write inside one is refused by the database,
not by the harness
(`tests/integration/test_jev_evaluations.py::TestTheCommandsOnPostgres::test_a_reading_command_runs_where_postgres_refuses_a_write`,
each reading command's work swapped for a write). `evaluate`, the
computation, is a function the tests call
(`jev_eval.evaluate(conn, *, question_set, question_key, labelled_by, model,
split) -> Evaluation`); `Evaluation` is a frozen dataclass whose fields are
`jev_repo.EVALUATION_COLUMNS`, every column of the table but `id` and
`created_at`, held to `information_schema` on PostgreSQL. The figure itself
is `build_evaluation`, pure, over rows already read.

**What an evaluation is** (design section 10.1, binding). The items are the
labeller's labelled subjects in the split; each is scored by its answer, the
`ok` non-probe row's for the pinned model, else the newest `invalid` one's,
exact because subjects are content addresses. The answers are counted valid,
escape (valid, and never correct), not valid and not asked, and the three
partition n. Accuracy is correct over the valid answers and, over every item,
correct over n, the not valid and the not asked counted wrong — the figure
compared with the baselines, which answer every item. Each class has its n,
recall, precision and the keyword rule's own precision and recall, and "too
few to say" below ten; balanced accuracy is the mean recall. The Brier score
is over the valid answers — a Choice's distribution scaled to sum to one, a
Noul's p(true) — with a bootstrap interval of 2,000 resamples seeded from the
dataset's hash, and its climatology on the same items; the calibration bins
are deciles of the top probability, each with n, mean, agreement and Wilson,
and a probability is binned by its decimal, so 0.3 is in the bin from 0.3.
The majority baseline is in-sample, which favours it, ties going to the first
option; the keyword baseline is the one the set plan registered — the plan's
keyword rules for the catalogue and the hypotheses, the code screen v1 at the
rules hash the plan holds for the screen, refused if the screen running is
another, and the claims check for the card. Each comparison is Jev minus the
baseline over the same items, reported with its paired bootstrap interval at
the reporting level like every other interval, beside the items only one of
the two got right, which the row records; Jev beats a baseline only by the
exact one-sided sign test of those items at the gate level (McNemar's, exact:
`jev_stats.sign_test`), and the text says "too few to say" where not even
every one of them going Jev's way could reach it — fewer than eight at plan
version 1's 0.995, and from phase D1 fewer than eleven at version 2's 0.999375.
The bootstrap gates nothing: over a few discordant items it understates their
uncertainty, and the first cut, which gated on its bound, called one item of
one, and five, six or seven of 200 all Jev's way, a win at exact chances of
1/2 to 1/128 against the gate's 1/200 (C9's review). The threshold is searched
on the development split alone, on the margin grid, the smallest with at least
30 covered whose statistic's one-sided Wilson lower bound at the gate level
meets the set plan's target — covered accuracy, or covered precision of the
acting class `true` for the guardrails — `not_attempted` below 100
development items or on an upper bound, `none_found`, or `chosen`, and then
measured on the test split; a test split's own labels never move it
(`tests/unit/test_jev_eval.py::TestTheThreshold::test_the_threshold_depends_only_on_the_dev_split`).
The flip rates are C4's pairs, each counted only in the stratum and under the
global plan its re-ask was sampled under, the near-threshold rate from either
stratum within 0.10 of the threshold once one is chosen, read as the decimals
the margins were written as (in binary a margin exactly 0.10 away fell out of
20 of the grid's 91 edges), with the uniform stratum's median lag; and in each
the re-asks whose pair could not be compared — a re-ask, or its canonical
answer, not valid, failed or refused — are counted with the row and printed
beside the rate, "k of n compared re-asks ...; m re-asked, j not compared",
never dropped from both counts. Every level the text prints is the row's own:
`ci_level` for each interval and `gate_ci_level` for each gate, never the plan
in force when it is read.
Labeller agreement compares each item with the earliest label another
labeller gave it, a dataset's page versions being one labeller, with Cohen's
kappa. The dataset's hash is of its sorted `(subject_type, subject_id,
label)`, the answers' of their sorted ids. Each figure over nothing is
`None`, printed "not measured" with its n; a genuine zero is printed as zero;
nothing is sorted by a figure.

**The plans an answer was recorded under** (the scope's 10a, exactly as C7+C8
stated it). An answer's plans are those of the `jev_ask` job whose result
names its request with `replayed` false; for an answer no result names, those
the payloads of every `jev_ask` job that asked about its subject name, only
if every one names the same; otherwise unknown. A replay never re-dates an
answer: the plans are the recording attempt's, not a later replaying job's
(`tests/unit/test_jev_eval.py::TestThePlansAnAnswerWasRecordedUnder`). An
answer recorded under plans other than those in force, or under plans
unknown, is counted in `n_other_plans` or `n_plan_unknown` and never scored.
The plans in force are `jev_prereg.plans_in_force`, and the row records their
identity, `jev_calibration.analysis_plan_hash`.

**Possibly in training** (the scope's 6). Computed, never typed: false only
when every item the evaluation reads is dated strictly after the pinned
model's first observation, `jev_catalogue.MODEL_FIRST_OBSERVED`, `jev-1.13.0`
on 26 September 2026 by the key check, a conservative bound. The items read
include the development split's when the figures are the test split's, since
a threshold rests on them: an undated development item makes a well-dated
test split an upper bound, and no threshold is searched
(`tests/unit/test_jev_eval.py::TestPossiblyInTraining`). An excerpt's date is
its documents' earliest `published_at`, unknown, and so possibly in training,
if any is NULL; a title's is its hypothesis's earliest `created_at`. Every web document
is stored with `published_at` NULL (C6), so every evaluation of a web set is
an upper bound — the README's grouping's always — and an upper bound carries
no threshold: the harness searches none, and 0014 refuses one whoever writes
it (open item 65).

**One labeller at a time** (the scope's 10b; open item 57). An evaluation is
computed against exactly the labeller named on the command line and never
pools labellers, and `report` lists each apart. The README's grouping is a
labeller per version of its page, `source:pwb-readme@<sha12>`, and is
printed as "the README's own grouping, never ground truth".

**`jev_calibration`.** `usable(evaluation, *, earlier, pin, plan_hash)`
returns whether a recorded evaluation could arm a threshold, the threshold,
and every reason it could not, each enough alone (one test each,
`tests/unit/test_jev_calibration.py::TestUsable`): another set version or a
key its plan does not plan, another model than the pin, other plans than
those in force, not the test split, fewer than 200 items, possibly in
training, no threshold chosen or no coverage at it, a threshold the held-out
test split does not bear out, either baseline not beaten, a uniform or
near-threshold flip rate not measured on 30 pairs or above its limit, a test
set an earlier version's evaluation used, or a newer evaluation of its key.
The held-out reason (`held_out`) holds the test split to the rule the search
applied on the development split: at least 30 test items measured at the
threshold, a coverage above 0, and the statistic's one-sided Wilson lower
bound at the gate level at least the plan's target. The threshold is the
smallest of fifty margins that cleared its target on the development split,
so that bound flatters by construction, and the first cut read nothing the
test split measured: a threshold at which every covered test answer was
wrong — 0 of 30, or the card check's covered precision 0 of 22 — was reported
usable (C9's review;
`tests/unit/test_jev_eval.py::TestAThresholdTheTestSplitRefutes`). A baseline
is beaten only by the exact sign test of the items one of the two got right
(above), never by the difference's bootstrap bound. `card_verdict` never accepts what the code's check
rejected and, armed, can only add a rejection; `document_path` takes no
calibration, a code flag quarantining whatever Jev said and a text being
described only on a valid `false` with no code flag
(`::TestTheCardVerdict` and `::TestTheDocumentPath`, exhaustive). Nothing
that acts loads it — the planner, the jobs, the lane and its client, the
runner, the ingest and fetcher, the tick and what it runs, and every package
that can move money (`test_import_boundaries.py::test_nothing_that_acts_loads_the_calibration`
and `::test_nothing_that_can_move_money_loads_the_calibration`); and
`jev_calibration`, with `jev_stats`, is in the fresh-interpreter check that a
pure module loads nothing (`::test_the_pure_modules_load_nothing`), it alone
allowed `jev_prereg` and `jev_stats`, both pure, for the plan and the gates'
statistics.

**Migration 0014.** The columns are those above (Schema), and from C9's
review three more kinds: `gate_ci_level` beside `ci_level`, each comparison's
discordant items (`vs_<baseline>_jev_right_only`,
`vs_<baseline>_baseline_right_only`), and each flip rate's re-asks not
compared (`flip_rate_not_compared` and the low-margin and near-threshold
strata's). The split is required, `all` by default; every measurement is
nullable, NULL meaning not measured. Its eighteen CHECKs, each named and each
tolerant of NULL: every proportion in [0, 1], 0012's columns among them; both
levels strictly between 0 and 1; the Brier score and its climatology in
[0, 2]; kappa in [−1, 1]; each difference in [−1, 1], and its discordant
items present with it and making it, (Jev's − the baseline's) over n; an
estimate held by its interval, and an estimate and its two bounds all present
or all absent; every count within n — the discordant items of a baseline,
and the re-asks of the two strata and of the window, together — and the
three that sit outside it non-negative; valid, not valid and not asked adding
up to n, the escapes within the valid; each flip rate present exactly when
its pairs are more than none, and the lag a finite number of hours beside
uniform pairs, NaN and Infinity refused (PostgreSQL orders NaN above every
number, so the first cut's `>= 0` admitted both); the threshold's group —
threshold, statistic, target, development dataset and the test items measured
at it — whole exactly when the outcome is `chosen`, and nothing measured or
counted at a threshold without one, the re-asks near it included, which the
first cut admitted; no threshold on an upper bound; the model a pinned id;
and the split and the outcome each in their vocabulary. PostgreSQL tests a
table's CHECKs in the order of their names and names only the first a row
fails, so each case of
`tests/integration/test_jev_evaluations.py::TestEveryRuleBites` breaks one
conjunct alone — each side of a range, an interval or an equality, each
count's floor and ceiling, each member of a group missing alone, each member
of a threshold's group recorded where none was chosen, and an estimate
without its interval — and
`::test_each_case_breaks_its_rule_alone` admits it with that rule alone
dropped, in a transaction rolled back after; a conjunct other rules imply (an
interval's inner ends, an estimate's own range, a difference's point, and an
accuracy's bounds at a threshold nobody chose, which the carry rule holds to
the accuracy) has no case and says so. A CHECK added without a case
fails `::test_every_rule_0014_adds_has_a_case`. What was not measured is NULL
and stays NULL, a genuine zero stays zero, and 0014 applies over a database
at 0013 holding rows, or fails whole and leaves it there
(`::TestTheMigration`). The rows stay append-only under 0012's trigger. 0014
was changed in C9's review, which it could be only because no database it
was checked against holds it: the branch is unmerged, and `migrate.yml`, the
one road to the deployed schema besides the API's authenticated route, which
applies what the deployed code carries, is dispatch-only and has run four
times, all on `main` and all in August 2026, before C9 began.

**The repository.** `labels_for`, `answers_for_subjects`, `item_dates`,
`subject_texts`, `subjects_to_label`, `ask_jobs_about`, `recorded_questions`,
`quarantine_reasons`, `evaluations_for` and `latest_evaluations` read; the one
insert of `jev_evaluations` is `record_evaluation`, which takes exactly
`EVALUATION_COLUMNS` and refuses a column missing or unknown before writing.
`jev_labels` and `jev_evaluations` are written in `jev_repo` alone, and the
latter by that function alone
(`tests/unit/test_jev_table_boundaries.py::test_only_the_repo_writes_jev_evaluations`
and `::test_the_repo_writes_jev_evaluations_by_record_evaluation_alone`, each
scan proved on sources that must trip it). On PostgreSQL each read is held to
what it returns (`tests/integration/test_jev_repo.py::TestTheHarnessLabels`
to `::TestRecordEvaluation`).

**The boundaries.** The harness's closure reaches no lane, client, model
runner, asking handler, vault or decryption, and from C9 not the planner
either, since it queues nothing
(`test_import_boundaries.py::test_the_harness_holds_no_key_and_reaches_no_client`);
and "never `src/cli.py`" is a machine rule: the research command line's whole
closure loads nothing from `src.programme`
(`::test_the_research_cli_loads_no_programme`, proved on a synthetic tree by
`::test_the_research_cli_scan_sees_the_programme_loaded`).

**End to end** (`tests/integration/test_jev_evaluations.py`). The programme's
loop as shipped — planner, drain, ingest, screen, catalogue, the two sets about
a model-written title, and the next UTC day's re-asks — writes a ledger
against a scripted vendor; two people's synthetic labels are imported and
five evaluations recorded through `jev_eval.main`, as an operator would; and
each row recorded equals its recomputation, column for column, with the counts
the script implies (eight excerpts, one quarantined by the screen and never
described, one tie, one escape: six valid, three agreeing with the person,
four with the README), no answer set apart, the README's evaluation an upper
bound, a title's dated by its hypothesis, and the flips each evaluation counts
what the re-ask jobs found. Seeded ledgers, and two whose threshold is chosen,
show that whatever `build_evaluation` computes 0014 admits and the repository
reads back exactly. The export is blind and ordered by address, and keeps the
excerpt the screen quarantined, for the screen and the catalogue alike; on a
database of its own, one excerpt quarantined by each of the three causes, in
the shipped code's words, shows the code screen's alone left out
(`TestTheCommandsOnPostgres::test_the_export_leaves_out_what_the_code_screen_flags_alone`);
a refused import records nothing; a copy carries labels only across the words
the lane recorded.

**Mutations.** Every new control was mutated and restored in turn, and each
mutation failed a test: the statistics, the calibration's reasons and
verdicts, the repository's reads and its one write, the harness's rules and
commands, and, on PostgreSQL, the read-only snapshot, the probe lane's
exclusion, the export's filter, the copy's word comparison, the import's
subject check, the jobs the plans are read from and the commit recorded, with
the two boundaries. Two first survived — a replay that re-dated its answer,
and a threshold searched on an upper bound, whose dry run nothing read since
the schema refuses the row — and their tests now catch them; one calibration
mutant was equivalent and was replaced. The first cut said the same of the
migration's rules, and it held only rule by rule: each named CHECK had a case,
but conjuncts inside them — an interval's outer end, one side of an
estimate's interval, a count's floor or ceiling, a member of the
at-threshold group — could each be deleted with every PostgreSQL suite green
(C9's review). Every conjunct no other rule implies now has a case breaking
it alone, and the migration was then mutated against those cases on
PostgreSQL, one mutant at a time: every conjunct removed, every range
halved, every group rule kept for all but one member or for one pair of
them, every equality kept on one side, each vocabulary widened and each
anchor dropped. 168 of 195 mutants failed a case; the 27 that survived are
the conjuncts other rules imply, named above, each equivalent to the rule as
written. Eighteen of the finer mutants — an
estimate alone, a difference with one of its counts, an equality's upper
side, a threshold's member where none was chosen — survived until the last
eighteen cases were written for them.

**Where C9 departs from the design and its scope.** Migration 0014 adds
`n_other_plans` and `n_plan_unknown`, so a row says how many items 10a set
apart rather than the report alone, and five CHECKs the design's list did not
name: the reporting level's range, an estimate carrying both its bounds, the
answer counts adding up, the counts outside n non-negative, and nothing
measured at a threshold without one; a flip rate is held present when its
pairs are, as well as absent when they are not, and the threshold's group
includes the test items measured at it. `evaluate` takes `--labelled-by`, the
scope's name, with the design's `--labeller` as an alias, and defaults to the
test split. `report` keeps the newest evaluation per labeller and split as
well as per set, version, key and model, so that one labeller's standing is
never shown for another's (10b). `usable` requires accuracy's lower bound
over every item, not only over the valid answers, above each baseline, since
an answer that abstains on the hard items can beat a baseline over the rest.
The Brier score of a Choice scales its distribution to sum to one, which the
validator allows to be off by 0.02. A percentile bootstrap interval that
misses its own estimate is widened to hold it, which 0014's rule requires and
a skewed few items can produce; never narrowed. `choose_threshold` takes the
development floor as an argument, `jev_stats` loading nothing. "Every item"
in the scope's rule for possibly in training is read as every item the
evaluation reads, the development split's included when the figures are the
test split's, since the threshold rests on them. The first cut read the
figures' items alone, and would have searched a threshold on an undated
development item beside a dated test split. Labeller
agreement is defined by the earliest other labeller's label, one comparison
per item, where the design said "items with ≥ 2 labellers" (open item 62).
`analysis_plan_hash` lives in `jev_calibration` rather than `jev_prereg`,
whose changes cost a released-hash row. `labels import` takes an `operator:`
name in lower case only, refuses an allow-listed source's name, a revised
label and an escape, and reads an optional `text` column to check the
address; `labels copy` reads an unregistered version's words from the ledger
(open item 61). The harness reads `GIT_COMMIT` for `--record`, beside C4's
`DATABASE_URL` (open item 66). And `jev_repo` has six reads beyond the
design's five functions, each named above.

C9's review moved four of the design's own choices, each toward refusing, and
each a finding the first cut met with its tests green. `usable` reads what the
held-out test split measured at the threshold (`held_out`), which design C9's
list left out. Jev beats a baseline by the exact one-sided sign test of the
items only one of the two got right, where design section 10.1 named the
paired bootstrap's bound at the gate level; the bootstrap interval is still
computed and reported, at the reporting level rather than the gate's, so
`ci_level` is every reported interval's level, as 0014 documents it, and the
gate's level is recorded beside it (`gate_ci_level`); the discordant items the
test reads are columns of their own, held to the difference by a sixth CHECK
the design did not name (`jev_evaluations_differences_from_their_items`). The
blind export leaves out the code screen's flags alone, where the design's
`--include-quarantined` implied every quarantine left out by default, since
some are answers. And a
row counts the re-asks it could not compare. Each is recorded under the plans
already registered: none moves a number of the plan, and the gate's level,
the target, the floors and the grid are the plan's as released; whether a
threshold should be refused when many re-asks could not be compared would be
one, and is left to a new plan version (open item 68). The planned
set-and-question pairs are held to `GATE_FAMILY`, the family `GATE_CI` is
Bonferroni over, by `tests/unit/test_jev_prereg.py::TestTheGateFamily`, since a
pair a set plan adds moves no hash of the global plan.

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
    to the follow-up, recorded as a change of the set's plan. *C9:* the
    harness measures it — covered precision of `true` beside the code screen
    v1 — and can arm nothing yet: every web excerpt is undated, so every
    evaluation of the screen is an upper bound and carries no threshold (open
    item 65). The blind export keeps the texts the screen quarantined, so a
    labeller sees its `true` answers (C9's review); the first cut left them
    out, and the screen could only have been measured on what it cleared.
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
    them. *C9, in part:* an evaluation is computed against exactly the
    labeller named on the command line, never pooled, and `report` lists each
    apart; choosing for each answer the page version in force when it was
    recorded is not built, so the operator names the version.
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
60. **A test set reused in part is not seen as reused.** `usable` refuses an
    evaluation whose test dataset, or whose threshold's development dataset,
    an earlier version's evaluation used, by comparing the two datasets'
    hashes. A new version measured on a test split that overlaps an earlier
    one's, one item added, passes. Seeing overlap needs each evaluation's items
    stored, which no table holds; the rows hold the hash alone.
61. **Labels are copied only from a version whose words are on record.** The
    words of a version live in code while it is registered, and afterwards
    only in the requests it was asked with, so `labels copy` reads them from
    the ledger and refuses a version that was never asked anything. Labels of
    such a version can be imported again.
62. **Labeller agreement is with the earliest other labeller.** Design
    section 10.1 said "items with ≥ 2 labellers". C9 compares each scored item
    once, with the earliest label another labeller gave it, a dataset's page
    versions counting as one labeller, so `labeller_agreement_n` is at most n
    and a dataset re-read many times does not outvote a person. Agreement among
    three or more labellers is not summarised.
63. **`n_contested` is always 0 for now.** The schema holds one label per
    labeller per item, and an evaluation reads one labeller, so no item it
    reads can carry two labels. The column is computed rather than assumed,
    and would mean something only if an evaluation pooled labellers, which C9
    refuses.
64. **The near-threshold flip rate draws on both strata.** Its pairs, within
    0.10 of the threshold, come from the uniform sample and the low-margin
    search alike, each also counted in its own stratum's rate. Drawn from the
    uniform stratum alone it would rest on a handful of pairs; drawn from both
    it leans toward the low margins, where flips are likeliest, which errs
    toward refusing a threshold.
65. **No web set can be calibrated on today's documents.** The ingest stores
    every document with `published_at` NULL (C6), and an undated item may be
    in the model's training, so every evaluation of the screen or the
    catalogue — a person's labels of the same excerpts as well as the
    README's — is an upper bound, and an upper bound carries no threshold.
    Calibrating the screen's line (open item 54) needs labelled web text with
    a known date after the model was first observed: a source that dates its
    documents, or text written after 26 September 2026. Titles the programme's
    model writes from now on are dated after it.
66. **A commit named by hand is trusted.** `evaluate --record` records the
    commit `--commit` or `GIT_COMMIT` names, checked only to be 40 lowercase
    hex digits; that the code running is that commit's is the operator's word.
    Without either, the repository's own HEAD is read, on a clean tree only.
    The harness reads `GIT_COMMIT` for this alone, beside `DATABASE_URL`; it
    holds no secret.
67. **Nothing reads a usable evaluation yet.** `jev_calibration.usable` is
    reported and consumed by nothing that acts: every lane stays
    suggestion-only and "not calibrated". Arming a threshold — the card check
    through `card_verdict`, the screen's line — is phase D's change, and must
    move the calibration across the boundary test that keeps it out of
    everything that acts.
68. ~~**`usable` does not read the re-asks that could not be compared.**~~
    *Closed by phase D1 (plan version 2, M5):* `usable` reads each flip rate in
    the worst case, every re-ask that could not be compared counted as a flip,
    `(flipped + not compared) / (compared + not compared)` within its limit on
    at least `MIN_FLIP_PAIRS` compared pairs (`jev_prereg.FLIPS_NOT_COMPARED`),
    so thirty valid pairs and thirty ties are refused where sixty valid pairs
    pass, and a row that does not say how many could not be compared is
    refused too. The rule is a number of the plan, registered by version 2
    while no answer existed, as this item asked
    (`tests/unit/test_jev_calibration.py::TestTheFlipLimitsReadTheWorstCase`).
    As first written: a row counts them, stratum by stratum and near the
    threshold (C9's review), and the text prints them beside each rate, but a
    flip rate over the compared pairs alone still decided the two flip
    conditions; a tie or an answer refused whole on a re-ask is itself
    unstable, and a rule counting them against a threshold would be a new
    number of the plan, a new plan version's to register.
69. **A percentile bootstrap over few items understates its uncertainty.** The
    Brier score's interval and each paired difference's are reported only, at
    the reporting level, and gate nothing: "beats" is the exact sign test's
    (C9's review). Over one item the interval has no width, and the n is
    printed beside it; a method with better small-sample coverage — Newcombe's
    paired interval for the differences, say — is a later change.
70. **The README's labels cover what was in use when each page version was
    read.** The ingest records the source's grouping only for content not
    quarantined at that moment (C6, C7+C8), so a page version first read after
    Jev's screen quarantined a title has no label for it: that labeller's
    population leaves out what the screen answered `true` about, a choice made
    by an answer. Its evaluations are upper bounds, every excerpt being
    undated, and arm nothing; a labeller that must not be chosen by answers is
    a person labelling from the blind export, which keeps such content.

### Phase D, as built

Phase D routes findings, triages failed jobs and arms the card check, as
`docs/09-jev-phase-d-design.md` designs it and its build scope binds it, in
four pull requests, each dark. Its first, D1, builds the foundations the other
three stand on, and calls nothing: it registers no question set, adds no job
kind, plans and asks nothing that phase C did not, and switches nothing on, the
arming switch it adds included. It touches nothing in the decision path, the
signals, the worker's order path, the engine or the three live-money gates.
Its second, D2, routes findings, behind the findings area, seeded off: it
registers two sets, asks them about titles the programme's model wrote,
records the answers and changes nothing with them. It adds no job kind, no
switch, no migration, no API route and no worker change, and touches none of
what D1 left untouched. Its third, D3, triages failed jobs, behind the ops area
and the detail switch, both seeded off: code places every error it can, and
the residue of a research or ingest job's error is sent as a skeleton the
redactor builds, to one set, recorded and changing nothing. It too adds no job
kind, no switch, no migration, no API route and no worker change, and touches
none of what D1 left untouched.

#### D1: plan version 2 and the foundations

**Plan version 2** (design section 3.2; the scope's 2a). The analysis plan is
re-registered while the ledger holds no answer, so the new version sets aside
nothing; version 1's hash,
`f744c2d88bded050e7b1b0fb946c9e29b502264d55ee6ac7c6a68b182daf7caf`, stays in
`tests/unit/test_jev_prereg.py`'s `RELEASED_PLAN_HASHES`, and version 2 hashes
to `5d3a7fbbdb804440e70e077c75f9c997454786a84024d5ef58afabcab8365844`
(`GOLDEN_PLAN_HASH`). What changed, each moving the hash:

- **R1, floors by statistic.** `STATISTIC_FLOORS` replaces `LANE_TARGETS`:
  covered accuracy at least 0.80, and covered precision of the acting class at
  least 0.90, each met by its one-sided Wilson lower bound at the gate level. A
  set plan may raise a floor and never lower it; a guardrail with an acting
  class is held to precision, anything else to accuracy.
- **R2, M3, the family and the looks.** `GATE_FAMILY` 20 set-and-question
  pairs and `MAX_LOOKS` 4 looks at the held-out items, counted per set, version
  and question across every model (`LOOKS_COUNTED_BY`, the identity
  `_gated_family` counts), so a new pin restores no look. `GATE_CI` is
  0.999375, written as a literal and held to 1 − 0.05/(20 × 4): one-sided
  Wilson floors now need 42 covered items all right for accuracy and 94 for
  precision, and the exact sign test eleven discordant items all one way.
- **M1, the split.** `DEV_SPLIT_TENTHS` 5: half the items search, half test.
- **M2, flips over the population.** A flip rate counts every canonical
  request of the question under the pin (`FLIP_PAIRS`), labelled or not;
  `build_evaluation` no longer drops a pair whose request answered no scored
  item, and 0015 frees the pair counts from `n`.
- **M5, the worst case.** A re-ask that could not be compared counts against
  the flip limits as a flip (`FLIPS_NOT_COMPARED`): `usable` reads
  `(flipped + not compared) / (compared + not compared)` as exact fractions, on
  at least `MIN_FLIP_PAIRS` compared pairs, and refuses a row that does not say
  how many could not be compared, or whose rate no count of its pairs could
  give.

**The regime's plan, apart** (M4; the scope's 2b). `REGIME_BASELINE_RULE` and
the reference sleeves left the global plan for one of their own:
`REGIME_PLAN_VERSION` 1, `regime_plan()`, `regime_plan_hash()` and
`GOLDEN_REGIME_PLAN_HASH`,
`2833a4c00d1a6b0adab46c6d6bf0e3544deae6dc1a964598a088162fc1b6af74`, with its
own released history in the test. A change to the rule or the sleeves is a
regime plan bump that sets aside no other lane's history. `jev_forward`'s
result gains `regime_plan_version` and `regime_plan_hash` beside the global
plan's, and `forward` scores agreement under the regime plan alone, counting an
answer recorded under another, or before D1 under none (plan unknown), apart;
`status` prints both plans. `tests/unit/test_jev_forward.py::test_the_result_names_both_plans`,
`tests/unit/test_jev_eval.py::TestTheRegimeReport`,
`tests/integration/test_jev_harness.py::TestTheForwardReportUnderTheRegimePlan`.

**Looks at the command line** (the scope's 2c). `evaluate --split` has no
default and takes `dev`, `test` or `all`. `test` and `all` read the held-out
items, so each is a look and is taken only with `--record`; `dev` scores the
development split's items alone — it reads no label or date of a test item and
scores none of its answers — and is never recorded. Its flip rates are the
population's (M2), as a look's are, since a flip uses no label: the re-asks of
test items are counted among them, and the first cut's claim that `dev` read
nothing of the test split was wrong (D1's review). Nor does its threshold line
promise that a look will bear the threshold out, as the first cut's did: the
look searches again only if every item it reads, the held-out ones included,
is dated after the pin was first observed, which a `dev` run does not read
(open item 83). The rule is `jev_eval.look_problem`, applied in
`jev_eval.execute`, which `main` and every caller of the commands reach,
before any connection is made, and it fails closed: it decides from the
command `jev_eval._command` names, which refuses anything but one of
`jev_eval.COMMANDS`, and it refuses a split that is not `dev`, `test` or
`all`, while `_read` dispatches on each command by name with no default. The
first cut held the rule to the literal `"evaluate"` and sent every reading
command it did not know to the evaluation, so a caller handing `execute`
arguments no parser makes — a command of `None`, mis-cased or padded, or
`labels` with no such subcommand — printed a held-out evaluation and recorded
no look (D1's review). `jev_calibration.usable` gains the `looks`
reason: an evaluation with `MAX_LOOKS` recorded looks of its set, version and
question before it, on the test split or every item, under any model, is
refused. `report` prints the looks each identity has spent.
`tests/unit/test_jev_eval.py::TestLooks`,
`tests/unit/test_jev_calibration.py::TestUsable` and
`::TestTheFlipLimitsReadTheWorstCase`; on PostgreSQL, a dry look at the test
split, and arguments no parser made, refused before anything is read
(`tests/integration/test_jev_evaluations.py::TestTheCommandsOnPostgres`).

**Migration 0015** (the scope's 2d) is described under the schema above, and
`tests/integration/test_phase_d_schema.py` holds it: every rule and every
conjunct no other rule implies broken alone and admitted with that rule
dropped, in a transaction rolled back after, the rules read from the catalogue
against a database at 0014, so a rule added without a case fails
(`TestEveryRuleBites`); the migration over 0014 holding findings and
evaluations, or failing whole (`TestTheMigration`); an insert naming no origin
failing on `NOT NULL` and not on a trigger's message, and `raise_finding`
writing the origin it is given (`TestOriginIsKnownFromNowOn`); each column but
the closure's refused, a closure admitted through `repo.close_finding`, a
reopen, a DELETE, a TRUNCATE and a candidate's cascading delete each refused
and the row read back (`TestWhatWasRaisedStaysRaised`); a Jev finding on a
missing request, a request in each other status, a probe, another set, under
another set's raiser, and on no valid `true` each refused alone
(`TestAJevFindingRestsOnItsAnswer`); `repo.JEV_REF_SQL` never cutting a ref at
1, 9,999, 10,000, 10,001 and 123,456 (`TestTheJevRefs`); `system` admitted on
`jev_requests`, refused by `jev_signals_provenance_check` and, as a signal's
claimed provenance on a `system` request, by the origin trigger
(`TestTheProvenances`); the arming switch read off through the shipped reader;
and flip counts above `n` admitted. The foreign key on `source_request_id` is
the one rule with no case of its own: a Jev finding's trigger refuses a
request it cannot see before the key is checked, nothing else names a request,
and the request cannot change.

**A finding's writer** (the scope's 2e). `repo.raise_finding(..., *, origin)`
takes `origin` keyword-only with no default, and refuses any writer but
`'model'` and `'operator'` before the connection is touched; the tick passes
`'model'` and the API `'operator'`, each a literal. `findings.origin` is the
API's one change, a literal on a write it already made.
`tests/unit/test_jev_table_boundaries.py` reads every write of `findings` in
`src/` and the protected entry points: every insert names its origin, every
update sets the closure's columns alone, no write is anything else, and the
two callers pass literals — each scan proved on sources that must trip it.
From D1's review the update scan reads a `SET` list to the `WHERE`, `FROM` or
`RETURNING` that ends it outside every parenthesis and string literal, where
the first cut stopped at the first of those words anywhere, a subquery's or a
literal's included, and missed every column set after it; and the caller scan
counts the writer taken by its name — the literal `"raise_finding"`, or the
`repo` module read by a computed name or as a namespace — as a call it cannot
read.
`test_programme_convene.py::TestThePanelSits::test_the_tick_raises_findings_as_model`
holds the tick's value, and `test_programme_gates.py::TestTheVeto::test_veto_roles_are_role_keys`
that no veto role holds a `:`, so a `jev:` raiser is never one.

**The title sets read by column list** (the scope's 2f).
`jev_repo.get_hypothesis_title` returns a hypothesis's ref, title, origin and
creation time and nothing else (`HYPOTHESIS_TITLE_COLUMNS`), and is the title
sets' `load` in place of `repo.get_hypothesis`, whose `SELECT *` handed every
title ask the card. `jev_jobs` no longer imports `repo`.
`tests/unit/test_jev_jobs.py::TestTheTitleProjection`,
`tests/integration/test_jev_repo.py::TestTheTitleRead`.

**Two registry rules, with no set under them yet** (the scope's 2g).
`jev_questions.STATE_ADDRESSED` maps a state model to the provenance every set
asking about it records, empty until D3's `{JobErrorState: "system"}`; for
such a subject the road holds the id to `jev_hash.state_hash` of the state
sent, before any switch is read, and registration refuses a model addressed
both by its text and by its state, one the detail rule cannot prove text-free
with no field exempted, and a set asking about one under another provenance.
`TEXT_FREE_LANES` is the ops lane: a set in it registers only declaring
`internal_detail`, with a state proved text-free and no field exempted, a
`title` included, and `dump_state` reads what every ask of it would send, no
title exempted, whatever it declares. `system` joins the provenance vocabulary
and the provenances read as this system's own text. Each rule is proved with
test-only sets and a stand-in for D3's state:
`tests/unit/test_jev_questions.py::TestStateAddressedSubjects` and
`::TestTheTextFreeLanes`, and
`tests/unit/test_jev_lane.py::TestSubjectsAreContentAddressed::test_a_state_addressed_subject_is_refused_before_any_switch`.

**The arming switch** (the scope's 2h), under the switches above.
`tests/unit/test_jev_flags.py::TestTheReadersReadTheSeededKeys` holds the keys
to the seeds of 0012 and 0015, and `::TestTheArmingSwitch` that it is on only
for a stored JSON `true`, reads its own key and no other, is seeded off by 0015
and, in D1, is read by nothing outside `flags`.

**The shares** (the scope's 2i): research 25, guardrail 25, findings 10, ops
10, signals 0, decision 20, probe 10; the minimum budget is still derived, and
still 10; a refused budget's message names the lanes with the smallest share,
read from the table (`jev_catalogue.smallest_shares`).
`tests/unit/test_jev_catalogue.py::TestTheShares`.

**The detail switch in the planner** (the scope's 2j). A set declaring
`internal_detail` is planned only while `jev_send_internal_detail` is on, read
through its own reader (`jev_plan._detail_allows`), for an ask, a re-ask and
the forward clock alike; a set declaring none reads no switch for it.
`_plan_asks`' screen-only hold exception is word for word as it was.
`tests/unit/test_jev_plan.py::TestTheDetailSwitchGatesPlanning`, with a
test-only set.

**What Jev's code reaches** (the scope's 2k; design section 9.2). Two walks
with `test_jev_jobs.py`'s `_Reach`, from every root on the Jev side that acts —
each `JEV_HANDLERS` handler, each `ASKABLE` set's `load`, `admit`, `build` and
`follow_up`, and the planner, read from the objects themselves — and one scan:

- `test_jev_table_boundaries.py::test_the_jev_side_never_reads_detail`, the
  harness's commands among its roots, refuses any reachable SQL that reads `*`
  from `hypotheses`, `findings` or `role_assessments`, or names a detail column
  of them (`card`, `decision_rationale`, `detail_md`, `remediation`,
  `close_note`, `summary`, `evidence`) in a SELECT or a RETURNING; it trips on
  handlers calling `repo.get_hypothesis` and `repo.list_findings`. From D1's
  review it judges every statement that reads one of the three, whatever its
  first word once comments and parentheses are read past — an `INSERT …
  SELECT`, an `UPDATE … FROM`, a `DELETE … USING`, a `COPY (…) TO` — finds a
  table after a comma in a `FROM` list and as the `TABLE` shorthand, counts a
  table read as a whole row (`to_jsonb(h)`, `SELECT f`, `(f).*`) and a table
  copied whole (`COPY t TO`, asyncpg's `copy_from_table`) as reads of every
  column, refuses a column list it cannot read (interpolated, or a `%` or
  `str.format` placeholder) on a table it reads, and treats a table it reads
  but cannot name (`FROM {table}`) as any of the three. A module's string
  constant interpolated into a statement is read as its text, comments and
  string literals are read past, and docstrings and other prose are not
  statements. The first cut judged only statements whose first word was
  `SELECT` or `WITH`, found a table only after `FROM`, `JOIN`, `INTO` or
  `UPDATE`, and read no whole row and no column list it could not read.
- `::TestWhatJevCodeCanWrite::test_exactly_these_writers` finds exactly the
  allow-listed `(table, writer)` pairs: `jev_requests` and `jev_answers` from
  `jev_repo.record_request` and `record_answers`, which `record_exchange` alone
  calls; `jev_signals` from `jev_lane.record_signal`; `web_documents` from
  `insert_documents` and `quarantine_content`; `jev_labels` from
  `record_label_once`; and `jobs` from `enqueue`. It runs the shared scanner
  for a table wherever the texts that scanner reads name it, case aside; the
  first cut looked for the table's lower-case name in a module's raw text,
  and so never looked for a write named in capitals or split across `+` or
  `str.join`, which the scanner reads (D1's review).
- `::test_nothing_in_the_programme_writes_a_switch` and
  `test_job_ownership.py::test_nothing_in_the_programme_changes_a_job_it_did_not_claim`:
  no write of `system_flags` and no reference to a switch's writer anywhere in
  `src/programme`; and no state-changing queue call there but the loop's claim,
  completion, failure and lease of what it claimed and the planner's and the
  tick's `enqueue`, never `requeue_expired`. From D1's review the switch test
  also walks everything each programme module reaches with `_Reach`, so a
  switch written through a wrapper it imports — the API's `set_enabled` and
  `set_autonomy` routes call `set_flag`, and no boundary keeps the programme
  from importing them — is a write the walk finds; and the queue scan also
  refuses the queue's module, or a package holding it, used as a value, its
  `__dict__`, a name loader loading it, a star import of it, and a changer's
  name handed to `getattr`, `attrgetter` or `methodcaller` on anything else,
  as the enqueue scan always has.

**The tests D1 moved** (the scope's 2l), re-derived by running both suites on
this build: the 86 unit cases design section 13 listed, in the eight files it
named, with `test_jev_prereg.py` rewritten; and its 31 integration cases in four
files, `test_programme_panel_atomicity.py`'s clean-up now retiring its
candidate and leaving its findings, and `test_a_dry_run_records_nothing` a
`--split dev` dry run. The table missed one, by the way the seeded switches are
held: `test_jev_schema.py::TestTheMigration::test_it_applies_on_top_of_a_database_already_at_0011`
compares the switches at 0012, so it reads 0012's seeds (`SEEDED_BY_0012`)
while every other case reads them with 0015's. Two cases the table listed
needed nothing: `test_a_chosen_threshold[precision]`, whose fixture grew with
the unit builder it shares, and the two hold tests of `TestTheAsks`, as the
design said.

**Where D1 departs from the design and its scope.** The ledger's writers in
the write walk are `record_request` and `record_answers`, the definitions the
SQL is in, where the design names `record_exchange`, their one caller.
`raise_finding` also refuses any writer but `'model'` and `'operator'`, so
`'jev'` can come only from D4's own writer. `repo.JEV_REF_SQL`, the `J-` ref
expression, lands in D1 with no user, because design section 13 tags
`TestTheJevRefs` D1 while the scope places its writer in D4. The planner's
detail rule covers the re-asks and the forward clock as well as the asks,
reading "the planner's one general rule" as the planner's. `report` prints the
looks spent from D1, since D1 is where looks start to count. `usable`'s
worst-case flip rule also refuses a rate no count of its pairs could give. The
integration split test's expectations were re-derived under five tenths rather
than its fixture's titles re-chosen. 0015 carries a header saying why, above
SQL identical to the design's.

**D1's review.** Fifteen findings, each checked against the code and each
real; every one is fixed with a test that failed before it, recorded beside
what it changed above, or below as an open item:

- the harness's command line fails closed: `execute` refuses a command or a
  split no parser makes, where the first cut evaluated any command it did not
  know (looks at the command line, above);
- a `dev` run promises no look its threshold cannot have, and says that its
  flip rates are the population's, as a look's are (looks at the command
  line, above, and open item 83);
- the four boundary scans read the spellings they missed: the write walk a
  table in capitals or split across `+` or `str.join`, the detail walk every
  statement reading a guarded table, whatever its first word, its comma joins
  and whole-row reads, and its column lists it cannot read, the switch test
  everything the programme reaches, the queue scan the queue held as a value
  or looked up by name, the findings-update scan a `SET` list past a subquery
  or a literal, and the caller scan `raise_finding` taken by name (what Jev's
  code reaches, and a finding's writer, above);
- two tests now bind what they claimed: the text-free check is tested without
  the declaration and under a provenance the detail rule does not read, and
  two flip cases ask rates their pairs can give, so the limit refuses them;
- three passages that still stated what D1 changed now say what it is: C4's
  rule and sleeves are a `REGIME_PLAN_VERSION`'s, C9's `evaluate` row says
  `--split` has no default and a look needs `--record`, and open item 68 is
  closed by M5.

#### D2: findings routing

D2 asks two question sets about the title of every finding the programme's
model raised, behind the findings area, records each answer and changes
nothing with it; builds the chips phase E may show beside a finding; and gives
the harness the finding title as a subject, `preview` and `suggestions`. The
findings area is seeded off, so the shipped loop, as seeded, plans, claims and
asks nothing new. No answer writes a finding, a hypothesis, a candidate, an
assessment, a label or a switch.

**The sets and their words** (the scope's 3, first and second points; design
sections 2.2, 2.3 and 2.6). `FindingTitleState` holds a title of 1 to
`FINDING_TITLE_MAX_CHARS`, 200 characters, and nothing else, closed and
frozen; 200 is `roles.ProposedFinding.title`'s `max_length`, the most the
panel's model may write, and a test holds the two equal. Its subject is
`finding_title`, the sha256 of the title, written by the programme's model
(`TEXT_SUBJECT_PROVENANCE`), so every set asking about one records `model`.
`findings.owner` v1 asks `owning_role`, the twelve roles in `roles`' order,
each by what kind of defect falls in its area and never by who may veto or
close, then `unclear`; `findings.severity` v1 asks `severity`, the panel's
four levels, then `insufficient_evidence`. Both are word for word as design
2.2 and 2.3 give them, lane `findings`, provenance `model`, and re-pinned from
the registered words they hash as the scope gives: packs
`7e97f8b11d80494d5ecb978bc04240226229993d2f73617b1fccdf7ea4437c8c` and
`a9cae8cdafff291715982ea74dc3fe05f3e0da1ba8ffdd03cc428df585e830e0`, questions
`2989fecdce44b1ff9bd1c216b5eb1f33bbc76fc15427403e83defac412239ff3` and
`0504d4817b84e44db3fc268f4d64bfd0d4d0e4ec62856f84595ccd9bab08db9e`. The
registry is eight sets, and the released pack and question histories gain
their rows. `tests/unit/test_jev_questions.py::TestTheFindingTitle`, and
`::TestTheRegistry`'s `test_the_title_cap_is_proposed_findings`,
`test_the_owning_role_options_are_the_twelve_roles` and
`test_the_severity_options_are_the_findings_severities`.

**Their plans** (the scope's 3, third point; design section 3.4). Each set's
plan holds covered accuracy to the 0.80 floor with no acting class, and
registers the baseline the measurement proposal argued for: `findings.recorded`,
the value already recorded — who raised the earliest model-written finding
holding the title, for the owner, and the severity it was raised at, for the
severity — the earliest by `opened_at`, then `ref`. Neither value is ever
exported to a labeller. Each plan also names the population it is asked
about: findings of origin `model`, any status, a title of 1 to 200
characters, addressed by the sha256 of the title (`FINDINGS_POPULATION`).
They hash to `e6cb5e05456468a9447b5748a3f09900a4893a5096cea6b0e98c445de05e09e9`
and `256b20e7cf141417af8bb71e4aeaca4b793d4ef1eedb947ec41db96bf30fcca2`, in
`GOLDEN_SET_PLAN_HASHES` and the released history. `keyword_label` gains its
`fallback`, read at call time and recorded in each plan that uses one; every
phase C plan keeps `insufficient_evidence` and its hash. The harness measures
a keyword baseline with the fallback its plan recorded, and refuses a plan
that records none; the first cut applied `KEYWORD_FALLBACK` whatever the plan
said, which moved no figure only because every plan's fallback is that
constant (D2's review;
`tests/unit/test_jev_eval.py::TestTheBaselines::test_a_keyword_rule_falls_back_as_its_plan_registered`).
The gated family is eight pairs of twenty.
`tests/unit/test_jev_prereg.py::TestTheFindingsBaseline`,
`::TestTheKeywordFallback` and `::TestTheGateFamily::test_the_family_holds_phase_ds_pairs`.

**The ask** (the scope's 3, fourth point; design section 5.1). `ASKABLE`
gains both sets. They load through `jev_repo.get_finding_title`, a finding's
`ref`, `title`, `origin` and `opened_at` and no other column. They admit a
finding only when the programme's model wrote it, and a title only within
its cap, refused by the cap before any state is built and never by pydantic;
each refusal fails the job for good, names the finding by its ref and quotes
nothing. The state is `FindingTitleState(title=…)`, dated by `opened_at`, and
neither set has a follow-up: an answer is recorded and changes nothing.
`tests/unit/test_jev_jobs.py::TestTheFindingAsk` and `::TestASKABLE`;
`test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall::test_every_askable_set_makes_at_most_one_call`,
every road outcome through each findings set.

**The planner** (the scope's 3, fifth point; design sections 5.2 and 5.3).
Each set behind the findings area, at most ten a pass, one call each from the
findings share, under `jev_ask:findings.owner@1:finding_title:{sha}:{UTC date}`
and its severity twin. `jev_repo.findings_to_ask` returns the distinct
titles of model-written findings, whatever their status, of 1 to 200
characters, by content address computed in SQL, newest first by `opened_at`
then `ref`, each with the newest finding holding it, and never a title with
a content block on record, answered `ok` or retired under the pin, or waiting
or planned today. A block counts whichever title recorded it: a finding's
title and a hypothesis's holding the same words are sent as one state,
`{"title": …}`, which the road holds a block by the hash of, across every set
(`jev_lane`, step 4), so `findings_to_ask`, C8's `hypotheses_to_ask` and
`ask_outcomes` read a block across the subject types sent as the same state,
`jev_questions.same_state_subjects`, and an excerpt of the same words, another
state, holds neither. The first cut read a block on its own subject type
alone, and a test pinned it: a block on a hypothesis's title left the finding
holding its words planned every UTC day, each job refused by the road before
any call and never retired, since a refusal writes no row, while `preview`
listed the words as about to leave and `suggestions` said "not asked yet" —
and the other way round for C8's title sets (D2's review). The authentication
and 422 holds stand, and the detail switch is not read for either set.
`tests/unit/test_jev_plan.py::TestTheFindingsRules`
and `::TestTheSwitchMatrix`, all 256 cases of the programme, Jev, the
findings, ops and guardrails areas, the arming and detail switches and a key,
built up from D2; `tests/integration/test_jev_repo.py::TestTheFindingTitleRead`
and `::TestFindingsToAsk`, each filter held by a case only it refuses; and,
for the block, `tests/unit/test_jev_questions.py::TestTheSubjectsSentAsOneState`,
which holds `same_state_subjects` to the hash of what each registered set
sends, `test_jev_repo.py::TestHypothesesToAsk` and `::TestWhatSuggestionsReads`
each way round, and
`tests/integration/test_jev_findings.py::TestABlockOnTheSameWordsHoldsBothTitles`,
the planner, `preview` and `suggestions` end to end on rows the shipped jobs
wrote.

**The chips** (the scope's 3, sixth point; design sections 6.1 and 6.4).
`jev_chips` is pure, the standard library alone, and API-importable
(`PURE_PROGRAMME_MODULES`). A chip is labels and numbers — a role, a severity
or a ref, the answer's probability and margin, the set version, the
answering model and its request, and whether code or Jev made it — and never
a title. `severity_chip` appears only where a valid suggestion is more serious
than the severity recorded (M5). `route_chip` names one of the twelve roles,
and on a finding that blocks only a role in `VETO_ROLES` (M24, D-SAFE-3); the
escape and an answer that was not valid make no chip. `duplicate_chips` is
code's, by exact normalised title (NFKC, case-folded, whitespace collapsed),
from a newer finding to the earliest older one on the same candidate that
blocks at least as much, so closing every finding a chip marks unblocks
nothing (M4). Each property is held by case and over seeded random
registers, whether a finding blocks judged by `gates` itself
(`tests/unit/test_jev_chips.py`). Nothing in D shows a chip.

**The harness** (the scope's 3, seventh point; design sections 3.7 and 9.3).
A finding title is a labelled subject (`LABELLED_SUBJECTS`). It is dated by
the earliest `opened_at` among the population's findings holding it, and its
text and its labelling population are read over the same rows, so a title
only an operator's finding holds is no subject. `findings.recorded` answers
each item from `jev_repo.finding_records`, which only the harness reads, and a
plan naming another order or writer, or an item no finding of the population
holds, is refused rather than guessed. Two commands read, each in the
harness's read-only snapshot, loading no planner, lane or client:

- `preview --set S [--limit N] [--json]` prints what a title set — the two
  findings sets, the hypothesis categories and the card check — would be
  asked about on the day: the planner's own read, each subject with the row
  it comes from and the exact state that would be sent, or why nothing would
  be, quoting no text — the handler's refusals, and the two the road makes
  before any call that the planner does not foresee: the day's budget spent,
  whatever a lane's share has left, and a state over the size limits under
  `jev_max_state_tokens`, read through its own reader, which refuses every
  request at 0, what a setting nobody can read reads as. The first cut read
  neither, and printed "would send" for a state the road would refuse under
  a limit of 0 (D2's review;
  `tests/unit/test_jev_eval.py::TestPreview::test_a_state_the_road_refuses_for_its_size_is_not_shown_as_sent`
  and `::test_a_spent_day_is_named_for_each_subject`). It prints every
  switch the planner reads for the set, the pin, the plans, the holds, the
  lane's calls left, the day's budget and spend and the state limit. The
  planner's and the handler's rules are copied, since the harness may load
  neither, and `tests/integration/test_jev_findings.py::TestPreviewIsThePlanners`
  holds the subjects equal to the planner's, in order, and every state equal
  to the one the handler hands the road, on the same rows, for all four title
  sets.
- `suggestions [--json]` prints, for each open finding but Jev's, by its ref,
  how each findings set's ask came out — answered, invalid, held by a content
  block, retired, waiting, or not asked and why — with the switches, the pin
  and the holds; never a title, an option, a probability or a chip, since
  anyone who reads it may later label a set (D-HMB-04). With no usable pin
  the asks, which are read under the pin, are not read at all, and a finding
  a set does ask about reads "unknown", the header saying why; the first cut
  printed "not asked" there, a negative fact where nothing was read, which an
  answer on record from before the pin went contradicts (D2's review;
  `tests/unit/test_jev_eval.py::TestSuggestions::test_with_no_pin_nothing_is_read_and_nothing_is_said_of_it`).
  What a finding's own row decides — its writer, its title's length — is
  said whatever the pin. Jev's findings are counted, never named. Its reads, `open_findings`, `jev_findings_raised` and
  `ask_outcomes`, read no option, probability or margin, and each filter is
  held on PostgreSQL by a case only it refuses
  (`tests/integration/test_jev_repo.py::TestWhatSuggestionsReads`).

`tests/unit/test_jev_eval.py::TestTheNewSubjects`, `::TestTheRecordedBaseline`,
`::TestTheExportStaysBlind`, `::TestPreview` and `::TestSuggestions`;
`tests/integration/test_jev_repo.py::TestTheFindingTitlesAHarnessReads`.

**What holds it** (the scope's 3, last point; design section 13):

- the findings canary (`tests/integration/test_jev_findings.py::TestTheCanary`):
  markers planted in a finding's detail, remediation and close note, an
  assessment's summary, and the titles of an operator's finding and of one
  raised before 0015 named its writer stay in their own columns once the loop
  has asked about every finding it may, every text and JSON column of every
  table read from `information_schema`; a model-written title is found in
  `findings.title` and `jev_requests.state` alone; and no marker is in a log
  record at DEBUG or in a job's payload, result or error. Beside it, only
  model-written findings are asked about, whatever their status
  (`::TestOnlyModelFindingsAreAsked`); the register, the hypotheses, the
  candidates and the assessments are unchanged under an answer, a timeout, a
  response refused whole, a content block, a 422 and a refused key
  (`::TestAFindingIsUnchangedByEveryOutcome`); and one title held by two
  findings is asked once by each set and replayed with no call
  (`::TestAskedOnceAndReplayed`);
- what leaves (`tests/sdk/test_jev_findings_ops_over_http.py`): a
  model-written title asked by both sets through the planner, the handler,
  the lane, the real client and SDK and real HTTP to the fake TypeSafe
  server, each request's state exactly `{"title": …}`; an operator's finding
  asked nothing; and the title raised again replayed with no request leaving;
- the dark matrix (`tests/integration/test_jev_dark.py`): seeded, a finding
  stored while dark is asked nothing; the switch matrix gains the findings
  area, the findings sets asking about a model-written finding exactly when
  the programme, Jev and the findings area are all on, and never about an
  operator's; and the ops area, the detail switch and the arming switch, with
  no consumer yet, plan and send nothing of their own;
- the evaluation (`tests/integration/test_jev_evaluations.py::TestTheFindingsSetsEndToEnd`):
  a ledger the loop and the next day's re-asks wrote, synthetic labels
  imported and each set's evaluation recorded through `jev_eval.main`, each
  row equal to its recomputation; `findings.recorded` reading the earliest
  model-written finding holding a title, never a later one and never an
  operator's; and the flip rates counting the population's pairs, six of
  them of titles nobody labelled, so a flip count exceeds `n` (M2);
- the walks: `test_jev_table_boundaries.py::test_the_jev_side_never_reads_detail`
  covers the findings sets' `load`, and a new scan,
  `::test_the_ask_side_never_reads_what_the_findings_baseline_reads`, holds
  every root that asks to reading neither `raised_by` nor `severity`, so no
  answer can echo the value it is measured against, proved on synthetic trees.

Every new control was removed in turn and a named test failed. That claim
was first made with four controls holding it falsely, each of which D2's
review removed with every test still passing: the cap on the dates read for
a finding title, the subject-type filter on `ask_outcomes`' block, `preview`'s
reason for a set with no plan in force, and `suggestions`' 422 hold. Each now
has a case that fails when it is removed:
`test_jev_repo.py::TestTheFindingTitlesAHarnessReads::test_a_model_title_outside_the_cap_is_undated`,
`::TestWhatSuggestionsReads::test_a_block_holds_what_the_road_holds`,
`test_jev_eval.py::TestPreview::test_a_set_with_no_plan_in_force_is_planned_nothing_and_says_so`
and `::TestSuggestions::test_each_hold_is_read_for_its_own_set_and_named`.

**Where D2 departs from the design and its scope.**

- `Askable.address` (design 5.1) is not added. The text sets' check, the
  sha256 of the text before `admit`, covers the findings sets unchanged; the
  hook is D3's, whose skeleton is addressed by its state.
- `preview` shows the title sets alone and refuses a web set. A web set's
  subjects are chosen by the injection screen's own answers — the content it
  cleared, for the catalogue, and the content its `true` is on record for, for
  the screen's repairs — so listing them would show those answers to someone
  who may label the set (open item 84). D3 adds the job-error skeleton.
- The duplicate chip is held to more than design 6.4's sentence. The older
  finding must also be open wherever the newer one is open, and recorded at
  least as serious, so closing every finding a chip marks leaves every title
  held by an open finding at least as serious, as well as every candidate
  held as it was; a finding on no candidate gets no chip. The property test
  checks the titles too, since the mutation check found that it passed with
  the open rule removed.
- `jev_chips` copies `VETO_ROLES`, the blocking severities, the severities and
  the role keys from `gates` and `roles`, which load pydantic, a module the
  pure set may not load; `TestTheCopies` holds each copy equal to its
  original, and `blocks` to `gates.FindingFact.blocks` on every combination.
- Test names in the binding list that this build spells otherwise:
  `TestTheSetPlans::test_released_rows` is the existing
  `TestTheSetPlansAreTheirReleasedHashes`, whose released history gains the two
  rows; `TestTheGateFamily::test_the_gated_pairs_fit_the_family`'s count is
  eight in D2, pinned pair by pair by `::test_the_family_holds_phase_ds_pairs`,
  and nine from D3; and `TestWhatAnAnswerMayChange` is still
  `TestTheCardCheckChangesNothing` until D4 renames it, its walk from
  `jev_jobs` covering the findings entries and finding no writer.
- The SDK case holds the finding half of `test_jev_findings_ops_over_http.py`;
  the skeleton half is D3's. It needs a database as well as the SDK, which
  CI's `programme sdk` job has.
- The dark matrix gains the findings area as a dimension, 64 cases. Ops, the
  detail switch and the arming switch join it with their consumers in D3 and
  D4; until then one case turns all three on beside every other switch and
  finds nothing more planned or sent, and the planner's unit matrix covers
  every combination of all seven.
- One commit of the pull request, `078c133`, registered the findings plans
  before the harness admitted their subject, and fails
  `test_jev_eval.py::TestWhatEvaluateRefuses::test_every_planned_question_may_be_evaluated`;
  the next commit mends it. A bisect should step over it.

**D2's review.** Seven findings, each checked against the code and each
real, two of them the same defect found from two sides. Each change to the
code but a comment's has a case that failed before it, and each case added
to hold an existing control fails when that control is removed. Each is
recorded beside what it changed, above, or below as an open item:

- a block on the same words holds both titles: a finding's title and a
  hypothesis's holding the same words are one state, which the road holds a
  block by the hash of, while the planner's reads, `preview` and
  `suggestions` read a block on their own subject type alone, so the other
  kind's asks were planned every UTC day, each refused for good and never
  retired, and a test of the first cut pinned it (D2RS-1, D2RT-1; the
  planner, above, and `jev_questions.same_state_subjects`);
- `preview` reads the state limit, as the road does, and says nothing would
  be sent where the road would refuse a state for its size, a limit of 0 or
  one nobody can read included; and, beyond the finding, the day's spend,
  which the road refuses on whatever a lane's share has left (D2RW-1; the
  harness, above);
- `suggestions` says "unknown" for a model-written finding when no usable pin
  is set, since nothing is read without one, never "not asked" (D2RW-2);
- the harness measures a keyword baseline with the fallback its plan
  recorded, and refuses a plan that records none (D2RW-3; their plans,
  above);
- four controls no test held now have a case each, and every control this
  review touched was removed in turn and caught by a named test, fourteen in
  all (D2RT-2; what holds it, above);
- the comment above `jev_repo._FINDING_ADDRESS` says which reads take the
  findings sets' population and which, `open_findings`, does not (D2RT-3);
- and, found while fixing the first, the re-ask planner reads no block at
  all, so a re-ask the road refuses unrecorded can be drawn, and the flip
  rates count it neither way; which pairs they should count is the plan's
  to decide (open item 85);
- found while running the suites, C4's
  `tests/integration/test_jev_forward.py::TestTheClockThroughTheLoop::test_planned_claimed_asked_once_and_recorded_once`
  failed for ten minutes of every session, from today's collection to its
  cutoff, at D1's base as at D2's: the planner also plans today's session
  then, due at once and in the test's state, and the drain asked about it
  first, so the session the test names replayed its answer. The test now
  holds any other regime job back a day, and passed inside that window.

#### D3: ops triage

D3 places every failed job's error it can by code first, and asks one question
set, `ops.job_error`, about the rest: the error of a failed research or ingest
job that code's table cannot place, sent as a skeleton the redactor builds and
nothing else, behind the ops area and the detail switch together. Each answer
is recorded and changes nothing. Code's chips for reconciliation, data health
and the ingest label structured rows and are never sent. The harness gains the
job error as a subject, and `preview` and `suggestions` their jobs half. The
ops area and the detail switch are both seeded off, so the shipped loop, as
seeded, plans, claims and asks nothing new. No answer writes, retries, resumes
or cancels a job, or writes a finding, a hypothesis, a candidate, a label or a
switch. The scope asks that D3 be reviewed as this system's own text leaving
it for the first time.

**The redactor** (the scope's 4, first and second points; design sections 4.2
and 4.3). `jev_redact.skeleton` reduces an error, its first 4,000 characters
(`MAX_INPUT_CHARS`), to at most 48 tokens (`SKELETON_MAX_TOKENS`): the words of
a closed vocabulary of 393, the exception names and the HTTP tokens, in order,
and for everything else one of twelve placeholders saying what kind of thing
stood there — a number, an identifier, a name, another word, a date, a time,
an address, a path, quoted text, a setting's value, a credential, or words left
out at the end — never what it was. Placeholders are taken before the split,
in square brackets; rules 0 to 16 run in order; runs are collapsed, the
skeleton is cut to 47 tokens and `[more]`, and runs are collapsed again, so it
is idempotent. It is pure, the standard library alone
(`PURE_PROGRAMME_MODULES`), total, and never raises. The vocabulary holds at
most 400 words, none a job kind outside `TRIAGED_KINDS` or a table's name;
every underscore part of every word and HTTP token, and every capital-split
part of every exception name, is held to `NEVER_IN_VOCABULARY`, 79 words; and
every word alone and every ordered pair is read by the code screen's
instruction rules, rule by rule, and trips none. The vocabulary, the never
list, the placeholders and the rules hash to
`e7742dcfc1b4ebafb2ab87e595fb8a9fce67a8dc540bdca39a63fb05330984e9`
(`redactor_sha256`, pinned by `GOLDEN_REDACTOR_SHA256`), with an append-only
released history kept in the test. `tests/unit/test_jev_redact.py`: total,
closed, bounded, deterministic across hash seeds and idempotent over a seeded
fuzz of 10,000 inputs; no synthetic credential or identifier survives in any
of 36 marked forms and 30 templates, and swapping one for another of its
shape changes nothing; one case per rule; this system's own raise sites in
the triaged modules pinned skeleton by skeleton; every hashed attribute moves
the hash.

**Code first** (the scope's 4, third point; design sections 4.5 and 4.6).
`jev_chips.code_cause` places an error by `JOB_ERROR_SHAPES`, 82 shapes read in
order, the first match deciding: the queue's own whole messages first, then
the triaged kinds' raise sites, the data sources', the venues', every error a
programme handler fails its job with and the ops ask's own refusals, and a
SQLSTATE last, so a quoted SQLSTATE never outranks the message quoting it. It
returns one of the ten causes Jev may also name (`CAUSES`) or of the five
only code does (`CODE_ONLY_CAUSES`: `switched_off`, `expired`,
`held_by_design`, `needs_review`, `unclassified`); `unclassified` for any
other kind's error no shape places, and for a value that is not text; and
`None` only for the error of a triaged kind — `backtest`, `walkforward`,
`ingest_bars`, `ingest_reference_bars` — that no shape places: the residue,
the one thing Jev may be asked about. `residue_skeleton` is the one rule that
turns an error into what may be sent — code's cause `None`, then the
redactor, then at least three words of content (`jev_redact.admissible`) —
and the planner, the handler's admission, the harness and the reads beneath
them all read by it. The table is version 2 and hashes to
`0ce6cdc62fbbbfe20ba80fa5f268157f6a21f838687fc8657bf8f4a84aa474d8`
(`GOLDEN_SHAPES_SHA256`), version 1's hash kept in the released history.
`reconciliation_chip`, `data_health_chips` and `ingest_chips` label structured
rows code computed, by labels alone, and are never sent. `jev_chips` loads
`jev_redact` and nothing else of the programme.
`tests/unit/test_jev_chips.py::TestCodeFirst` holds the table to the code —
every literal raise of the triaged modules and of `src/data`, every
pass-through raise in a reviewed list, every ask, re-ask, regime and probe
verdict, every `JobFailedError` a handler spells and every fetch failure
kind, each placed by the shape pinned for it, and every venue shape live on
a message a venue module writes — and
`::TestCodeFirst::test_code_cause_is_none_only_for_triaged_residue` holds
`None` to the residue over the redactor's fuzz; `test_job_ownership.py::TestEachKindHasOneOwner::test_triaged_kinds_are_the_workers_and_no_others`
holds the triaged kinds to the worker's own and keeps them apart from the
venue kinds, the shadow replay, the programme's kinds and the kill switch's.

**The state** (the scope's 4, fourth point; design sections 2.1 and 3.5).
`JobErrorState` is a triaged kind, a `Literal` of `TRIAGED_KINDS`, and 1 to 48
tokens, each a `Literal` of `jev_redact.TOKENS`: every value written in code,
so the detail rule proves it text-free with no field exempted, as the ops lane
requires. Its subject, `job_error`, is addressed by the state itself:
`job_error_subject` is `jev_hash.state_hash` of the state as sent, and
`STATE_ADDRESSED` is `{JobErrorState: "system"}`, so the road holds an ask's
subject to the state sent and registration holds every set asking about it to
provenance `system`. `job_error_text`, `"{kind}: {tokens}"`, is the subject's
text as the harness exports it and the baseline reads it, and
`job_error_from_text` reads a text back to the one state it names, or `None`.
`tests/unit/test_jev_questions.py::TestTheJobError` and
`::test_job_error_text_round_trips`, over the redactor's fuzz.

**The set and its words** (the scope's 4, fifth point; design sections 2.4 and
2.6). `ops.job_error` v1 asks `cause`: the ten causes of `jev_chips.CAUSES`,
then `unclear`, about a failed job's kind and its error's skeleton, the
placeholders' legend and the skeleton's bound rendered from `jev_redact`'s
constants, so moving either moves the pack hash. Lane `ops`, provenance
`system`, `internal_detail` declared. Word for word as design 2.4 gives it, it
hashes as the scope gives: pack
`1e625e8f0965342d12907dbc27fb78e66db44086bb0b6428359c8ab9c512b512`, questions
`e24fe30799ea8252dd3eac4dba6df02cb7fd9a0aaf4d4d11007fedc7df6a617a`. The
registry is nine sets, and the released pack and question histories gain
their rows. `tests/unit/test_jev_questions.py::TestTheRegistry`,
`::test_the_cause_options_are_jev_chips_causes` and
`::test_the_skeleton_bound_and_legend_are_rendered_from_jev_redact`, run with
each constant moved.

**Its plan** (the scope's 4, sixth and seventh points; design sections 3.4 and
3.7). Covered accuracy at least 0.80, no acting class. The baseline is
`keyword_label` over the subject's text, `job_error_text`, falling back to
`unclear`, by `OPS_KEYWORDS`, every keyword held to an evidence corpus of
real messages a triaged job can record and code leaves to Jev, admissible:
the builtins' messages triggered in the test, operating-system errors by
errno, PostgreSQL's as asyncpg's classes raise them, and numpy's and pandas'
own. A keyword no message produces is dropped, and the code-defect label comes
before `data_missing`. `OPS_POPULATION` names the population: failed jobs of
the triaged kinds, finished after the UTC day the pin was first observed, left
to Jev by `code_cause`, admissible, each skeleton dated by the earliest
`finished_at` of those same rows, with the redactor's and the shapes table's
versions and hashes, so moving either moves the plan. The plan hashes to
`eaf2412b1c757bde0a0d42bd3d3f3c10fab1c4e9ae04bd30d750a5aef46fa883`, in
`GOLDEN_SET_PLAN_HASHES` and the released history. The gated family is nine
pairs of twenty. `tests/unit/test_jev_prereg.py::TestTheOpsKeywords` and
`::TestTheOpsPlan`.

**The reads** (design sections 3.7 and 5.3). `jev_repo.get_failed_job` reads a
job by its id, as its id, kind, status, error and finish time and nothing
else. `failed_jobs_for_triage` is the planner's: jobs of the kinds named that
failed and finished after a bound, newest first, at most 200; a job an
expired lease failed has no finish time and is never read. `unasked_subjects`
applies C7's filters to addresses its caller computed — an `ok` answer under
the pin at the registered version, three failed calls, a job waiting or
planned today — since a skeleton's address is no SQL's to compute; no content
block holds a subject addressed by its state (open item 36).
`job_error_since` is the UTC midnight after the pin's first day, and
`job_error_population` every skeleton of the population by its state's
address, with its earliest and latest failure and its newest job. The
harness's dates, texts and labelling population of a job error are read over
that population, so a skeleton whose only occurrences fell on or before the
pin's first day is no item, and no item is dated by one (D-HMB-08).
`recent_failed_jobs` is `suggestions`' read. No read writes, retries or
resumes a job. `tests/integration/test_jev_repo.py::TestTheFailedJobRead`,
`::TestFailedJobsForTriage`, `::TestUnaskedSubjects`,
`::TestTheJobErrorPopulation` and `::TestRecentFailedJobs`, each filter held
by a case only it refuses.

**The ask** (the scope's 4, eighth point; design section 5.1). `ASKABLE` gains
the ops set, and `Askable` gains `address(row, state)`, the subject a row
holds: for a text set the sha256 of its text, checked before admission as
before; for the ops set the address of the state built, checked once the
state is built. The job is read by its id; the admission refuses, each alone
and for good, a job that did not fail, one of a kind code alone places, one
with no finish time, one whose error code places and one whose skeleton is
too short, naming the job by its id and quoting nothing of its error. No
follow-up: an answer is recorded and changes nothing.
`tests/unit/test_jev_jobs.py::TestTheJobErrorAsk`;
`test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall`, every road
outcome through the ops set; and
`test_jev_table_boundaries.py::test_a_job_error_is_used_only_by_the_redactor_and_code_cause`,
an AST scan of the handler, the planner, the harness and `jev_repo` holding
every use of a job's error to the redactor and code's triage —
`jev_redact.skeleton`, `jev_chips.code_cause`, `residue_skeleton` and, for the
harness's chips, `job_error_shape` — proved on synthetic sources.

**The planner** (the scope's 4, ninth point; design section 5.2). The ops set
behind the ops area and the detail switch, each through its own reader, at
most ten a pass, one call each from the ops share, under
`jev_ask:ops.job_error@1:job_error:{address}:{UTC date}`: the failed jobs of
the triaged kinds within a week of the clock (`OPS_WINDOW`) and after the
pin's first day, the residue only, each skeleton once by its address, naming
its newest job, newest first, then `unasked_subjects`. The authentication and
422 holds stand. A row it cannot read is logged by its class and the job's
id; no error is logged. `tests/unit/test_jev_plan.py::TestTheOpsRule`,
`test_the_planner_logs_no_text` among its cases, captured at DEBUG;
`::TestTheDetailSwitchGatesPlanning` with `ops.job_error`; and
`::TestTheSwitchMatrix`'s ops conjunction. The road holds the same:
`tests/unit/test_jev_lane.py::TestTheDetailSwitch::test_ops_asks_nothing_with_the_detail_switch_off`
and `::TestStandingRefusals::test_a_skeleton_is_held_by_no_content_block`.

**The harness** (the scope's 4, tenth point; design sections 3.5, 3.7 and
9.3). A job error's skeleton is a labelled subject. A label of one is read
back through the state its text names (`STATE_FROM_TEXT`, D-HMB-07): the text
required, naming exactly one state, whose address is the subject. An ops
evaluation prints beside its figures that its dates carry nothing about
training (`OPS_DATING_NOTE`, open item 81). Both read surfaces gain their jobs
half, each still reading in the harness's read-only snapshot and loading no
planner, lane or client:

- `preview --set ops.job_error` runs the ops rule from copies of the
  planner's reads and the handler's rules: each skeleton the planner would ask
  about, by its newest job, with the exact state that would be sent — the
  kind and the skeleton, which is what leaves — or why nothing would be, in
  code's words; the switches it names, the detail switch among them; and
  every failed job of a triaged kind the rule reads, by its id and kind, with
  code's chip and shape, or that code leaves it to Jev.
  `tests/integration/test_jev_ops.py::TestPreviewIsThePlanners` holds the
  subjects equal to the planner's, in order, and every state to the one the
  handler hands the road, on the same rows; with the detail switch off,
  preview names it and the planner plans nothing.
- `suggestions` lists each failed job of the last seven days, of any kind
  (`jev_repo.recent_failed_jobs`, where a job an expired lease failed is
  placed by when it was first claimed), by its id and kind, with code's chip
  and how the ops set's ask about its skeleton came out; never its error, its
  skeleton or an answer. What the job's row decides — a kind code alone
  places, an error code places, a skeleton too short — is said whatever the
  pin. A job the planner does not read, one with no finish time or one that
  failed on or before the pin's first day, holds words another job may have
  had asked, so its status is read from the ledger first, and "not asked" is
  said only where nothing is on record; with no pin it is unknown (D2RW-2's
  rule).

`tests/unit/test_jev_eval.py::TestTheJobErrorLabels`, `::TestTheOpsSubject`,
`::TestTheOpsDates`, `::TestThePreviewOfAFailedJob` and
`::TestTheSuggestionsOfFailedJobs`; `tests/integration/test_jev_ops.py::TestSuggestionsOnPostgres`.

**What holds it** (the scope's 4, last points; design section 13):

- the ops canary (`tests/integration/test_jev_ops.py::TestTheCanary`): markers
  in failed jobs' errors — one code leaves to Jev, one it places, one too short
  to ask about, one of a kind code alone places — and in a job's payload and
  result; a marker in every placeholder class; and synthetic secrets of every
  shape this deployment holds or could echo, marked as credentials and bare;
  each found in its own job's own column alone once the loop has asked about
  every skeleton it may, every text and JSON column of every table read from
  `information_schema`; `jev_requests.state` holding the redactor's tokens and
  nothing else, exactly what the vendor saw; and no marker in a log record at
  DEBUG or in another job. Beside it, only what code leaves to Jev is asked
  about, each skeleton once by its newest job, replayed for an older one with
  no call and planned again on no later day, and never a venue kind's, the
  shadow replay's, a programme kind's, one before the population starts, one
  older than the week or one an expired lease left
  (`::TestOnlyWhatCodeLeavesToJevIsAsked`); and the failed job, the findings
  register, the hypotheses, the candidates, the assessments and the switches
  are unchanged under an answer, a timeout, a response refused whole, a
  content block, a 422 and a refused key (`::TestAJobIsUnchangedByEveryOutcome`);
- what leaves (`tests/sdk/test_jev_findings_ops_over_http.py::TestOneJobErrorSkeletonOverHTTP`):
  with the ops area on and the detail switch off, nothing planned and nothing
  sent; with both on, a failed job's skeleton asked through the planner, the
  handler, the lane, the real client and SDK and real HTTP to the fake
  TypeSafe server, the request's state exactly the kind and the skeleton,
  none of the error's words, the job's id or its payload in the body,
  recorded in the ops lane as `system`; and a second job of the same skeleton
  replayed with no request leaving;
- the dark matrix (`tests/integration/test_jev_dark.py`): a failed job stored
  while dark is asked nothing; the big matrix stores one before every case and
  none asks about it; `TestTheOpsMatrix` crosses the programme, Jev, the ops
  area and the detail switch, sixteen cases, the skeleton alone sent exactly
  when all four are on, so the ops area on with the detail switch off plans
  and sends nothing; and `TestTheArmingSwitchHasNoConsumerYet` holds the
  arming switch, which has none until D4;
- the evaluation (`tests/integration/test_jev_evaluations.py::TestTheOpsSetEndToEnd`):
  a ledger the loop wrote, the population exported blind, labelled by its
  text, imported and evaluated through `jev_eval.main`; the row equal to its
  recomputation, the keyword rule reading each skeleton's text, and every item
  dated after the pin's first day, the early job's skeleton no item.

Each new control was removed in turn, thirty-five in all, two of them again
against the dark matrix and `suggestions` on PostgreSQL, and a named test
failed for every one but one: the exact round-trip comparison at the end of
`job_error_from_text`, which the parse before it already implies — a text
that validates is the text `job_error_text` writes, since no token holds a
space and none is empty — so no input reaches it. It is kept as a guard
should a token ever hold a space.

**Where D3 departs from the design and its scope.**

- Owner item 9.1 is open, and D3 builds its chosen default: a skeleton goes
  only while the ops area and the detail switch are both on, each read through
  its own fail-closed reader. Fact 7 is not amended. Restating fact 7's
  defaults and the "Inputs needed" defaults with ops, which the scope's docs
  list asks for once the owner answers 9.1, waits on that answer (open item
  89).
- The shapes table is version 2. Version 1 was published on the branch in
  `a7a6a27`, before the ops ask's own refusals were placed by two shapes of
  their own (`ops_ask_outside_the_population`, `code_defect`, and
  `ops_ask_left_to_code`, `held_by_design`); no plan named version 1, and its
  hash stays in the released history.
- `OPS_KEYWORDS` is design 3.4's table cut, and only cut, by the evidence
  rule. Every HTTP status, the rate-limit words, `unauthorized`,
  `unauthorised`, `forbidden`, `credential`, `password`, `exhausted`, `dns`,
  `cannot connect`, `outage`, `empty response`, `not subscriptable`,
  `is not defined`, `not callable`, `no data`, `delisted`, `not found` and
  `inconsistent` are produced by no subject text of the corpus: the data
  sources wrap every vendor failure in a message code places, and the
  redactor never lets some of the words through. So `rate_limit` is a cause
  the baseline never answers, and a person's `rate_limit` label is always the
  rule's miss. `TestTheOpsKeywords::test_the_rule_is_the_drafts_less_what_no_message_produces`
  holds the cut to the draft, in the draft's order.
- The population starts at the UTC midnight after the day the pin was first
  observed (`job_error_since`), not at the observation itself: a job is the
  population's only when it finished after that day, the day an item is
  dated by, so every item reads as not possibly in training, for the reason
  open item 81 gives.
- The planner reads a week (`OPS_WINDOW`) while the population reads every
  failed job since the pin's first day (open item 86).
- `Askable.address` takes the row and the state, not design 5.1's row alone,
  since a skeleton's address is its state's, built only after admission.
- The harness shows code's chip where the design names it for `suggestions`
  and beyond: `preview` lists every failed job of a triaged kind the rule
  reads, with code's chip and shape, and `suggestions` every failed job of
  the week, of any kind, a lease-expired one included. The chip is code's
  own table's entry, never Jev's, and the error-use scan admits
  `jev_chips.job_error_shape`, whose result names that entry and carries no
  word of the error.
- Test names in the binding list that this build spells otherwise:
  `TestPreview::test_it_prints_exactly_what_would_leave` for ops is
  `TestThePreviewOfAFailedJob::test_it_prints_exactly_the_skeleton_that_would_leave`;
  `TestSuggestions::test_ids_labels_and_numbers_only` and
  `::test_no_answer_no_probability_no_chip_and_no_jev_ref` for ops are
  `TestTheSuggestionsOfFailedJobs::test_ids_kinds_and_codes_chip_only` and
  `::test_no_answer_no_probability_and_no_chip_of_jevs`;
  `TestTheSetPlans::test_released_rows` is
  `TestTheSetPlansAreTheirReleasedHashes`, as in D2;
  `TestTheGateFamily::test_the_gated_pairs_fit_the_family`'s nine are pinned
  pair by pair by `::test_the_family_holds_phase_ds_pairs`; and
  `TestWhatAnAnswerMayChange` is still `TestTheCardCheckChangesNothing` until
  D4 renames it, its walk from `jev_jobs` covering the ops entry and finding
  no writer.
- The ops area and the detail switch get a matrix of their own with the
  programme and Jev, sixteen cases, rather than joining the big matrix as two
  more dimensions, which would make 256 cases of a database each; no other
  switch bears on whether the ops set asks, and the planner's unit matrix
  covers every combination of all of them. The class that held the ops area
  and the detail switch to having no consumer, true until D3, now holds the
  arming switch alone.
- The SDK case's skeleton half needs the SDK and a database in one process,
  which this machine cannot give: the database here admits the `postgres`
  operating-system user alone, which cannot read the SDK's environment. It was
  collected with the SDK installed, and CI's `programme sdk` job runs it.

### Open items Phase D found

Numbered on from Phase C's, as design section 14 numbers them. Each says the
pull request it belongs to; D1 builds the ones it names.

71. **The Jev duplicate question is deferred** (D2). Duplicates are code-exact
    only; asking Jev whether two findings are one is left for later. D2 builds
    the code chip alone, on the same candidate and by exact normalised title,
    so two findings worded differently are never marked.
72. **Card labels are exposed after the first armed finding** (D4). A Jev
    finding on the register says what Jev answered about a title, and nothing
    records which labeller has seen it.
73. **The worker records `str(exc)` without its class** (D3), so no ops
    keyword reads a class name; naming the class is the worker's own review.
74. **The daily report's blocking count is not veto-aware** (D2 and after): it
    counts high and critical findings whoever raised them.
75. **Findings labels can echo the register** (D2). The findings page shows
    the raiser and the severity beside every title — the values the recorded
    baseline reads — and nothing records which labeller has read it. No
    findings set arms in phase D.
76. **Findings raised before 0015 read `'unknown'`** (D1), and are never
    asked about: no writer of them can now be proved, and a backfill from
    `audit_log` would be a guess.
77. **The vocabulary bounds what a skeleton can say** (D3); a change to it is
    a new set version.
78. **Looks are counted per set, version and question across every model**
    (D1), so after four looks a set's question cannot arm under any pin until
    a new set version.
79. **The harness enforces only its own commands** (D1). `jev_eval.evaluate()`,
    the function, computes a test-split evaluation and records nothing, and
    anyone who reads the test split by hand is outside the protocol.
80. **Near-threshold flips above a threshold of 0.30 rest on the uniform
    stratum alone** (D1, plan version 2); a margin-banded stratum is a later
    plan's.
81. **Ops items are dated over the rows their population reads** (D3), so an
    occurrence of a skeleton before the pin's first observation does not mark
    it possibly in training. For private records the date carries nothing
    about training, and a skeleton that is also a public library message is in
    training whatever its date.
82. **The detail switch is one switch for all of this system's detail** (D1,
    live from D3). Switched on for ops, it lets any later set declaring
    `internal_detail` send too, once that set's own area is on; the planner
    and the road both read it for every such set.
83. **A `dev` run cannot say whether a look would be an upper bound** (D1,
    found by D1's review). `evaluate --split dev` reads no date of a test
    item, and a look searches for a threshold only if every item it reads is
    dated after the pin was first observed, so a held-out item undated, or
    dated on or before that day, makes the look an upper bound that attempts
    no threshold while it still spends one of the four looks every pin
    shares (item 78). The `dev` run's threshold line names that condition and
    promises nothing; reading the held-out items' dates, which carry no label
    and no answer, in a line of their own beside the `dev` figures, without
    moving any of them, would let an operator know before spending the look.
    Left for review: it is a new read of the test split, however harmless.
84. **`preview` cannot show a web set** (D2). A web set's subjects are chosen
    by the injection screen's own answers — the content it cleared, for the
    catalogue, and the content its `true` is on record for, for the screen's
    repairs — so a list of them would show those answers to someone who may
    later label the screen or the catalogue, and `preview` refuses a web set.
    Before the research or guardrails area is first switched on, what a web
    set would send is read from the stored excerpts and the planner's rules
    instead; a preview that withheld which content the screen cleared, or one
    readable only by someone who will never label, is left for review.
85. **A re-ask of an answer whose words a block has since reached is drawn,
    and refused unrecorded** (D2, found by D2's review). The re-ask planner
    (`jev_plan._reaskable`) reads no content block: it leaves out web text
    quarantined since or flagged by the screen, and nothing else. So a
    canonical answer about a title — a hypothesis's or, from D2, a finding's,
    the two one state for the same words — whose words a vendor's block
    reached before its re-ask is drawn, by any set of either title, is drawn
    the next UTC day all the same, and the road refuses the re-ask before any
    call, writing nothing. The job fails once, since a re-ask is drawn only
    the day after its answer, and as nothing was recorded the canonical
    answer has no re-ask on record (`jev_repo.probe_pairs` pairs it with a
    probe row): the flip rates count it neither as a comparison nor as a
    re-ask not compared, which plan version 2 reads against the limits in
    the worst case (M5). The same holds for any re-ask the road refuses
    without a row — a standing refusal, a switch turned off, no key — so "a
    re-ask that could not be compared is counted" covers the re-asks that
    reached the ledger. The two hypothesis-title sets could meet the block
    case before D2. Leaving such text out of the draw, or counting a drawn
    re-ask the road refused as not compared, would each change which pairs
    the flip limits count, which is the plan's to decide, not a planner's;
    left for review.
86. **The ops rule reads a week, and the population every failed job since
    the pin's first day** (D3). The planner asks about the skeletons of the
    last seven days' failed jobs (`OPS_WINDOW`), while the population a
    labeller is shown, and an evaluation is computed over, holds every
    skeleton since the midnight after the pin was first observed. A skeleton
    whose jobs all failed more than a week before the ops area is switched
    on, or before a pass reaches it, is exported and labelled and never
    asked, unless a job fails with it again, and the evaluation counts it not
    asked. Exporting only what was asked would choose the subjects by the
    planner's work rather than the code alone, and widening the window would
    ask about errors nobody is looking at any more; left for review.
87. **A redactor change needs new words** (D3). The plan names the
    redactor's hash and the set's words render its legend and bound, but a
    change to the vocabulary or the rules leaves the words as they are, and a
    new version of the set asking the same words repeats its questions hash,
    which open item 15's rule refuses. Such a change must move the words as
    well, a reworded legend say, or the rule must learn that one set's next
    version may repeat its own questions. Open item 77 is why a change is a
    new version at all.
88. **The rule reads the newest 200 failed jobs of the week** (D3), the page
    `failed_jobs_for_triage` reads, and `suggestions` lists at most 200
    (`recent_failed_jobs`). A burst of more than 200 failures — a parameter
    grid failing point by point, say — hides the week's older failures from
    the rule until the burst ages out, and from `suggestions`. The address is
    computed in code, so no SQL can read distinct skeletons; paging the read
    until ten unasked skeletons are found is left for review.
89. **Fact 7's defaults and "Inputs needed" are not yet restated with ops**
    (D3; the owner's item 9.1). D3 builds the scope's chosen default — a
    skeleton goes only while the ops area and the detail switch are both on —
    and amends nothing of fact 7. Restating fact 7's defaults and the
    "Inputs needed" defaults with ops waits on the owner's answer to 9.1:
    confirmed, they gain a line saying a failed job's skeleton is this
    system's own text and goes only while the detail switch is on; answered
    the other way, fact 7 is amended and the planner and the road change
    with it.

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
   above). From D1 they are the regime's own plan, apart from the global one,
   so before the decisions area is first switched on a change is a
   `REGIME_PLAN_VERSION` bump that costs nothing and sets aside no other
   lane's history; after the first regime answer, the same bump is recorded as
   a change of plan.
3. **A replacement Alpaca paper key** for the revoked one.
4. **For phase H, a second Alpaca paper account's key**: a `PK` key, checked
   against both endpoints before it is stored, as CLAUDE.md requires of any
   Alpaca key.

Defaults applied unless the operator says otherwise:

- Public web content and code-computed features are sent to TypeSafe.
- Hypothesis cards and findings are sent as titles only. Their detail is sent
  only if `jev_send_internal_detail`, which starts off, is switched on. From
  D2 a finding's title is sent only when the programme's model wrote it,
  never an operator's.
- No model is ever trained on Jev's output.
- The model is pinned to `jev-1.13.0`, and every Jev switch starts off.

## Verification

| When | Check |
|---|---|
| Every phase | `pytest tests/unit -q`; `pytest tests/unit/test_parity.py -q`; `ruff check src/ tests/`; the integration suite on real Postgres in CI; from phase B, the SDK job |
| Once a key exists | A probe run; `jev_eval` on the held-out set and on the 61-strategy set, labelled an upper bound; the forward clock checked daily; the new pages checked on the deployed app with the live smoke |
