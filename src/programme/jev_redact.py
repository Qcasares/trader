"""
jev_redact.py
-------------
A failed job's error message reduced to a skeleton: the one way any part of
``jobs.error`` becomes state (phase D3, docs/09 section 4).

Pure: the standard library alone, so the API may import it and phase E can
compute a subject with the same function the planner and the handler use
(``tests/unit/test_import_boundaries.py::test_the_pure_modules_load_nothing``).

Why an allow-list
~~~~~~~~~~~~~~~~~
A job's error is not all code-built. The worker records ``str(exc)`` for any
exception (``src/worker/main.py``), and that text can quote a driver's value,
a validator's input, a vendor's reply, symbols, amounts, ids and paths. A
deny-list could never be shown complete, so the redactor keeps only what it
knows — the words of :data:`VOCABULARY`, the names in :data:`EXCEPTION_NAMES`
and :data:`HTTP_TOKENS` — and replaces everything else by a placeholder from
:data:`PLACEHOLDERS`, which says what kind of thing stood there and never what
it was. :func:`skeleton` is total and deterministic: it never raises, for any
input of any type, every token it returns is one of :data:`TOKENS`, and it
reads at most :data:`MAX_INPUT_CHARS` characters and returns at most
:data:`SKELETON_MAX_TOKENS` tokens.

The rules, in order (docs/09 section 4.2, binding)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The first rule that applies decides each piece.

0. A value that is not a ``str`` gives ``()``; a string is cut to
   :data:`MAX_INPUT_CHARS`.
1. The text is split on whitespace into chunks. A chunk exactly equal to a
   placeholder or an :data:`HTTP_TOKENS` entry is emitted as itself, so a
   skeleton read again is unchanged.
2. Every other chunk is split on :data:`SPLIT_CHARACTERS`, which are emitted as
   nothing. A run opened by a piece beginning with one of
   :data:`QUOTE_CHARACTERS` is closed by a later piece ending with the same
   character — read once its trailing :data:`STRIP_CHARACTERS` are set aside,
   so ``'x'.`` closes where it ends — or by the end of the text, and the whole
   run is one ``[quoted]``. An apostrophe inside a word opens nothing.
3. Leading and trailing :data:`STRIP_CHARACTERS` are stripped, so no colon
   survives; a piece left empty is emitted as nothing.
4. Any character outside printable ASCII gives ``[word]``.
5. A piece containing ``://``, starting ``www.`` or holding ``@`` gives
   ``[address]``.
6. ``key=value`` gives the key, by these rules, then ``[value]``, or
   ``[secret]`` when the key, casefolded, is in :data:`SECRET_WORDS`. The value
   is never emitted: a value opening a quote that the piece does not close
   swallows the pieces after it up to the one that closes it, as rule 2's run
   does; and a value written after a space — ``key= value``, ``key = value``
   — is the next piece, given ``[value]``, or ``[secret]`` after a key in
   :data:`SECRET_WORDS` or :data:`SECRET_LEADS`.
7. The piece after a :data:`SECRET_LEADS` word gives ``[secret]``. The word is
   read casefolded, with its leading dashes dropped, its rule 3 characters
   stripped, and one trailing ``=`` dropped, so ``password= x`` hides ``x`` as
   ``password x`` does.
8. A piece containing ``/`` or ``\\`` gives ``[path]``.
9. A date gives ``[date]``, and a time of day ``[time]``.
10. A dotted run gives ``[number]`` when it is a decimal, and ``[address]``
    otherwise.
11. A number directly after ``http``, ``status`` or ``code`` and from 100 to
    599 gives ``http_NNN`` when listed in :data:`HTTP_TOKENS`, and
    ``http_other`` otherwise. Any other number gives ``[number]``.
12. Any digit left in a piece gives ``[id]``.
13. A piece exactly an :data:`EXCEPTION_NAMES` entry gives itself.
14. Two or more capitals give ``[name]``, unless the casefolded piece is in
    :data:`CAPS_VOCABULARY`, which gives that word.
15. A piece whose casefolded form is in :data:`VOCABULARY` gives that word.
16. Anything else gives ``[word]``.

Then, in this order: a run of one placeholder repeated collapses to one; over
:data:`SKELETON_MAX_TOKENS` tokens, the first 47 are kept and ``[more]``
added; and runs are collapsed again. The third step is what makes the
redactor idempotent — ``skeleton(" ".join(skeleton(x))) == skeleton(x)`` —
since an input whose 47th token is a literal ``[more]`` would otherwise end
``[more] [more]``, which read again is another skeleton (docs/09, D-HMB-09).

Three readings are wider than the design's sentences (docs/09 section 4.2),
and each only hides more: rule 7's lead word sets aside a rule 3 character
and a trailing ``=`` as well as its casefold and dashes, so ``password: x``
and ``password= x`` hide ``x``, and a piece hidden as a value still leads, so
``headers= password: x`` hides ``x`` too; rule 6's value is the piece after a
space when it is written apart, and what a quote opened in it spans; and a
quote is read after rule 3's characters at a piece's start, so ``:'a b'`` is
one ``[quoted]``. The hash below pins them (docs/08, D3 as built).

What the planner and the handler admit is :func:`admissible`: at least
:data:`MIN_CONTENT_TOKENS` content tokens, which are vocabulary words outside
:data:`FUNCTION_WORDS`, exception names and HTTP tokens.

The vocabulary
~~~~~~~~~~~~~~
At most 400 reviewed words, each ``^[a-z][a-z_]{1,31}$``, drawn from the raise
sites of the triaged kinds' modules, the error messages of the libraries
they use, and :data:`TRIAGED_KINDS`; never from the other job kinds or from
table names. The code screen reads an underscore as a space
(``web_sources.SKELETON_SPACES``), so a word is held to
:data:`NEVER_IN_VOCABULARY` part by part as well as whole: every underscore
part of every word and HTTP token, and every capital-split part of every
exception name. ``tests/unit/test_jev_redact.py`` proves, by parsing the code
screen's ``instruction_phrase`` patterns, that every alternative needs a word
this module can never emit, and runs every word alone and every ordered pair
through the three rules a skeleton could trip.

Versioning
~~~~~~~~~~
:data:`REDACTOR_VERSION` and :func:`redactor_sha256`, pinned in
:data:`GOLDEN_REDACTOR_SHA256` and held to an append-only released history in
the test. A change of vocabulary is a new ``ops.job_error`` version, since the
same words over another skeleton are another question (docs/08 open item 77),
and the ops set plan names the hash its answers were recorded under.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType

#: The redactor's version, which :func:`redactor_sha256` hashes with every set
#: and rule below.
REDACTOR_VERSION = 1

#: :func:`redactor_sha256` of this version, pinned beside the rules. A test
#: compares the two, and holds this one to the append-only history of released
#: versions kept in ``tests/unit/test_jev_redact.py``, so re-recording it after
#: a change still fails there.
GOLDEN_REDACTOR_SHA256 = (
    "e7742dcfc1b4ebafb2ab87e595fb8a9fce67a8dc540bdca39a63fb05330984e9"
)

#: The job kinds whose errors may be triaged by Jev: research and ingest alone
#: (docs/09, D9). A venue job's error carries broker responses, quantities and
#: order ids and is read whole by an operator; a programme job's is code-built,
#: and triaging it with Jev would be a loop. ``tests/unit/test_job_ownership.py``
#: holds these to the worker's own kinds and to none of the venue, shadow or
#: programme kinds.
TRIAGED_KINDS: tuple[str, ...] = (
    "backtest",
    "walkforward",
    "ingest_bars",
    "ingest_reference_bars",
)

#: The placeholders, in their order, each with what it stands for. The
#: question ``ops.job_error`` renders this legend into its words, so moving a
#: placeholder or its meaning moves the set's pack hash.
PLACEHOLDERS: Mapping[str, str] = MappingProxyType(
    {
        "[number]": "a number",
        "[id]": "an identifier mixing letters and digits",
        "[name]": "a name written with capital letters",
        "[word]": "another word",
        "[date]": "a date",
        "[time]": "a time of day",
        "[address]": "a web, network or code address",
        "[path]": "a file path",
        "[quoted]": "quoted text",
        "[value]": "the value given to a setting",
        "[secret]": "a credential",
        "[more]": "words left out at the end",
    }
)

NUMBER = "[number]"
ID = "[id]"
NAME = "[name]"
WORD = "[word]"
DATE = "[date]"
TIME = "[time]"
ADDRESS = "[address]"
PATH = "[path]"
QUOTED = "[quoted]"
VALUE = "[value]"
SECRET = "[secret]"
MORE = "[more]"

#: The most tokens a skeleton holds, ``[more]`` included.
SKELETON_MAX_TOKENS = 48

#: The most characters of an error the redactor reads: ``job_repo.fail`` keeps
#: the first 4,000 of an error, and the redactor reads no further.
MAX_INPUT_CHARS = 4_000

#: The fewest content tokens a skeleton needs to be asked about
#: (:func:`admissible`).
MIN_CONTENT_TOKENS = 3

#: The HTTP statuses rule 11 names, each its own token; any other status from
#: 100 to 599 is ``http_other``.
HTTP_LISTED: tuple[int, ...] = (
    400,
    401,
    403,
    404,
    408,
    409,
    422,
    429,
    500,
    501,
    502,
    503,
    504,
    529,
)

HTTP_OTHER = "http_other"

HTTP_TOKENS: tuple[str, ...] = (
    *(f"http_{status}" for status in HTTP_LISTED),
    HTTP_OTHER,
)

#: The words after which a number from 100 to 599 is an HTTP status.
HTTP_LEADS: frozenset[str] = frozenset({"http", "status", "code"})

#: Keys whose value is a credential: ``key=value`` gives ``[secret]`` for them.
SECRET_WORDS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "apikey",
        "api_key",
        "key",
        "authorization",
        "bearer",
        "cookie",
        "session",
        "dsn",
        "credential",
        "credentials",
    }
)

#: Words after which the next piece is a credential.
SECRET_LEADS: frozenset[str] = frozenset(
    {
        "authorization",
        "bearer",
        "basic",
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "apikey",
        "api_key",
    }
)

#: What rule 2 splits a chunk on, emitting nothing for each.
SPLIT_CHARACTERS = ",;()[]{}|"

#: What rule 3 strips from either end of a piece.
STRIP_CHARACTERS = ".:!?"

#: What opens a quoted run (rule 2).
QUOTE_CHARACTERS = "'\"`"

#: Words written in capitals that rule 14 reads as the vocabulary word rather
#: than a name: each is in :data:`VOCABULARY`.
CAPS_VOCABULARY: frozenset[str] = frozenset({"http", "json", "sql", "utc", "nan"})

#: The most words :data:`VOCABULARY` may hold (docs/09, section 4.3): a
#: reviewer reads every one, and every one is a word a skeleton can say.
MAX_VOCABULARY = 400

#: What a vocabulary word looks like: lower-case letters and underscores, two
#: to thirty-two characters, starting with a letter.
VOCABULARY_WORD = re.compile(r"[a-z][a-z_]{1,31}")

#: Words that carry no content of their own: a skeleton of these alone says
#: nothing a cause could be read from (:func:`admissible`). Each is a
#: vocabulary word.
FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "after",
        "all",
        "already",
        "also",
        "an",
        "and",
        "another",
        "any",
        "are",
        "at",
        "be",
        "been",
        "before",
        "between",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "due",
        "each",
        "for",
        "from",
        "got",
        "had",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "its",
        "more",
        "must",
        "no",
        "not",
        "of",
        "on",
        "one",
        "only",
        "or",
        "out",
        "over",
        "per",
        "should",
        "so",
        "such",
        "than",
        "that",
        "the",
        "to",
        "too",
        "under",
        "until",
        "up",
        "was",
        "were",
        "what",
        "when",
        "which",
        "while",
        "with",
        "without",
        "would",
    }
)

#: The words that carry content: what a research or ingest job's errors are
#: written in, by its own raise sites and by the libraries it uses. Reviewed
#: one by one, and kept to :data:`MAX_VOCABULARY` words with
#: :data:`FUNCTION_WORDS`; a change is a new redactor version, and so a new
#: ``ops.job_error`` version (docs/08 open item 77).
_CONTENT_WORDS: frozenset[str] = frozenset(
    {
        # The triaged kinds, and what their own raise sites write.
        "backtest",
        "walkforward",
        "ingest_bars",
        "ingest_reference_bars",
        "ingest",
        "reference",
        "bar",
        "bars",
        "adjustment",
        "basis",
        "calendar",
        "close",
        "data",
        "dependency",
        "deployment",
        "download",
        "enabled",
        "end",
        "fetch",
        "fetched",
        "history",
        "installed",
        "job",
        "keep",
        "kept",
        "live",
        "minutes",
        "new",
        "next",
        "nothing",
        "older",
        "produced",
        "request",
        "requests",
        "research",
        "retry",
        "return",
        "returned",
        "row",
        "rows",
        "run",
        "session",
        "sessions",
        "source",
        "span",
        "stale",
        "start",
        "stored",
        "table",
        "timestamp",
        "unknown",
        "usable",
        "vendor",
        "window",
        "worker",
        # Errors as this system's engine and strategies write them, which
        # reach a backtest or a walk-forward unwrapped.
        "few",
        "leverage",
        "panel",
        "registered",
        "strategy",
        "symbol",
        "symbols",
        "universe",
        "weight",
        "weights",
        # Errors as Python, its standard library, pandas, numpy, pydantic and
        # the exchange calendar write them.
        "access",
        "allocate",
        "argument",
        "arguments",
        "array",
        "assignment",
        "attribute",
        "axis",
        "bad",
        "badly",
        "base",
        "bound",
        "bounds",
        "broadcast",
        "broken",
        "byte",
        "bytes",
        "callable",
        "cannot",
        "character",
        "codec",
        "column",
        "columns",
        "concatenate",
        "convert",
        "date",
        "dates",
        "datetime",
        "day",
        "decode",
        "defined",
        "depth",
        "dict",
        "dimension",
        "directory",
        "division",
        "dtype",
        "duplicate",
        "element",
        "empty",
        "encoding",
        "equal",
        "errno",
        "error",
        "errors",
        "exceeded",
        "exception",
        "expected",
        "expecting",
        "extra",
        "failed",
        "fails",
        "failure",
        "field",
        "fields",
        "file",
        "finite",
        "float",
        "format",
        "formed",
        "found",
        "frame",
        "frequency",
        "function",
        "greater",
        "hexadecimal",
        "identity",
        "import",
        "index",
        "input",
        "int",
        "integer",
        "invalid",
        "isoformat",
        "iterable",
        "keyword",
        "left",
        "length",
        "less",
        "limit",
        "line",
        "list",
        "literal",
        "match",
        "matrix",
        "maximum",
        "minimum",
        "missing",
        "module",
        "month",
        "name",
        "negative",
        "non",
        "none",
        "number",
        "object",
        "objects",
        "operand",
        "operands",
        "operation",
        "overflow",
        "parse",
        "permitted",
        "position",
        "positional",
        "range",
        "reason",
        "recursion",
        "reduction",
        "required",
        "resource",
        "result",
        "scalar",
        "sequence",
        "setting",
        "shape",
        "shapes",
        "single",
        "singular",
        "size",
        "slice",
        "space",
        "starting",
        "str",
        "string",
        "subscriptable",
        "support",
        "supported",
        "syntax",
        "temporarily",
        "time",
        "timezone",
        "together",
        "tuple",
        "type",
        "types",
        "unable",
        "unexpected",
        "unsupported",
        "unterminated",
        "valid",
        "validation",
        "value",
        "values",
        "year",
        "zero",
        "files",
        "long",
        "milliseconds",
        "named",
        "open",
        "pipe",
        "progress",
        "property",
        "quotes",
        "route",
        "uuid",
        # Errors as PostgreSQL and asyncpg write them.
        "aborted",
        "administrator",
        "authentication",
        "block",
        "canceling",
        "check",
        "clients",
        "closed",
        "command",
        "commands",
        "concurrent",
        "configuration",
        "connection",
        "connections",
        "constraint",
        "current",
        "database",
        "deadlock",
        "denied",
        "detected",
        "down",
        "exist",
        "extend",
        "foreign",
        "ignored",
        "insert",
        "key",
        "lock",
        "malformed",
        "memory",
        "middle",
        "null",
        "numeric",
        "obtain",
        "operator",
        "parameter",
        "password",
        "peer",
        "permission",
        "privilege",
        "query",
        "relation",
        "role",
        "schema",
        "serialize",
        "shutting",
        "sorry",
        "statement",
        "terminating",
        "transaction",
        "unique",
        "unrecognized",
        "update",
        "violates",
        "violation",
        # Errors as the network, the vendor's transport and HTTP write them.
        "certificate",
        "client",
        "code",
        "connect",
        "delisted",
        "device",
        "disconnected",
        "disk",
        "forbidden",
        "gateway",
        "handshake",
        "host",
        "http",
        "internal",
        "json",
        "limited",
        "many",
        "nan",
        "network",
        "perform",
        "port",
        "possibly",
        "price",
        "prices",
        "protocol",
        "quota",
        "rate",
        "received",
        "refused",
        "remote",
        "reset",
        "resolution",
        "resolve",
        "response",
        "retries",
        "server",
        "service",
        "socket",
        "sql",
        "ssl",
        "status",
        "temporary",
        "timed",
        "timeout",
        "unauthorized",
        "unavailable",
        "unreachable",
        "url",
        "utc",
        "verify",
    }
)

#: Every word a skeleton may hold: the content words and the function words,
#: at most :data:`MAX_VOCABULARY` of them (docs/09, section 4.3).
VOCABULARY: frozenset[str] = _CONTENT_WORDS | FUNCTION_WORDS

#: Exception names a skeleton may hold as themselves, each a real exception
#: class of the standard library, of a library a triaged kind uses, or of this
#: repository (``tests/unit/test_jev_redact.py`` resolves every one).
EXCEPTION_NAMES: frozenset[str] = frozenset(
    {
        # Python's own.
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BlockingIOError",
        "BrokenPipeError",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "EOFError",
        "FileExistsError",
        "FileNotFoundError",
        "FloatingPointError",
        "ImportError",
        "IndexError",
        "InterruptedError",
        "IsADirectoryError",
        "KeyError",
        "LookupError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "NotADirectoryError",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PermissionError",
        "RecursionError",
        "RuntimeError",
        "TimeoutError",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "ValueError",
        "ZeroDivisionError",
        "CancelledError",
        "JSONDecodeError",
        # asyncpg's, for PostgreSQL's errors and its own.
        "CannotConnectNowError",
        "CheckViolationError",
        "ConnectionDoesNotExistError",
        "ConnectionFailureError",
        "DataError",
        "DeadlockDetectedError",
        "DiskFullError",
        "ForeignKeyViolationError",
        "InFailedSQLTransactionError",
        "InsufficientPrivilegeError",
        "InsufficientResourcesError",
        "InterfaceError",
        "InternalServerError",
        "InvalidPasswordError",
        "LockNotAvailableError",
        "NotNullViolationError",
        "NumericValueOutOfRangeError",
        "OutOfMemoryError",
        "PostgresConnectionError",
        "PostgresError",
        "QueryCanceledError",
        "SerializationError",
        "StringDataRightTruncationError",
        "TooManyConnectionsError",
        "UndefinedColumnError",
        "UndefinedTableError",
        "UniqueViolationError",
        # The vendor's transport, curl_cffi's.
        "CurlError",
        "HTTPError",
        "ReadTimeout",
        "ConnectTimeout",
        "DNSError",
        "SSLError",
        # pydantic's, numpy's, exchange_calendars' and yfinance's.
        "ValidationError",
        "LinAlgError",
        "DateOutOfBounds",
        "NotSessionError",
        "YFRateLimitError",
        "YFPricesMissingError",
        "YFTzMissingError",
        # This repository's.
        "DataSourceError",
        "InsufficientDataError",
        "BacktestJobError",
        "WalkForwardJobError",
    }
)

#: Words no vocabulary word, HTTP token or exception name may be or hold as a
#: part (docs/09, section 4.3):
#:
#: (a) every word an alternative of the code screen's ``instruction_phrase``
#: requires and cannot do without, so no skeleton can spell an instruction;
#: (b) the model vendors' names; (c) the sleeves and every ticker in the
#: fixtures and docs; (d) names of a person, place, venue, vendor or account.
NEVER_IN_VOCABULARY: frozenset[str] = frozenset(
    {
        # (a) The verbs.
        "ignore",
        "disregard",
        "forget",
        "override",
        "bypass",
        "follow",
        "following",
        "obey",
        "obeying",
        "heed",
        "heeding",
        "answer",
        "respond",
        "reply",
        "classify",
        "label",
        "categorise",
        "categorize",
        "mark",
        "score",
        "tag",
        "output",
        "print",
        # (a) The role words.
        "system",
        "assistant",
        "user",
        "developer",
        "human",
        # (a) The targets.
        "instructions",
        "instruction",
        "prompt",
        "prompts",
        "direction",
        "directions",
        "guideline",
        "guidelines",
        # (a) The targets as the screen also reads them, run together or
        # bracketed: ``systemprompt``, ``[inst]``, ``<<sys>>``.
        "systemprompt",
        "systemprompts",
        "developerprompt",
        "developerprompts",
        "inst",
        "sys",
        # (a) The address words.
        "you",
        "ai",
        "model",
        "chatbot",
        "bot",
        "llm",
        # (a) The rest.
        "as",
        "this",
        "it",
        "me",
        "title",
        "text",
        "paper",
        "item",
        "entry",
        # (b) The model vendors.
        "jev",
        "typesafe",
        "claude",
        "anthropic",
        "chatgpt",
        "openai",
        "gpt",
        # (c) The sleeves and the tickers of the fixtures and docs.
        "spy",
        "ief",
        "gsg",
        "aapl",
        "amzn",
        "googl",
        "msft",
        "nvda",
        # (d) Venues, vendors and accounts.
        "alpaca",
        "yahoo",
        "yfinance",
        "cryptocom",
        "bankr",
        "nyse",
        "xnys",
    }
)

#: Every token a skeleton may hold, sorted: ``JobErrorState.error``'s Literal,
#: exactly (``tests/unit/test_jev_redact.py``).
TOKENS: tuple[str, ...] = tuple(
    sorted(
        VOCABULARY | EXCEPTION_NAMES | frozenset(HTTP_TOKENS) | frozenset(PLACEHOLDERS)
    )
)

#: The rules, by name, in the order :func:`skeleton` applies them (the module
#: docstring); hashed, so a rule moved is a new version.
RULES: tuple[str, ...] = (
    "0_not_text_or_cut",
    "1_chunks_and_kept_tokens",
    "2_pieces_and_quoted_runs",
    "3_strip",
    "4_not_printable_ascii",
    "5_address",
    "6_key_value",
    "7_after_a_secret_lead",
    "8_path",
    "9_date_or_time",
    "10_dotted",
    "11_number_or_http_status",
    "12_digit",
    "13_exception_name",
    "14_capitals",
    "15_vocabulary",
    "16_word",
    "collapse",
    "truncate",
    "collapse",
)

_KEPT_CHUNKS = frozenset(PLACEHOLDERS) | frozenset(HTTP_TOKENS)
_SPLIT = re.compile("[" + re.escape(SPLIT_CHARACTERS) + "]")
_DATE = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}"
    r"(?:[Tt ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
    r"(?:[Zz]|[+-]\d{2}(?::?\d{2})?)?",
    re.ASCII,
)
_TIME = re.compile(
    r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}(?::?\d{2})?)?", re.ASCII
)
_DECIMAL = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
_INTEGER = re.compile(r"[+-]?\d+", re.ASCII)
_DIGIT = re.compile(r"\d", re.ASCII)
_STATUS = re.compile(r"[1-5]\d\d", re.ASCII)


def skeleton(text: object) -> tuple[str, ...]:
    """
    ``text`` reduced to tokens of :data:`TOKENS`, by the module's rules: at
    most :data:`SKELETON_MAX_TOKENS` of them, from at most
    :data:`MAX_INPUT_CHARS` characters. ``()`` for anything that is not a
    ``str``. Never raises, for any input of any type, and is deterministic.

    The rules are written to raise on nothing; should one ever raise, the
    skeleton is ``()``, which :func:`admissible` refuses, so a defect here
    sends nothing rather than something unread
    (``tests/unit/test_jev_redact.py::TestTotal`` drives the rules themselves
    over the fuzz, outside this guard).
    """
    if not isinstance(text, str):
        return ()
    try:
        tokens = _tokens(text[:MAX_INPUT_CHARS])
    except Exception:  # noqa: BLE001 - total by contract: fails closed to nothing
        return ()
    tokens = _collapsed(tokens)
    if len(tokens) > SKELETON_MAX_TOKENS:
        tokens = [*tokens[: SKELETON_MAX_TOKENS - 1], MORE]
    return tuple(_collapsed(tokens))


def _tokens(text: str) -> list[str]:
    """Rules 1 to 16, over every chunk and piece of ``text``, in order."""
    out: list[str] = []
    state = _State()
    for chunk in text.split():
        if state.closing is None and chunk in _KEPT_CHUNKS:
            out.append(chunk)
            state.previous = chunk
            state.pending = None
            continue
        for piece in _SPLIT.split(chunk):
            if piece:
                out.extend(_piece(piece, state))
    if state.closing is not None and not state.quoted_value:
        # A run closed by the end of the text.
        out.append(QUOTED)
    return out


class _State:
    """What reading a piece needs to know of the pieces before it."""

    __slots__ = ("closing", "pending", "previous", "quoted_value")

    def __init__(self) -> None:
        #: The quote character an open run waits for, or ``None``.
        self.closing: str | None = None
        #: Whether the open run is a ``key=value``'s value, already emitted.
        self.quoted_value = False
        #: The previous piece, read as a lead word (rules 7 and 11).
        self.previous: str | None = None
        #: What the next piece is emitted as, when an ``=`` left a key's value
        #: to it (rule 6): ``[value]``, ``[secret]``, or ``None``.
        self.pending: str | None = None


def _piece(piece: str, state: _State) -> list[str]:
    """One piece, by rules 2 to 16."""
    if state.closing is not None:
        if _ends_with(piece, state.closing):
            emitted = [] if state.quoted_value else [QUOTED]
            state.closing = None
            state.quoted_value = False
            state.previous = None
            return emitted
        return []
    opened = piece.lstrip(STRIP_CHARACTERS)
    if not opened.rstrip(STRIP_CHARACTERS):
        # Nothing but rule 3's characters: emitted as nothing, and no piece,
        # so a lead word before it still leads (rule 7).
        return []
    if not opened.strip("="):
        # ``key = value`` written apart: the piece before was the key, and
        # the next is its value, never emitted (rule 6).
        if state.pending is None:
            secret = state.previous in SECRET_WORDS or state.previous in SECRET_LEADS
            state.pending = SECRET if secret else VALUE
        return []
    if state.pending is not None:
        hidden, state.pending = state.pending, None
        # Hidden, yet still read as a lead word: ``headers= password: x``
        # hides ``x`` as well (rule 7).
        state.previous = _lead_word(piece)
        if opened[0] in QUOTE_CHARACTERS and not _closes_itself(opened):
            state.closing = opened[0]
            state.quoted_value = True
        return [hidden]
    if opened[0] in QUOTE_CHARACTERS:
        state.previous = None
        if _closes_itself(opened):
            return [QUOTED]
        state.closing = opened[0]
        state.quoted_value = False
        return []
    lead = state.previous
    state.previous = _lead_word(piece)
    return _word(piece, lead, state)


def _ends_with(piece: str, quote: str) -> bool:
    """Whether ``piece`` ends with ``quote`` once rule 3's characters are set
    aside from its end."""
    stripped = piece.rstrip(STRIP_CHARACTERS)
    return bool(stripped) and stripped[-1] == quote


def _closes_itself(opened: str) -> bool:
    """Whether a piece opening a quote also closes it: two characters or more
    before rule 3's, the last the quote it opened with."""
    return len(opened.rstrip(STRIP_CHARACTERS)) > 1 and _ends_with(opened, opened[0])


