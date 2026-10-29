import os
import re
import json
import traceback
from pathlib import Path

from flask_restful import Resource
from flask import request, current_app
from sqlalchemy import text

# -------------------------------
# Configuration
# -------------------------------
DEBUG_MODE = True

# Split models: SQL generation doesn't need reasoning; explanation prose benefits from it.
# Override via env vars without code changes.
MODEL_NAME_SQL     = os.getenv("ASKAI_MODEL_SQL",     "gpt-4.1-mini")
MODEL_NAME_EXPLAIN = os.getenv("ASKAI_MODEL_EXPLAIN", "gpt-5-mini")

MAX_ROWS = 500
EXPLANATION_ROW_LIMIT = 100

# Reasoning models (gpt-5-*, o1-*, o3-*) accept this; non-reasoning models ignore it
# (or error — so we only pass it when explicitly configured).
REASONING_EFFORT_SQL = os.getenv("ASKAI_REASONING_EFFORT_SQL", "")  # "", "minimal", "low", "medium", "high"

SQL_MAX_TOKENS     = int(os.getenv("ASKAI_SQL_MAX_TOKENS", "3000"))
EXPLAIN_MAX_TOKENS = int(os.getenv("ASKAI_EXPLAIN_MAX_TOKENS", "4000"))

# -------------------------------
# Paths (Server/AI/...)
# -------------------------------
AI_DIR = Path(__file__).resolve().parents[1] / "AI"
SCHEMA_DIR = AI_DIR / "schema"
PROMPTS_DIR = AI_DIR / "prompts"

SCHEMA_MD_PATH = SCHEMA_DIR / "dira_ai_schema.md"
SCHEMA_JSON_PATH = SCHEMA_DIR / "dira_ai_schema.json"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "dira_llm_system_prompt.txt"
RECON_RULES_PATH = PROMPTS_DIR / "reconciliation_rules.txt"


# -------------------------------
# Visualization contract prompt
# -------------------------------
VIZ_FORMAT_PROMPT = """
You are a UI response formatter. Given a user question, the SQL that was
run, and the result rows, produce a SINGLE JSON object (no prose, no
markdown fences, no comments) that describes how to render the answer in
a dashboard.

Return exactly this shape:

{
  "answer": "<1-3 sentence natural-language summary>",
  "viz": {
    "type": "table" | "stat" | "ranked_list" | "bar_chart" | "kv" | "text",
    "title": "<short title>",
    "subtitle": "<optional subtitle>",
    ...type-specific fields...
  }
}

Type-specific fields:

- "table":
    "columns": [{"key","label","type"}],   // type: "id"|"number"|"currency"|"date"|"badge"|"text"
    "rows": [...],                         // cleaned objects, one per row
    "footer": {"label","value"} | null

- "stat":
    "data": {"value","unit","label","sublabel","tone","icon"}
        // tone: "success"|"warning"|"danger"|"info"|"neutral"
        // icon: short semantic name like "award","cash","users","box"

- "ranked_list":
    "items": [{"rank","label","value","meta"}]

- "bar_chart":
    "series": [{"label","value"}],
    "unit": "<optional>"

- "kv":
    "pairs": [{"key","value"}]

- "text": (fallback — use only if nothing else fits)
    "body": "<markdown>"

RULES:
- Strip internal columns (user_id, promocode, note, timestamp, delivery)
  unless the user explicitly asked about them.
- Format currency values as numbers; the UI formats them.
- Format dates as ISO strings (YYYY-MM-DD).
- If there are <= 3 rows and a single dominant number → use "stat".
- If the question asks for "top"/"least"/"most"/"best"/"worst" →
  "stat" + "ranked_list" as secondary.
- If it asks for "compare"/"trend over time" and rows have a date + number →
  "bar_chart".
- If the user asks for a single employee/shop/item detail → "kv".
- Otherwise → "table".
- Never invent data that is not present in the rows.
- Do not include markdown, code fences, or explanation outside the JSON.
"""


# -------------------------------
# File loader (cached, reloads when file changes)
# -------------------------------
_file_cache = {}


