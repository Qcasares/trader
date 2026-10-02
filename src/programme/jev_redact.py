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
   :data:`QUOTE_CHARACTERS` is closed at the end of a later chunk ending with
   the same character — read once its trailing :data:`SPLIT_CHARACTERS` and
   :data:`STRIP_CHARACTERS` are set aside, so ``'x'.`` and ``'x'),`` close
   where they end — or by the end of the text, and the whole run is one
   ``[quoted]``. A piece beginning and ending with the quote is a run of its
   own unless the rest of its chunk ends with the quote too. An apostrophe
   inside a word opens nothing.
3. Leading and trailing :data:`STRIP_CHARACTERS` are stripped, so no colon
   survives; a piece left empty is emitted as nothing.
4. Any character outside printable ASCII (:data:`PRINTABLE_ASCII`) gives
   ``[word]``.
5. A chunk holding one of :data:`ADDRESS_MARKERS`, ``://`` or ``@``, or with a
   piece starting with one of :data:`ADDRESS_PREFIXES`, ``www.``, gives one
   ``[address]`` for the whole chunk, read before rule 2 splits it.
6. ``key=value`` gives the key, by these rules, then ``[value]``, or
   ``[secret]`` for a credential's key (rule 7's). The value is never
   emitted, and it is the rest of the chunk after the ``=``, whatever rule 2
   would split it on. A tuple's values — an ``=`` straight after
   :data:`TUPLE_KEY_END`, as in PostgreSQL's ``Key (a, b)=(x, y)`` — are the
   rest of the line. A value written after a space — ``key= value``, ``key =
   value`` — is the next chunk.
7. A credential's lead hides as ``[secret]`` the rest of its chunk, or, when
   nothing follows in it, the whole next chunk. A lead is a word in
   :data:`SECRET_LEADS`, a compound key holding one as a part
   (:data:`KEY_PART_SEPARATORS`: ``access_token``, ``client_secret``), or a key
   ending with one of :data:`SECRET_SUFFIXES` (``PGPASSWORD``); a word of
   :data:`SECRET_WORDS`, or a compound holding one, leads only written as a
   key — ``dsn:``, ``"dsn":``, ``dsn :`` — and ``password:x`` holds a lead
   and its value in one piece. The word is read casefolded, with its leading
   dashes dropped, its rule 3 characters stripped, and one trailing ``=``
   dropped, and only a word shaped as a key (:data:`KEY_SHAPE`) is one. What
   stands between a lead and its value made only of rule 2's and rule 3's
   characters and :data:`ARROW_CHARACTERS` (``->``, ``=>``, ``-``) is read as
   neither. After one of :data:`SCHEME_LEADS` two chunks are hidden, a
   scheme's and the credential's (``Authorization: Key x``). A value or a
   credential hidden still leads when it ends with a lead
   (``Authorization=Bearer x``, ``headers= password: x``).
8. A piece containing one of :data:`PATH_CHARACTERS`, ``/`` or ``\\``, gives
   ``[path]``.
9. A date gives ``[date]``, and a time of day ``[time]``.
10. A dotted run gives ``[number]`` when it is a decimal, and ``[address]``
    otherwise.
11. A number directly after ``http``, ``status`` or ``code`` and from 100 to
    599 gives ``http_NNN`` when listed in :data:`HTTP_TOKENS`, and
    ``http_other`` otherwise. Any other number gives ``[number]``.
12. Any digit left in a piece gives ``[id]``.
13. A piece exactly an :data:`EXCEPTION_NAMES` entry gives itself.
14. :data:`NAME_CAPITALS` capitals or more give ``[name]``, unless the
    casefolded piece is in :data:`CAPS_VOCABULARY`, which gives that word.
15. A piece whose casefolded form is in :data:`VOCABULARY` gives that word.
16. Anything else gives ``[word]``.

Then, in this order: a run of one placeholder repeated collapses to one; over
:data:`SKELETON_MAX_TOKENS` tokens, the first 47 are kept and ``[more]``
added; and runs are collapsed again. The third step is what makes the
redactor idempotent — ``skeleton(" ".join(skeleton(x))) == skeleton(x)`` —
since an input whose 47th token is a literal ``[more]`` would otherwise end
``[more] [more]``, which read again is another skeleton (docs/09, D-HMB-09).