def _lead_word(piece: str) -> str:
    """``piece`` as a lead word (rules 7 and 11): casefolded, rule 3's
    characters stripped, leading dashes dropped, and one trailing ``=``."""
    word = piece.strip(STRIP_CHARACTERS).casefold().lstrip("-")
    if word.endswith("=") and word.count("=") == 1:
        word = word[:-1]
    return word


def _word(piece: str, lead: str | None, state: _State) -> list[str]:
    """Rules 3 to 16 for one piece outside a quoted run."""
    piece = piece.strip(STRIP_CHARACTERS)
    if not piece:
        return []
    if not all("!" <= ch <= "~" for ch in piece):
        return [WORD]
    if "://" in piece or piece.startswith("www.") or "@" in piece:
        return [ADDRESS]
    if "=" in piece:
        key, _, value = piece.partition("=")
        emitted = _word(key, lead, state) if key else []
        hidden = SECRET if key.casefold() in SECRET_WORDS else VALUE
        if not value.strip("="):
            # ``key=`` with its value written after a space: the next piece
            # is the value, never emitted.
            state.pending = hidden
        elif value[0] in QUOTE_CHARACTERS and not _closes_itself(value):
            # The value is never emitted: what its quote spans goes with it.
            state.closing = value[0]
            state.quoted_value = True
        return [*emitted, hidden]
    if lead in SECRET_LEADS:
        return [SECRET]
    if "/" in piece or "\\" in piece:
        return [PATH]
    if _DATE.fullmatch(piece):
        return [DATE]
    if _TIME.fullmatch(piece):
        return [TIME]
    if "." in piece:
        return [NUMBER] if _DECIMAL.fullmatch(piece) else [ADDRESS]
    if _INTEGER.fullmatch(piece):
        if lead in HTTP_LEADS and _STATUS.fullmatch(piece):
            listed = f"http_{piece}"
            return [listed if listed in HTTP_TOKENS else HTTP_OTHER]
        return [NUMBER]
    if _DIGIT.search(piece):
        return [ID]
    if piece in EXCEPTION_NAMES:
        return [piece]
    folded = piece.casefold()
    if sum("A" <= ch <= "Z" for ch in piece) >= 2:
        return [folded] if folded in CAPS_VOCABULARY else [NAME]
    if folded in VOCABULARY:
        return [folded]
    return [WORD]