def _read_file(path, as_json=False):
    """Read a file, cached by mtime. Returns None if missing/unreadable."""
    try:
        path = Path(path)
        if not path.exists():
            return None

        mtime = path.stat().st_mtime
        cached = _file_cache.get((str(path), as_json))
        if cached and cached[0] == mtime:
            return cached[1]

        content = path.read_text(encoding="utf-8")
        if as_json:
            content = json.loads(content)

        _file_cache[(str(path), as_json)] = (mtime, content)
        return content

    except Exception as e:
        print(f"Failed to read {path}: {e}")
        return None


def clear_file_cache():
    _file_cache.clear()


# -------------------------------
# Schema source reporting
# -------------------------------
def _schema_source():
    """Report which file the schema was actually loaded from."""
    md = _read_file(SCHEMA_MD_PATH)
    if md and md.strip():
        return f"file: {SCHEMA_MD_PATH}"
    js = _read_file(SCHEMA_JSON_PATH, as_json=True)
    if js:
        return f"file: {SCHEMA_JSON_PATH}"
    return "fallback: SQLAlchemy models"


# -------------------------------
# Simple Question Detection
# -------------------------------
def is_simple_question(question):
    """Detect greetings or non-database questions"""
    simple_patterns = [
        r"\bhello\b", r"\bhi\b", r"\bhey\b",
        r"\bhow are you\b",
        r"\bwhat do you do\b",
        r"\bwho are you\b",
        r"\bgood morning\b", r"\bgood afternoon\b", r"\bgood evening\b"
    ]
    q = question.lower()
    return any(re.search(pattern, q) for pattern in simple_patterns)


# -------------------------------
# Configuration / rules question detection
# -------------------------------
def detect_config_question(question):
    """Detect configuration-inspection questions that must bypass SQL."""
    q = re.sub(r"\s+", " ", (question or "").lower()).strip()
    patterns = {
        "all_rules": [
            r"\bshow\b.*\b(schema|configuration|config)\s+rules?\b",
            r"\bshow\s+me\s+the\s+rules\b",
            r"\bshow\b.*\ball\s+(ai\s+)?rules\b",
            r"\blist\b.*\bai\s+rules\b",
            r"\bshow\b.*\bschema\s+and\s+(ai\s+)?rules\b",
        ],
        "reconciliation_rules": [
            r"\b(reconciliation\s+rules?|rules?\s+for\s+reconciliation)\b",
        ],
        "system_prompt": [
            r"\b(system\s+prompt|ai\s+instructions|your instructions)\b",
        ],
        "schema": [
            r"\b(show|display|explain|read|view|list|get)\b.*\bschema\b",
            r"\bdatabase\s+structure\b",
            r"\btable\s+(names|structure|columns)\b",
            r"\bwhat\s+tables\b",
            r"\bwhich\s+tables\b",
        ],
    }
    for config_type in ("all_rules", "reconciliation_rules", "system_prompt", "schema"):
        if any(re.search(pattern, q) for pattern in patterns[config_type]):
            return config_type
    return None


def get_config_answer(config_type):
    """Read AI configuration files directly; never generate or execute SQL."""
    if config_type == "schema":
        content = get_database_schema()
        return f"## Database Schema\n\n{content}" if content else "The database schema could not be loaded."
    if config_type == "reconciliation_rules":
        content = get_reconciliation_rules()
        return f"## Reconciliation Rules\n\n{content}" if content else "The reconciliation rules file is empty or missing."
    if config_type == "system_prompt":
        content = get_system_prompt()
        return f"## AI System Instructions\n\n{content}" if content else "The AI system prompt is empty or missing."
    if config_type == "all_rules":
        schema = get_database_schema() or "Schema unavailable."
        reconciliation = get_reconciliation_rules() or "No reconciliation rules found."
        system_prompt = get_system_prompt() or "No system prompt found."
        return (
            "## Database Schema\n\n" + schema
            + "\n\n## Reconciliation Rules\n\n" + reconciliation
            + "\n\n## AI System Instructions\n\n" + system_prompt
        )
    return None