Wider than the design's sentences, and each only hides more
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Version 1 read rules 5, 6 and 7 on pieces, after rule 2 had split a chunk,
so whatever of a password, a DSN or a tuple's values followed a ``,;()[]{}|``
was read as a new, ordinary piece: verbatim when a vocabulary word, and its
class otherwise, so two passwords of one shape gave two skeletons (D3's
review, D3RR-1). Version 2 reads them on chunks, lines and runs as rule by
rule above, and closes a quoted run only at a chunk's end, where no bracket
of a quoted value can stop it; and it hides a credential in the marked forms
version 1 missed — ``key:`` for every key of :data:`SECRET_WORDS`, compound
keys, an arrow, a scheme written as a value, a quoted key (D3RR-2). Version
1's own wider readings stand: rule 7's word sets aside a rule 3 character
and a trailing ``=`` as well as its casefold and dashes, and a value hidden
still leads; rule 6's value is the next chunk when it is written apart, and
what a quote opened in it spans; and a quote is read after rule 3's
characters at a piece's start, so ``:'a b'`` is one ``[quoted]``. The hash
below pins every datum they read, and the test pins what they do (docs/08,
D3 as built).

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
the test, beside a hash of what each released version makes of a fixed
corpus. Once an ``ops.job_error`` answer is on record, a change of vocabulary
or rules is a new ``ops.job_error`` version, since the same words over another
skeleton are another question (docs/08 open items 77 and 87), and the ops set
plan names the hash its answers were recorded under. Version 2 replaced
version 1 before D3 merged, while no ``ops.job_error`` answer existed and
every switch was off: ``ops.job_error`` v1 is asked under it, and its set
plan, which names it, is plan version 2.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType

#: The redactor's version, which :func:`redactor_sha256` hashes with every set
#: and rule below. Version 2 reads rules 5 to 7 on chunks rather than pieces
#: and hides the marked forms version 1 missed (D3's review, D3RR-1 and
#: D3RR-2), and hashes the rules' data (D3RR-3).
REDACTOR_VERSION = 2

