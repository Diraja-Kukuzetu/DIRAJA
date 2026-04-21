import re
import traceback
from flask_restful import Resource
from flask import request, current_app
from sqlalchemy import text

DEBUG_MODE = True

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
# Utility Functions
# -------------------------------

def clean_sql(sql):
    sql = re.sub(r"```sql\n?", "", sql)
    sql = re.sub(r"```\n?", "", sql)
    sql = re.sub(r"^sql\n?", "", sql, flags=re.IGNORECASE)
    return sql.strip()


def is_safe_query(sql):
    sql_upper = sql.upper().strip()

    if not sql_upper.startswith("SELECT"):
        return False

    dangerous_keywords = [
        r'\bDELETE\b', r'\bUPDATE\b', r'\bINSERT\b',
        r'\bDROP\b', r'\bALTER\b', r'\bTRUNCATE\b',
        r'\bCREATE\b', r'\bREPLACE\b', r'\bGRANT\b',
        r'\bREVOKE\b'
    ]

    for keyword in dangerous_keywords:
        if re.search(keyword, sql_upper):
            return False

    return True


def get_database_schema():
    try:
        from app import db

        schema_text = []

        for table_name, table in db.Model.metadata.tables.items():
            schema_text.append(f"\nTable: {table_name}")

            for column in table.columns:
                line = f"  - {column.name} ({str(column.type)})"
                if column.primary_key:
                    line += " PRIMARY KEY"
                schema_text.append(line)

            for fk in table.foreign_keys:
                schema_text.append(
                    f"  FK: {fk.parent.name} -> {fk.column.table.name}.{fk.column.name}"
                )

        return "\n".join(schema_text)

    except Exception as e:
        print("Schema error:", str(e))
        return ""


def query_database(sql):
    from app import db

    try:
        result = db.session.execute(text(sql))
        db.session.commit()

        if result.returns_rows:
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            if not rows:
                return "No results found."

            return "\n".join([str(r) for r in rows])
        else:
            return "No results."

    except Exception as e:
        db.session.rollback()
        raise Exception(str(e))


# -------------------------------
# API Resource
# -------------------------------

import re
import traceback
import json
import ast
from flask_restful import Resource
from flask import request, current_app
from sqlalchemy import text

DEBUG_MODE = True


# -------------------------------
# Simple Question Detection
# -------------------------------
def is_simple_question(question):
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
# Utility Functions
# -------------------------------
def clean_sql(sql):
    sql = re.sub(r"```sql\n?", "", sql)
    sql = re.sub(r"```\n?", "", sql)
    sql = re.sub(r"^sql\n?", "", sql, flags=re.IGNORECASE)
    return sql.strip()


def is_safe_query(sql):
    sql_upper = sql.upper().strip()

    if not sql_upper.startswith("SELECT"):
        return False

    dangerous_keywords = [
        r'\bDELETE\b', r'\bUPDATE\b', r'\bINSERT\b',
        r'\bDROP\b', r'\bALTER\b', r'\bTRUNCATE\b',
        r'\bCREATE\b', r'\bREPLACE\b', r'\bGRANT\b',
        r'\bREVOKE\b'
    ]

    for keyword in dangerous_keywords:
        if re.search(keyword, sql_upper):
            return False

    return True


def query_database(sql):
    from app import db

    result = db.session.execute(text(sql))
    db.session.commit()

    if result.returns_rows:
        columns = result.keys()
        rows = [dict(zip(columns, row)) for row in result.fetchall()]

        if not rows:
            return []

        return rows

    return []


# -------------------------------
# MAIN ENDPOINT
# -------------------------------
class AskAI(Resource):
    def post(self):
        data = request.get_json()
        question = data.get("question", "").strip()

        if not question:
            return {"error": "No question provided"}, 400

        try:
            # ------------------------
            # STEP -1: Greetings
            # ------------------------
            if is_simple_question(question):
                return {
                    "success": True,
                    "answer": "Hello 👋 I can help you analyze your business data. Ask me about sales, shops, inventory, or reports."
                }, 200

            # ------------------------
            # STEP 0: Schema
            # ------------------------
            schema_text = get_database_schema()

            if not schema_text:
                return {"answer": "Could not load database schema."}, 500

            if not hasattr(current_app, 'llm_client'):
                return {"answer": "AI model not configured."}, 500

            client = current_app.llm_client
            system_prompt = current_app.llm_system_prompt

            # ------------------------
            # STEP 1: SQL generation
            # ------------------------
            sql_prompt = f"""
Convert question to MySQL SELECT only.

Schema:
{schema_text}

Question:
{question}

Return only SQL:
"""

            sql_response = client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": sql_prompt}
                ],
                max_completion_tokens=800
            )

            sql = clean_sql(sql_response.choices[0].message.content).rstrip(";")

            if not sql or not is_safe_query(sql):
                return {"answer": "Invalid query generated."}, 200

            # ------------------------
            # STEP 2: Execute SQL
            # ------------------------
            raw_rows = query_database(sql)

            # ------------------------
            # STEP 3: FORCE HUMAN FORMAT
            # ------------------------
            if not raw_rows:
                answer_text = "No records found in the system."
            else:
                try:
                    result_json = json.dumps(raw_rows, default=str)

                    explanation_prompt = f"""
Convert this database result into human-readable business English.

User Question: {question}

Data:
{result_json}

Rules:
- NEVER say "no data available" if data exists
- Always summarize ALL results
- If list → rank items
- Use KSh for currency
- Be clear and structured
"""

                    answer_response = client.chat.completions.create(
                        model="gpt-5-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": "You convert structured data into clean business insights."
                            },
                            {"role": "user", "content": explanation_prompt}
                        ],
                        max_completion_tokens=800
                    )

                    answer_text = answer_response.choices[0].message.content.strip()

                    if not answer_text:
                        raise Exception("Empty response")

                except Exception as e:
                    print("FALLBACK USED:", str(e))

                    # ------------------------
                    # FALLBACK FORMATTER
                    # ------------------------
                    lines = []

                    for i, row in enumerate(raw_rows[:10], 1):

                        if isinstance(row, dict):

                            if "item_name" in row:
                                name = row.get("item_name")
                                qty = row.get("total_quantity", row.get("total_quantity_sold", 0))
                                revenue = row.get("total_revenue", 0)

                                lines.append(
                                    f"{i}. {name} - {qty:,.0f} units | KSh {revenue:,.0f}"
                                )

                            elif "shopname" in row:
                                lines.append(
                                    f"{i}. {row.get('shopname')} - {row.get('location')} ({row.get('shopstatus')})"
                                )

                            else:
                                lines.append(f"{i}. {row}")

                    answer_text = "Here are your results:\n\n" + "\n".join(lines)

            # ------------------------
            # FINAL RESPONSE
            # ------------------------
            return {
                "success": True,
                "question": question,
                "sql": sql,
                "raw_result": str(raw_rows),
                "answer": answer_text
            }, 200

        except Exception as e:
            traceback.print_exc()
            return {
                "success": False,
                "answer": f"Unexpected error: {str(e)}"
            }, 500


# -------------------------------
# Refresh Schema
# -------------------------------
class RefreshSchema(Resource):
    def post(self):
        try:
            from schema_generator import write_schema_file
            write_schema_file()

            return {"message": "✅ Schema refreshed successfully"}, 200

        except Exception as e:
            return {
                "error": "Failed to refresh schema",
                "details": str(e)
            }, 500