# -------------------------------
# Schema / Prompt Loading
# -------------------------------
def _schema_from_models():
    """Fallback: build schema text from SQLAlchemy metadata."""
    try:
        from app import db

        lines = []
        for table_name, table in db.Model.metadata.tables.items():
            lines.append(f"\nTable: {table_name}")

            for column in table.columns:
                line = f"  - {column.name} ({str(column.type)})"
                if column.primary_key:
                    line += " PRIMARY KEY"
                lines.append(line)

            for fk in table.foreign_keys:
                lines.append(
                    f"  FK: {fk.parent.name} -> {fk.column.table.name}.{fk.column.name}"
                )

        return "\n".join(lines)

    except Exception as e:
        print("Schema (models fallback) error:", str(e))
        return ""


def get_database_schema():
    """Prefer diraja_ai_schema.md, then JSON dump, then live models."""
    md = _read_file(SCHEMA_MD_PATH)
    if md and md.strip():
        return md.strip()

    js = _read_file(SCHEMA_JSON_PATH, as_json=True)
    if js:
        return json.dumps(js, indent=1, default=str)

    print("Schema files missing, falling back to SQLAlchemy models")
    return _schema_from_models()


def get_allowed_tables():
    """
    Table names from diraja_ai_schema.json. Returns None if it can't be
    determined, in which case the whitelist check is skipped.
    """
    js = _read_file(SCHEMA_JSON_PATH, as_json=True)
    if not js:
        return None

    names = set()

    def from_list(items):
        for t in items:
            if isinstance(t, dict):
                n = t.get("name") or t.get("table") or t.get("table_name")
                if n:
                    names.add(str(n).lower())
            elif isinstance(t, str):
                names.add(t.lower())

    if isinstance(js, dict):
        tables = js.get("tables", js)
        if isinstance(tables, list):
            from_list(tables)
        elif isinstance(tables, dict):
            names.update(k.lower() for k in tables.keys())
    elif isinstance(js, list):
        from_list(js)

    return names or None


def get_system_prompt():
    prompt = _read_file(SYSTEM_PROMPT_PATH)
    if prompt and prompt.strip():
        return prompt.strip()
    return getattr(current_app, "llm_system_prompt", "") or ""


def get_reconciliation_rules():
    rules = _read_file(RECON_RULES_PATH)
    return rules.strip() if rules else ""


# -------------------------------
# Schema scoping: send only what the question needs
# -------------------------------
_DOMAIN_KEYWORDS = {
    "sales":       ["sale", "sold", "revenue", "top selling", "best sell",
                    "payment", "customer", "loyalty"],
    "inventory":   ["stock", "inventory", "item", "product", "shop stock",
                    "transfer", "spoilt", "spoil", "broken"],
    "expenses":    ["expense", "creditor", "spent", "cost", "credit payment"],
    "purchasing":  ["supplier", "purchase", "bought", "inventory payment"],
    "accounting":  ["ledger", "account", "balance", " gl ", "bank"],
    "etims":       ["etims", "kra", "tax invoice"],
    "employees":   ["employee", "user", "staff", "clerk", "loan", "merit"],
    "shops":       ["shop", "branch", "location", "target"],
    "tasks":       ["task", "todo", "assignee"],
}

# Sections that should ALWAYS be included regardless of the question.
_ALWAYS_INCLUDE_PREFIXES = ("## 0.", "## 1.", "## 2.")


def pick_relevant_schema(schema_text, question):
    """
    Send only the schema sections relevant to the question plus the
    mandatory rules + domain map + join cheat-sheet. Falls back to the
    full schema when we can't decide.
    """
    if not schema_text:
        return schema_text

    q = (question or "").lower()
    wanted_domains = {
        d for d, kws in _DOMAIN_KEYWORDS.items() if any(k in q for k in kws)
    }

    # If the question is vague, send the full schema — the LLM may need it.
    if not wanted_domains:
        return schema_text

    parts = re.split(r"\n(?=## )", schema_text)
    keep = []
    for part in parts:
        head = part.lstrip()[:80]
        low = part.lower()

        # Always include the mandatory-rules / map / cheat-sheet sections.
        if any(head.startswith(p) for p in _ALWAYS_INCLUDE_PREFIXES):
            keep.append(part)
            continue

        # Include sections whose heading mentions a wanted domain.
        if any(d in low[:400] for d in wanted_domains):
            keep.append(part)

    # If narrowing somehow removed everything except the header, fall back.
    if len(keep) <= 3:
        return schema_text

    return "\n".join(keep)