#: :func:`redactor_sha256` of this version, pinned beside the rules. A test
#: compares the two, and holds this one to the append-only history of released
#: versions kept in ``tests/unit/test_jev_redact.py``, so re-recording it after
#: a change still fails there.
GOLDEN_REDACTOR_SHA256 = (
    "ed4585f4750734e4615fc193300fddbc858fcb234462d3667bb859e05c1a3814"
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

#: What makes a whole chunk one ``[address]`` wherever in it it stands (rule
#: 5): a scheme's separator and a user's or a host's ``@``. Read on the chunk,
#: before rule 2 splits it, so a password inside a DSN never starts a piece.
ADDRESS_MARKERS: tuple[str, ...] = ("://", "@")

#: What makes a whole chunk one ``[address]`` at the start of any of its
#: pieces, after rule 3's characters and a quote (rule 5).
ADDRESS_PREFIXES: tuple[str, ...] = ("www.",)

#: What makes a piece a ``[path]`` (rule 8).
PATH_CHARACTERS = "/\\"

#: The first and the last character rule 4 reads as printable ASCII.
PRINTABLE_ASCII: tuple[str, str] = ("!", "~")

#: How many capitals make a piece a ``[name]`` (rule 14).
NAME_CAPITALS = 2

#: The character before an ``=`` that makes its key a tuple, as PostgreSQL's
#: DETAIL writes one: ``Key (kind, status)=(backtest, failed)``. A tuple's
#: values are hidden to the end of their line (rule 6), since a value may hold
#: anything, a space and a bracket included.
TUPLE_KEY_END = ")"

#: What separates a compound key's parts (rule 7): ``client_secret``,
#: ``X-Api-Key``, ``db.password``.
KEY_PART_SEPARATORS = "-_."

#: What a credential's key may end with when run into a prefix with no
#: separator, as ``PGPASSWORD`` and ``dbpassword`` do (rule 7).
SECRET_SUFFIXES: tuple[str, ...] = ("password", "passwd", "secret", "token", "apikey")

#: What a chunk standing between a secret's lead and its value may be made of,
#: beside rule 2's and rule 3's characters, and be read as neither: ``password
#: -> x``, ``password => x``, ``password - x`` (rule 7).
ARROW_CHARACTERS = "-=<>"

#: Leads whose value is a scheme and then a credential, so two chunks after
#: them are hidden, not one: ``Authorization: Bearer x``, ``Authorization: Key
#: x`` (rule 7).
SCHEME_LEADS: frozenset[str] = frozenset({"authorization"})

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
_PIECE = re.compile("[^" + re.escape(SPLIT_CHARACTERS) + "]+")
_ADDRESS_START = re.compile(
    "(?:^|["
    + re.escape(SPLIT_CHARACTERS)
    + "])["
    + re.escape(STRIP_CHARACTERS + QUOTE_CHARACTERS)
    + "]*(?:"
    + "|".join(re.escape(prefix) for prefix in ADDRESS_PREFIXES)
    + ")"
)
_KEY_PARTS = re.compile("[" + re.escape(KEY_PART_SEPARATORS) + "]+")

#: What a word read as a key looks like (rule 7): casefolded letters and
#: digits, and :data:`KEY_PART_SEPARATORS`.
KEY_SHAPE = re.compile("[a-z0-9" + re.escape(KEY_PART_SEPARATORS) + "]+")
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

#: Every pattern a rule reads by, by name: hashed with the rest of the
#: definition (:func:`redactor_sha256`), so a pattern narrowed or widened is
#: a new version (docs/08, D3 as built; D3's review, D3RR-3).
PATTERNS: Mapping[str, re.Pattern[str]] = MappingProxyType(
    {
        "piece": _PIECE,
        "address_start": _ADDRESS_START,
        "key_parts": _KEY_PARTS,
        "key_shape": KEY_SHAPE,
        "date": _DATE,
        "time": _TIME,
        "decimal": _DECIMAL,
        "integer": _INTEGER,
        "digit": _DIGIT,
        "status": _STATUS,
    }
)

# How a key marks what follows it (rule 7): not at all; only when written
# ``key:`` (or ``key=``, which rule 6 hides whatever the key); or always, as a
# lead whose value comes next with or without a colon.
_NOT_A_KEY, _COLON_KEY, _LEAD = 0, 1, 2


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
    """
    Rules 1 to 16, over every line, chunk and piece of ``text``, in order.
    Lines matter to one reading alone: a tuple's values, hidden to the end of
    their line (rule 6). ``str.splitlines`` breaks only where ``str.split``
    does, so the chunks are ``text.split()``'s
    (``tests/unit/test_jev_redact.py::TestEachRule::test_lines_change_no_chunk``).
    """
    out: list[str] = []
    state = _State()
    for line in text.splitlines():
        for chunk in line.split():
            _chunk(chunk, state, out)
        state.to_line_end = False
    if state.closing is not None and not state.quoted_value:
        # A run closed by the end of the text.
        out.append(QUOTED)
    return out


class _State:
    """What reading a chunk needs to know of the chunks before it."""

    __slots__ = (
        "awaiting_colon",
        "closing",
        "pending",
        "pending_chunks",
        "previous",
        "quoted_value",
        "to_line_end",
    )

    def __init__(self) -> None:
        #: The quote character an open run waits for, or ``None``.
        self.closing: str | None = None
        #: Whether the open run is a value's or an address's, already emitted.
        self.quoted_value = False
        #: The previous piece, read as a lead word (rule 11).
        self.previous: str | None = None
        #: What the next chunk is emitted as, unread, when a key or a lead left
        #: its value to it (rules 6 and 7): ``[value]``, ``[secret]`` or
        #: ``None``; and how many chunks it takes.
        self.pending: str | None = None
        self.pending_chunks = 0
        #: How many chunks a credential's key ending its chunk would hide, were
        #: the next chunk a colon written apart (``dsn : x``); 0 for none.
        self.awaiting_colon = 0
        #: Whether the rest of the line is a tuple's values (rule 6).
        self.to_line_end = False


def _chunk(chunk: str, state: _State, out: list[str]) -> None:
    """One whitespace-delimited chunk, by rules 1 to 16."""
    if state.to_line_end:
        return
    awaiting, state.awaiting_colon = state.awaiting_colon, 0
    if state.closing is None:
        if chunk in _KEPT_CHUNKS:
            out.append(chunk)
            state.previous = chunk
            state.pending, state.pending_chunks = None, 0
            return
        if state.pending is not None:
            if _between(chunk):
                # ``password : x``, ``password -> x``: what stands between a
                # lead and its value is neither (rule 7).
                return
            token = state.pending
            state.pending_chunks -= 1
            if state.pending_chunks <= 0:
                state.pending, state.pending_chunks = None, 0
            _hidden(chunk, token, state, out)
            return
        if awaiting and chunk.startswith(":"):
            # ``dsn : x``: the colon written apart from a credential's key.
            _hide_after(chunk[1:], SECRET, awaiting, state, out)
            return
    rest = chunk
    while rest:
        rest = _segment(rest, state, out)


def _between(chunk: str) -> bool:
    """Whether ``chunk`` is only what may stand between a lead and its value:
    rule 2's and rule 3's characters, and :data:`ARROW_CHARACTERS`."""
    return not chunk.strip(SPLIT_CHARACTERS + STRIP_CHARACTERS + ARROW_CHARACTERS)


def _segment(text: str, state: _State, out: list[str]) -> str:
    """
    ``text``, a chunk or what is left of one, read from its start until a
    quoted run opens in it, when what follows is returned to be read in the
    run; ``""`` once the chunk is read or hidden.
    """
    if state.to_line_end:
        return ""
    if state.closing is not None:
        # A run closes where a chunk ends with its quote, rule 2's and rule
        # 3's characters set aside: never inside a chunk, where a bracket or a
        # comma of a quoted value may as well not be there. A quoted key it
        # ends with still leads: in ``"{"password": x}"`` the run closes on
        # ``"password":``.
        if _ends_quoted(text, state.closing):
            if not state.quoted_value:
                out.append(QUOTED)
            state.closing = None
            state.quoted_value = False
            state.previous = None
            pieces = _PIECE.findall(text)
            if pieces:
                _leaves(pieces[-1], state)
        return ""
    if _is_address(text):
        # Rule 5, on the whole of what is left of the chunk: a DSN's password,
        # a user's name, a URL's query, whatever rule 2 would split them on.
        _hidden(text, ADDRESS, state, out, leads=False)
        return ""
    for match in _PIECE.finditer(text):
        piece = match.group()
        after = text[match.end() :]
        opened = piece.lstrip(STRIP_CHARACTERS)
        if not opened.rstrip(STRIP_CHARACTERS):
            # Nothing but rule 3's characters: emitted as nothing, and no piece.
            continue
        if opened[0] in QUOTE_CHARACTERS:
            state.previous = None
            if not _closes_itself(opened) or _ends_quoted(after, opened[0]):
                # A quote closes in its own piece only where the rest of its
                # chunk does not end with it: in ``"password="(x)""`` the piece
                # ``"password="`` stops at a bracket of the value, which may as
                # well not be there (rule 2).
                state.closing = opened[0]
                state.quoted_value = False
                return after
            out.append(QUOTED)
        elif "=" in piece:
            _key_value(text, match.start(), piece, state, out)
            return ""
        else:
            stripped = piece.strip(STRIP_CHARACTERS)
            key, colon, value = stripped.partition(":")
            if colon and value and _secrecy(_lead_word(key)) != _NOT_A_KEY:
                # ``password:x``: a credential's key and its value in one piece.
                out.extend(_word(key, state.previous))
                _hide_after(value + after, SECRET, _units(_lead_word(key)), state, out)
                return ""
            lead = state.previous
            state.previous = _lead_word(piece)
            out.extend(_word(piece, lead))
        # Rule 7: a credential's lead — ``password``, ``dsn:``, ``"password":``
        # — hides the rest of its chunk, or what it leaves to the next.
        if not after.strip(SPLIT_CHARACTERS + STRIP_CHARACTERS):
            _leaves(piece, state)
            return ""
        units = _leads_as(*_key_of(piece))
        if units:
            _hide_after(after, SECRET, units, state, out)
            return ""
    return ""


def _key_value(
    text: str, start: int, piece: str, state: _State, out: list[str]
) -> None:
    """
    Rule 6 for a piece holding ``=`` at ``start`` in ``text``: the key, by the
    rules, then ``[secret]`` for a credential's key and ``[value]`` for any
    other, and the value never read. The value is the rest of the chunk,
    whatever rule 2 would split it on; a value written apart is the next
    chunk; and a tuple's values are the rest of the line.
    """
    index = piece.index("=")
    key = piece[:index]
    position = start + index
    value = text[position + 1 :]
    if key.strip(STRIP_CHARACTERS):
        word = _lead_word(key)
        out.extend(_word(key, state.previous))
    else:
        # ``status)=(``: rule 2 split the key from its ``=``.
        word = state.previous or ""
    secret = _secrecy(word) != _NOT_A_KEY
    hidden = SECRET if secret else VALUE
    state.previous = None
    if not key and position > 0 and text[position - 1] == TUPLE_KEY_END:
        out.append(hidden)
        state.to_line_end = True
        return
    if not _has_content(value):
        # ``key=`` or ``key =`` with its value written after a space.
        if key.strip(STRIP_CHARACTERS):
            out.append(hidden)
        state.pending = hidden
        state.pending_chunks = _units(word) if secret else 1
        return
    _hide_after(value, hidden, _units(word) if secret else 1, state, out)


def _hide_after(
    region: str, token: str, units: int, state: _State, out: list[str]
) -> None:
    """
    ``units`` of what follows a lead or a key hidden as ``token``: ``region``,
    the rest of its chunk, if anything is in it, then whole chunks.
    """
    if _has_content(region):
        _hidden(region, token, state, out)
        units -= 1
    if units > 0 and state.closing is None:
        state.pending = token
        state.pending_chunks = max(state.pending_chunks, units)


def _hidden(
    region: str, token: str, state: _State, out: list[str], *, leads: bool = True
) -> None:
    """
    ``region``, a value, a credential or an address, emitted as ``token`` and
    never read. A quote it leaves open hides what follows up to the piece that
    closes it. A value or a credential ending with a lead hides what follows
    it, so a value hidden still leads (``headers= password: x``,
    ``Authorization=Bearer x``); an address is no key, and leads nothing.
    """
    out.append(token)
    state.previous = None
    quote = _left_open(region)
    if quote is not None:
        state.closing = quote
        state.quoted_value = True
        state.pending, state.pending_chunks = None, 0
        return
    pieces = _PIECE.findall(region)
    if leads and pieces:
        _leaves(pieces[-1], state)


def _leaves(piece: str, state: _State) -> None:
    """
    What the last piece of a chunk, or of a value hidden in one, leaves to the
    next chunk (rules 6 and 7): the value of a key written ``key=`` with its
    value apart, hidden as ``[value]``, or ``[secret]`` after a credential's
    key; a lead's credential, ``[secret]``, the value of ``key=value`` read as
    one (``Authorization=Bearer``); or the colon a credential's key may still
    be written with (``dsn : x``).
    """
    if "=" in piece:
        key, _, value = piece.rpartition("=")
        if _has_content(value):
            # The value hidden with its key still leads.
            _leaves(value, state)
            return
        word = _key_of(key)[0]
        if _secrecy(word) == _NOT_A_KEY:
            _pend(state, VALUE, 1)
        else:
            _pend(state, SECRET, _units(word))
        return
    key, colon, value = piece.strip(STRIP_CHARACTERS).rpartition(":")
    if colon and key and _secrecy(_lead_word(key)) != _NOT_A_KEY:
        # ``Authorization:Bearer``: a credential's key and its value in one
        # piece, the value hidden with it and leading still.
        if _units(_lead_word(key)) > 1:
            _pend(state, SECRET, _units(_lead_word(key)) - 1)
        _leaves(value, state)
        return
    word, colon = _key_of(piece)
    units = _leads_as(word, colon)
    if units:
        _pend(state, SECRET, units)
    elif _secrecy(word) == _COLON_KEY:
        state.awaiting_colon = _units(word)


def _pend(state: _State, token: str, units: int) -> None:
    """The next ``units`` chunks to be hidden as ``token``: ``[secret]`` wins
    over ``[value]``, and the longer reach over the shorter."""
    if state.pending != SECRET:
        state.pending = token
    state.pending_chunks = max(state.pending_chunks, units)


def _left_open(region: str) -> str | None:
    """The quote character ``region`` leaves open — the first one in it, when
    it holds an odd number of them — or ``None``."""
    for character in region:
        if character in QUOTE_CHARACTERS:
            return character if region.count(character) % 2 else None
    return None


def _has_content(region: str) -> bool:
    """Whether ``region`` holds anything but rule 2's and rule 3's characters
    and ``=``."""
    return bool(region.strip(SPLIT_CHARACTERS + STRIP_CHARACTERS + "="))


def _is_address(text: str) -> bool:
    """Whether ``text`` is an address by rule 5: a marker anywhere in it, or a
    prefix at the start of any of its pieces."""
    return (
        any(marker in text for marker in ADDRESS_MARKERS)
        or _ADDRESS_START.search(text) is not None
    )


def _ends_with(piece: str, quote: str) -> bool:
    """Whether ``piece`` ends with ``quote`` once rule 3's characters are set
    aside from its end."""
    stripped = piece.rstrip(STRIP_CHARACTERS)
    return bool(stripped) and stripped[-1] == quote


def _ends_quoted(text: str, quote: str) -> bool:
    """Whether ``text`` ends with ``quote`` once rule 2's and rule 3's
    characters are set aside from its end."""
    stripped = text.rstrip(SPLIT_CHARACTERS + STRIP_CHARACTERS)
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


def _secrecy(word: str) -> int:
    """
    How a key read as ``word`` (:func:`_lead_word`) marks what follows it
    (rule 7). A lead — in :data:`SECRET_LEADS`, holding one as a part
    (:data:`KEY_PART_SEPARATORS`), or ending with one of
    :data:`SECRET_SUFFIXES` — hides its value with or without a colon; a key
    in :data:`SECRET_WORDS`, holding one as a part or ending with one
    (``privateKey``), only when written ``key:``; and rule 6 hides the value
    of ``key=`` whatever the key. Only a word shaped as a key is one
    (:data:`KEY_SHAPE`): a path or an address ending ``/token`` leads nothing.
    """
    if not KEY_SHAPE.fullmatch(word):
        return _NOT_A_KEY
    parts = [part for part in _KEY_PARTS.split(word) if part]
    pairs = {"_".join(pair) for pair in zip(parts, parts[1:], strict=False)}
    if (
        word in SECRET_LEADS
        or any(part in SECRET_LEADS for part in parts)
        or pairs & SECRET_LEADS
        or word.endswith(SECRET_SUFFIXES)
    ):
        return _LEAD
    if (
        word in SECRET_WORDS
        or any(part in SECRET_WORDS for part in parts)
        or pairs & SECRET_WORDS
        or word.endswith(tuple(SECRET_WORDS))
    ):
        return _COLON_KEY
    return _NOT_A_KEY


def _units(word: str) -> int:
    """How many chunks a credential's key read as ``word`` hides: two after a
    scheme's lead (:data:`SCHEME_LEADS`), one after any other."""
    parts = [part for part in _KEY_PARTS.split(word) if part]
    scheme = word in SCHEME_LEADS or (bool(parts) and parts[-1] in SCHEME_LEADS)
    return 2 if scheme else 1


def _colon_after(piece: str) -> bool:
    """Whether ``piece`` ends with a colon among rule 3's characters."""
    return ":" in piece[len(piece.rstrip(STRIP_CHARACTERS)) :]


def _key_of(piece: str) -> tuple[str, bool]:
    """``piece`` read as a key (rule 7): the word it is, by
    :func:`_lead_word` — for a quoted key, ``"dsn":``, the word inside its
    quotes — and whether a colon follows it."""
    opened = piece.lstrip(STRIP_CHARACTERS)
    if opened and opened[0] in QUOTE_CHARACTERS and _closes_itself(opened):
        return _lead_word(opened.rstrip(STRIP_CHARACTERS)[1:-1]), _colon_after(piece)
    return _lead_word(piece), _colon_after(piece)


def _leads_as(word: str, colon: bool) -> int:
    """How many chunks a key read as ``word``, with a colon after it or not,
    hides after it: a lead's, or a credential's key written with its colon
    (``dsn:``, ``"dsn":``); 0 for none (rule 7)."""
    secrecy = _secrecy(word)
    if secrecy == _LEAD or (secrecy == _COLON_KEY and colon):
        return _units(word)
    return 0


def _word(piece: str, lead: str | None) -> list[str]:
    """Rules 3, 4 and 8 to 16 for one piece outside a quoted run."""
    piece = piece.strip(STRIP_CHARACTERS)
    if not piece:
        return []
    low, high = PRINTABLE_ASCII
    if not all(low <= ch <= high for ch in piece):
        return [WORD]
    if any(ch in PATH_CHARACTERS for ch in piece):
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
    if sum("A" <= ch <= "Z" for ch in piece) >= NAME_CAPITALS:
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
    words, leads and suffixes; the split, strip, quote, path and arrow
    characters, the address markers and prefixes, the printable range, the
    capitals that make a name, the tuple's mark and the key's separators;
    every pattern a rule reads by, as written and with its flags
    (:data:`PATTERNS`); the rule names in order; both bounds and
    :data:`MIN_CONTENT_TOKENS`. What the ops set plan names, what
    :data:`GOLDEN_REDACTOR_SHA256` pins, and what the test holds each released
    version to.

    The rules' data, not only their names (D3's review, D3RR-3): version 1
    hashed the names, so a pattern narrowed under them kept its hash. What no
    datum can say — how the code reads them — the test pins by what it does,
    the skeletons of a fixed corpus per released version
    (``tests/unit/test_jev_redact.py::TestPinned::test_the_behaviour_is_the_released_versions``).
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
        "secret_suffixes": sorted(SECRET_SUFFIXES),
        "scheme_leads": sorted(SCHEME_LEADS),
        "split_characters": SPLIT_CHARACTERS,
        "strip_characters": STRIP_CHARACTERS,
        "quote_characters": QUOTE_CHARACTERS,
        "address_markers": list(ADDRESS_MARKERS),
        "address_prefixes": list(ADDRESS_PREFIXES),
        "path_characters": PATH_CHARACTERS,
        "printable_ascii": list(PRINTABLE_ASCII),
        "name_capitals": NAME_CAPITALS,
        "tuple_key_end": TUPLE_KEY_END,
        "key_part_separators": KEY_PART_SEPARATORS,
        "arrow_characters": ARROW_CHARACTERS,
        "patterns": {
            name: [pattern.pattern, pattern.flags]
            for name, pattern in sorted(PATTERNS.items())
        },
        "rules": list(RULES),
        "skeleton_max_tokens": SKELETON_MAX_TOKENS,
        "max_input_chars": MAX_INPUT_CHARS,
        "min_content_tokens": MIN_CONTENT_TOKENS,
    }
    text = json.dumps(definition, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "ADDRESS_MARKERS",
    "ADDRESS_PREFIXES",
    "ARROW_CHARACTERS",
    "CAPS_VOCABULARY",
    "EXCEPTION_NAMES",
    "FUNCTION_WORDS",
    "GOLDEN_REDACTOR_SHA256",
    "HTTP_LEADS",
    "HTTP_LISTED",
    "HTTP_OTHER",
    "HTTP_TOKENS",
    "KEY_PART_SEPARATORS",
    "KEY_SHAPE",
    "MAX_INPUT_CHARS",
    "MIN_CONTENT_TOKENS",
    "MORE",
    "NAME_CAPITALS",
    "NEVER_IN_VOCABULARY",
    "PATH_CHARACTERS",
    "PATTERNS",
    "PLACEHOLDERS",
    "PRINTABLE_ASCII",
    "QUOTE_CHARACTERS",
    "REDACTOR_VERSION",
    "RULES",
    "SCHEME_LEADS",
    "SECRET_LEADS",
    "SECRET_SUFFIXES",
    "SECRET_WORDS",
    "SKELETON_MAX_TOKENS",
    "SPLIT_CHARACTERS",
    "STRIP_CHARACTERS",
    "TOKENS",
    "TRIAGED_KINDS",
    "TUPLE_KEY_END",
    "VOCABULARY",
    "admissible",
    "content_tokens",
    "redactor_sha256",
    "skeleton",
]