def _collapsed(tokens: Sequence[str]) -> list[str]:
    """A run of one placeholder repeated, collapsed to one."""
    out: list[str] = []
    for token in tokens:
        if out and token == out[-1] and token in PLACEHOLDERS:
            continue
        out.append(token)
    return out


def content_tokens(tokens: Iterable[str]) -> list[str]:
    """The tokens a cause could be read from: vocabulary words outside
    :data:`FUNCTION_WORDS`, exception names and HTTP tokens, in order."""
    return [
        token
        for token in tokens
        if (token in VOCABULARY and token not in FUNCTION_WORDS)
        or token in EXCEPTION_NAMES
        or token in HTTP_TOKENS
    ]


def admissible(tokens: Iterable[str]) -> bool:
    """
    Whether a skeleton may be asked about: at least
    :data:`MIN_CONTENT_TOKENS` content tokens (:func:`content_tokens`). A
    skeleton of placeholders and function words says nothing a cause could be
    read from, and asking about it would spend a call on noise.
    """
    return len(content_tokens(tokens)) >= MIN_CONTENT_TOKENS


def redactor_sha256() -> str:
    """
    sha256 of the redactor's definition as compact JSON: its version, every
    set, sorted; the placeholders in order with their meanings; the secret
    words and leads; the split, strip and quote characters; the rule names in
    order; both bounds and :data:`MIN_CONTENT_TOKENS`. What the ops set plan
    names, what :data:`GOLDEN_REDACTOR_SHA256` pins, and what the test holds
    each released version to.
    """
    definition = {
        "version": REDACTOR_VERSION,
        "triaged_kinds": sorted(TRIAGED_KINDS),
        "vocabulary": sorted(VOCABULARY),
        "function_words": sorted(FUNCTION_WORDS),
        "caps_vocabulary": sorted(CAPS_VOCABULARY),
        "exception_names": sorted(EXCEPTION_NAMES),
        "http_tokens": sorted(HTTP_TOKENS),
        "http_leads": sorted(HTTP_LEADS),
        "never_in_vocabulary": sorted(NEVER_IN_VOCABULARY),
        "placeholders": [[token, meaning] for token, meaning in PLACEHOLDERS.items()],
        "secret_words": sorted(SECRET_WORDS),
        "secret_leads": sorted(SECRET_LEADS),
        "split_characters": SPLIT_CHARACTERS,
        "strip_characters": STRIP_CHARACTERS,
        "quote_characters": QUOTE_CHARACTERS,
        "rules": list(RULES),
        "skeleton_max_tokens": SKELETON_MAX_TOKENS,
        "max_input_chars": MAX_INPUT_CHARS,
        "min_content_tokens": MIN_CONTENT_TOKENS,
    }
    text = json.dumps(definition, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "CAPS_VOCABULARY",
    "EXCEPTION_NAMES",
    "FUNCTION_WORDS",
    "GOLDEN_REDACTOR_SHA256",
    "HTTP_LEADS",
    "HTTP_LISTED",
    "HTTP_OTHER",
    "HTTP_TOKENS",
    "MAX_INPUT_CHARS",
    "MIN_CONTENT_TOKENS",
    "MORE",
    "NEVER_IN_VOCABULARY",
    "PLACEHOLDERS",
    "QUOTE_CHARACTERS",
    "REDACTOR_VERSION",
    "RULES",
    "SECRET_LEADS",
    "SECRET_WORDS",
    "SKELETON_MAX_TOKENS",
    "SPLIT_CHARACTERS",
    "STRIP_CHARACTERS",
    "TOKENS",
    "TRIAGED_KINDS",
    "VOCABULARY",
    "admissible",
    "content_tokens",
    "redactor_sha256",
    "skeleton",
]