# -------------------------------
# SQL Utilities
# -------------------------------
def clean_sql(sql):
    """Strip code fences, trailing comments, and trailing semicolons."""
    if not sql:
        return ""

    sql = sql.strip()

    # strip leading ```sql / ```mysql / ```
    sql = re.sub(r"\A```(?:mysql|sql)?[ \t]*\r?\n?", "", sql, flags=re.IGNORECASE)

    # strip trailing ```
    sql = re.sub(r"\r?\n?```[ \t]*\Z", "", sql)

    # strip trailing line comments (-- or #) outside quoted strings
    def strip_trailing_comment(s):
        out = []
        in_single = in_double = False
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == "'" and not in_double:
                in_single = not in_single
                out.append(ch); i += 1; continue
            if ch == '"' and not in_single:
                in_double = not in_double
                out.append(ch); i += 1; continue
            if not in_single and not in_double:
                if ch == '-' and i + 1 < len(s) and s[i + 1] == '-':
                    nl = s.find("\n", i)
                    if nl == -1:
                        break
                    i = nl
                    continue
                if ch == '#':
                    nl = s.find("\n", i)
                    if nl == -1:
                        break
                    i = nl
                    continue
            out.append(ch); i += 1
        return "".join(out)

    sql = strip_trailing_comment(sql)
    return sql.strip().rstrip(";").strip()


# -------------------------------
# SQL VALIDATION — returns (ok, reason)
# -------------------------------
_FORBIDDEN_KEYWORDS = {
    r'\bDELETE\b':   'DELETE',
    r'\bUPDATE\b':   'UPDATE',
    r'\bINSERT\b':   'INSERT',
    r'\bDROP\b':     'DROP',
    r'\bALTER\b':    'ALTER',
    r'\bTRUNCATE\b': 'TRUNCATE',
    r'\bCREATE\b':   'CREATE',
    r'\bREPLACE\b':  'REPLACE',
    r'\bGRANT\b':    'GRANT',
    r'\bREVOKE\b':   'REVOKE',
    r'\bINTO\s+OUTFILE\b':  'INTO OUTFILE',
    r'\bINTO\s+DUMPFILE\b': 'INTO DUMPFILE',
    r'\bLOAD_FILE\b': 'LOAD_FILE',
    r'\bSLEEP\b':    'SLEEP',
    r'\bBENCHMARK\b': 'BENCHMARK',
}


def validate_sql(sql):
    """
    Returns (ok: bool, reason: str).
    reason is a precise, debuggable message when ok=False.
    """
    if not sql or not sql.strip():
        return False, "empty SQL (LLM returned nothing or only whitespace/code fence)"

    sql_upper = sql.upper().strip()

    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        first = sql.strip().split()[0] if sql.strip() else "(nothing)"
        return False, (
            f"statement must start with SELECT or WITH, "
            f"but starts with {first!r}"
        )

    body = sql.rstrip(";")
    if ";" in body:
        idx = body.index(";")
        return False, (
            f"multiple statements detected — extra ';' at position {idx}: "
            f"{body[max(0, idx - 40):idx + 40]!r}"
        )

    for token, label in (("--", "line comment --"),
                         ("/*", "block comment /*"),
                         ("#",  "hash comment #")):
        if token in sql:
            idx = sql.index(token)
            return False, (
                f"SQL comments not allowed — found {label} at position {idx}: "
                f"{sql[max(0, idx - 40):idx + 40]!r}"
            )

    for pattern, name in _FORBIDDEN_KEYWORDS.items():
        m = re.search(pattern, sql_upper)
        if m:
            return False, (
                f"forbidden keyword {name!r} found at position {m.start()}: "
                f"{sql[max(0, m.start() - 40):m.start() + 40]!r}"
            )

    return True, ""


def is_safe_query(sql):
    """Back-compat wrapper."""
    ok, _ = validate_sql(sql)
    return ok


def check_tables(sql, allowed):
    """
    Returns (ok: bool, blocked_table_or_None).
    Skips the check (ok=True) when there is no whitelist.
    """
    if not allowed:
        return True, None

    ctes = {
        m.lower()
        for m in re.findall(r"\b(\w+)\s+AS\s*\(", sql, flags=re.IGNORECASE)
    }

    refs = re.findall(r"\b(?:FROM|JOIN)\s+`?(\w+)`?", sql, flags=re.IGNORECASE)
    for ref in refs:
        r = ref.lower()
        if r not in allowed and r not in ctes:
            return False, ref

    return True, None


def uses_only_allowed_tables(sql, allowed):
    """Back-compat wrapper."""
    ok, _ = check_tables(sql, allowed)
    return ok


def enforce_limit(sql, limit=MAX_ROWS):
    """
    Apply LIMIT only to detail queries.
    Skip LIMIT for single-row aggregates (SUM/COUNT/AVG/MIN/MAX without GROUP BY).
    """
    if re.search(r"\bLIMIT\s+\d+", sql, flags=re.IGNORECASE):
        return sql

    sql_upper = sql.upper()
    aggregate_fns = r"\b(SUM|COUNT|AVG|MIN|MAX|GROUP_CONCAT)\s*\("
    has_aggregate = re.search(aggregate_fns, sql_upper)
    has_group_by = re.search(r"\bGROUP\s+BY\b", sql_upper)

    if has_aggregate and not has_group_by:
        return sql  # single-row aggregate — no LIMIT needed

    return f"{sql} LIMIT {limit}"


def query_database(sql):
    from app import db

    try:
        result = db.session.execute(text(sql))
        if result.returns_rows:
            columns = result.keys()
            return [dict(zip(columns, row)) for row in result.fetchall()]
        return []
    except Exception:
        db.session.rollback()
        raise


# -------------------------------
# Fallback formatter
# -------------------------------
def _num(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fallback_format(rows):
    lines = []

    for i, row in enumerate(rows[:10], 1):
        if not isinstance(row, dict):
            lines.append(f"{i}. {row}")
            continue

        if "item_name" in row:
            name = row.get("item_name")
            qty = _num(row.get("total_quantity", row.get("total_quantity_sold", 0)))
            revenue = _num(row.get("total_revenue", 0))
            lines.append(f"{i}. {name} - {qty:,.0f} units | KSh {revenue:,.0f}")

        elif "shopname" in row:
            lines.append(
                f"{i}. {row.get('shopname')} - {row.get('location')} ({row.get('shopstatus')})"
            )

        else:
            lines.append(f"{i}. {row}")

    return "Here are your results:\n\n" + "\n".join(lines)


# -------------------------------
# Fallback visualization builder
# -------------------------------
def build_fallback_viz(rows):
    """Build a basic table viz when the LLM viz step fails."""
    if not rows:
        return {
            "type": "text",
            "title": "No results",
            "body": "No records matched your question.",
        }

    # Use the first row's keys as columns
    keys = list(rows[0].keys())
    columns = [
        {"key": k, "label": k.replace("_", " ").title(), "type": "text"}
        for k in keys
    ]

    # Strip internal columns from fallback output too
    INTERNAL = {"user_id", "promocode", "note", "timestamp", "delivery"}
    display_keys = [k for k in keys if k not in INTERNAL]
    if display_keys:
        columns = [
            {"key": k, "label": k.replace("_", " ").title(), "type": "text"}
            for k in display_keys
        ]

    return {
        "type": "table",
        "title": "Results",
        "columns": columns,
        "rows": [
            {k: (str(v) if not isinstance(v, (int, float, str, type(None))) else v)
             for k, v in row.items() if k in {c["key"] for c in columns}}
            for row in rows[:50]
        ],
    }


# -------------------------------
# LLM helpers
# -------------------------------
def extract_message_text(msg):
    """
    Return the first non-empty text field from a chat message.
    Some reasoning-model gateways populate reasoning_content, others
    return the final text in content, some put it in the raw dict.
    """
    for attr in ("content", "reasoning_content", "text"):
        val = getattr(msg, attr, None)
        if val and str(val).strip():
            return str(val)
    try:
        d = msg.model_dump()
        for k in ("content", "reasoning_content", "text"):
            v = d.get(k)
            if v and str(v).strip():
                return str(v)
    except Exception:
        pass
    return ""


def log_llm_response(tag, response, message):
    """Print everything we might need to debug an empty/odd response."""
    if not DEBUG_MODE:
        return
    try:
        choice = response.choices[0]
        print("=" * 60)
        print(f"[AskAI] {tag} finish_reason = {choice.finish_reason!r}")
        print(f"[AskAI] {tag} model         = {getattr(response, 'model', None)!r}")
        print(f"[AskAI] {tag} usage         = {getattr(response, 'usage', None)}")
        print(f"[AskAI] msg.content            = {getattr(message, 'content', None)!r}")
        print(f"[AskAI] msg.reasoning_content  = {getattr(message, 'reasoning_content', None)!r}")
        print(f"[AskAI] msg.refusal            = {getattr(message, 'refusal', None)!r}")
        try:
            dump = message.model_dump()
            for k in ("content", "reasoning_content"):
                dump.pop(k, None)
            print(f"[AskAI] msg.other fields       = {dump}")
        except Exception as e:
            print(f"[AskAI] model_dump failed      = {e}")
        print("=" * 60)
    except Exception as e:
        print(f"[AskAI] log_llm_response failed: {e}")


def _build_kwargs(extra_reasoning_effort=""):
    """Assemble completion kwargs, adding reasoning_effort only when set."""
    kwargs = {}
    if extra_reasoning_effort:
        # Older openai SDKs need this nested inside extra_body.
        kwargs["extra_body"] = {"reasoning_effort": extra_reasoning_effort}
    return kwargs


def generate_sql(client, system_prompt_with_schema, user_prompt):
    """
    Call the LLM to generate SQL with one retry on empty output.
    Returns (raw_text, choice, response).
    """
    last_choice = last_resp = None
    for attempt, temp in enumerate((0.0, 0.2)):
        kwargs = _build_kwargs(REASONING_EFFORT_SQL)
        resp = client.chat.completions.create(
            model=MODEL_NAME_SQL,
            messages=[
                {"role": "system", "content": system_prompt_with_schema},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=SQL_MAX_TOKENS,
            temperature=temp,
            **kwargs,
        )
        choice = resp.choices[0]
        msg = choice.message
        log_llm_response(f"SQL attempt {attempt}", resp, msg)

        text = extract_message_text(msg)
        if text.strip():
            return text, choice, resp

        if DEBUG_MODE:
            print(
                f"[AskAI] SQL attempt {attempt} returned empty "
                f"(finish_reason={choice.finish_reason!r}, temp={temp})"
            )
        last_choice, last_resp = choice, resp

    return "", last_choice, last_resp


def generate_viz(client, question, sql, rows):
    """
    Call the LLM to produce a structured viz payload.
    Returns (answer_text, viz_dict).
    Falls back to a plain table if the LLM step fails or produces bad JSON.
    """
    try:
        rows_for_viz = rows[:EXPLANATION_ROW_LIMIT]
        result_json = json.dumps(rows_for_viz, default=str)

        viz_prompt = f"""
User question: {question}

SQL executed:
{sql}

Result rows ({len(rows_for_viz)} of {len(rows)}):
{result_json}
"""

        viz_kwargs = {}
        # Try to force strict JSON where supported
        try:
            viz_resp = client.chat.completions.create(
                model=MODEL_NAME_EXPLAIN,
                messages=[
                    {"role": "system", "content": VIZ_FORMAT_PROMPT},
                    {"role": "user", "content": viz_prompt},
                ],
                max_completion_tokens=EXPLAIN_MAX_TOKENS,
                response_format={"type": "json_object"},
                **viz_kwargs,
            )
        except Exception as format_err:
            # Some gateways don't support response_format — retry without it.
            if DEBUG_MODE:
                print(f"[AskAI] response_format unsupported, retrying without: {format_err}")
            viz_resp = client.chat.completions.create(
                model=MODEL_NAME_EXPLAIN,
                messages=[
                    {"role": "system", "content": VIZ_FORMAT_PROMPT},
                    {"role": "user", "content": viz_prompt},
                ],
                max_completion_tokens=EXPLAIN_MAX_TOKENS,
                **viz_kwargs,
            )

        viz_msg = viz_resp.choices[0].message
        log_llm_response("VIZ", viz_resp, viz_msg)

        viz_text = extract_message_text(viz_msg).strip()
        viz_text = clean_sql(viz_text)  # reuse fence stripper

        if not viz_text:
            raise ValueError("Empty viz response from LLM")

        viz_payload = json.loads(viz_text)

        answer_text = viz_payload.get("answer") or "Here are your results."
        viz = viz_payload.get("viz")

        if not viz or not isinstance(viz, dict) or "type" not in viz:
            raise ValueError(f"Malformed viz payload: {viz_payload!r}")

        return answer_text, viz

    except Exception as e:
        print("VIZ FALLBACK USED:", str(e))
        answer_text = fallback_format(rows)
        viz = build_fallback_viz(rows)
        return answer_text, viz


# -------------------------------
# MAIN ENDPOINT
# -------------------------------
class AskAI(Resource):
    def post(self):
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            return {"error": "No question provided"}, 400

        try:
            # ------------------------
            # STEP -2: Configuration questions
            # ------------------------
            config_type = detect_config_question(question)
            if config_type:
                return {
                    "success": True,
                    "type": "configuration",
                    "question": question,
                    "answer": get_config_answer(config_type),
                    "sql_executed": False,
                }, 200

            # ------------------------
            # STEP -1: Greetings
            # ------------------------
            if is_simple_question(question):
                return {
                    "success": True,
                    "answer": "Hello 👋 I can help you analyze your business data. Ask me about sales, shops, inventory, or reports."
                }, 200

            # ------------------------
            # STEP 0: Schema + prompts
            # ------------------------
            schema_text = get_database_schema()
            if not schema_text:
                return {"answer": "Could not load database schema."}, 500

            allowed_tables = get_allowed_tables()
            schema_source = _schema_source()
            allowed_count = len(allowed_tables) if allowed_tables else 0

            if not hasattr(current_app, "llm_client"):
                return {"answer": "AI model not configured."}, 500

            client = current_app.llm_client
            system_prompt = get_system_prompt()
            recon_rules = get_reconciliation_rules()

            # Narrow the schema to what the question likely needs.
            scoped_schema = pick_relevant_schema(schema_text, question)

            if DEBUG_MODE:
                print("=" * 60)
                print(f"[AskAI] SCHEMA SOURCE : {schema_source}")
                print(f"[AskAI] SCHEMA FULL   : {len(schema_text)} chars")
                print(f"[AskAI] SCHEMA SCOPED : {len(scoped_schema)} chars")
                print(f"[AskAI] ALLOWED TABLES: {allowed_count}")
                if allowed_tables:
                    print(f"[AskAI] TABLE LIST    : {sorted(allowed_tables)}")
                else:
                    print("[AskAI] WARNING: whitelist is EMPTY — table check will be SKIPPED")
                print("=" * 60)

            # ------------------------
            # STEP 1: SQL generation
            # ------------------------
            rules_block = (
                f"\nBusiness / reconciliation rules:\n{recon_rules}\n"
                if recon_rules else ""
            )

            # Put the schema in the system message so gateways can cache it.
            system_prompt_with_schema = (
                f"{system_prompt}\n\n"
                f"# DATABASE SCHEMA\n"
                f"{scoped_schema}\n"
            )

            user_prompt = (
                f"Convert the following question to a single MySQL SELECT statement.\n"
                f"{rules_block}"
                f"\nQuestion:\n{question}\n\n"
                f"Return ONLY the SQL — no prose, no code fences, no comments."
            )

            if DEBUG_MODE:
                print("=" * 60)
                print(f"[AskAI] SQL MODEL      : {MODEL_NAME_SQL}")
                print(f"[AskAI] SYSTEM LEN     : {len(system_prompt_with_schema)} chars")
                print(f"[AskAI] USER PROMPT    : {user_prompt[:600]!r}")
                print("=" * 60)

            raw_sql_text, sql_choice, sql_response = generate_sql(
                client, system_prompt_with_schema, user_prompt
            )

            sql = clean_sql(raw_sql_text).rstrip(";").strip()

            # --- Precise validation feedback ---
            ok, reason = validate_sql(sql)
            if not ok:
                if DEBUG_MODE:
                    print("=" * 60)
                    print("[AskAI] SQL REJECTED")
                    print(f"[AskAI] REASON : {reason}")
                    print(f"[AskAI] RAW SQL: {sql!r}")
                    print("=" * 60)
                return {
                    "success": False,
                    "type": "sql_rejected",
                    "question": question,
                    "reason": reason,
                    "raw_sql": sql if DEBUG_MODE else None,
                    "llm_finish_reason": (
                        sql_choice.finish_reason if sql_choice else None
                    ),
                    "llm_model": (
                        getattr(sql_response, "model", None) if sql_response else None
                    ),
                }, 200

            # --- Precise table-whitelist feedback ---
            tables_ok, blocked_table = check_tables(sql, allowed_tables)
            if not tables_ok:
                if DEBUG_MODE:
                    print("=" * 60)
                    print("[AskAI] SQL REJECTED — table not in whitelist")
                    print(f"[AskAI] BLOCKED TABLE: {blocked_table}")
                    print(f"[AskAI] RAW SQL      : {sql!r}")
                    print("=" * 60)
                return {
                    "success": False,
                    "type": "table_not_allowed",
                    "question": question,
                    "reason": (
                        f"query references table {blocked_table!r} which is not "
                        f"in the {allowed_count}-table schema whitelist"
                    ),
                    "blocked_table": blocked_table,
                    "raw_sql": sql if DEBUG_MODE else None,
                }, 200

            sql = enforce_limit(sql)

            # ------------------------
            # STEP 2: Execute SQL
            # ------------------------
            try:
                raw_rows = query_database(sql)
            except Exception as db_err:
                if DEBUG_MODE:
                    print("=" * 60)
                    print("[AskAI] DB EXECUTION ERROR")
                    print(f"[AskAI] SQL   : {sql!r}")
                    print(f"[AskAI] ERROR : {db_err}")
                    print("=" * 60)
                return {
                    "success": False,
                    "type": "sql_execution_error",
                    "question": question,
                    "reason": f"database rejected the query: {db_err}",
                    "raw_sql": sql if DEBUG_MODE else None,
                }, 200

            # ------------------------
            # STEP 3: Build structured UI payload
            # ------------------------
            if not raw_rows:
                return {
                    "success": True,
                    "question": question,
                    "answer": "No records found in the system.",
                    "sql": sql if DEBUG_MODE else None,
                    "viz": {
                        "type": "text",
                        "title": "No results",
                        "body": "No records matched your question.",
                    },
                }, 200

            answer_text, viz = generate_viz(client, question, sql, raw_rows)

            # ------------------------
            # FINAL RESPONSE
            # ------------------------
            response = {
                "success": True,
                "question": question,
                "answer": answer_text,
                "viz": viz,
            }

            if DEBUG_MODE:
                response["sql"] = sql
                response["raw_result"] = str(raw_rows)
                response["schema_source"] = schema_source
                response["schema_full_length"] = len(schema_text)
                response["schema_scoped_length"] = len(scoped_schema)
                response["schema_preview"] = scoped_schema[:500]
                response["allowed_tables_count"] = allowed_count
                response["allowed_tables"] = (
                    sorted(allowed_tables) if allowed_tables else []
                )
                response["rows_returned"] = len(raw_rows)
                response["rows_sent_to_llm"] = len(raw_rows[:EXPLANATION_ROW_LIMIT])
                response["models"] = {
                    "sql": MODEL_NAME_SQL,
                    "explain": MODEL_NAME_EXPLAIN,
                }

            return response, 200

        except Exception as e:
            traceback.print_exc()
            return {
                "success": False,
                "type": "unexpected_error",
                "answer": f"Unexpected error: {str(e)}",
                "traceback": traceback.format_exc() if DEBUG_MODE else None,
            }, 500


# -------------------------------
# Refresh Schema
# -------------------------------
class RefreshSchema(Resource):
    def post(self):
        try:
            from schema_generator import write_schema_file
            write_schema_file()
            clear_file_cache()

            return {"message": "✅ Schema refreshed successfully"}, 200

        except Exception as e:
            return {
                "error": "Failed to refresh schema",
                "details": str(e)
            }, 500


# -------------------------------
# Reload prompts/schema without restart
# -------------------------------
class ReloadAIConfig(Resource):
    def post(self):
        clear_file_cache()
        return {
            "message": "AI config reloaded",
            "files": {
                "schema_md": SCHEMA_MD_PATH.exists(),
                "schema_json": SCHEMA_JSON_PATH.exists(),
                "system_prompt": SYSTEM_PROMPT_PATH.exists(),
                "reconciliation_rules": RECON_RULES_PATH.exists(),
            }
        }, 200