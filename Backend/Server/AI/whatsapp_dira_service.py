import json
import traceback

from flask import current_app

from Server.Views.DirajaAI import (
    MODEL_NAME_SQL,
    MODEL_NAME_EXPLAIN,
    get_database_schema,
    get_system_prompt,
    get_reconciliation_rules,
    get_allowed_tables,
    clean_sql,
    is_safe_query,
    uses_only_allowed_tables,
    enforce_limit,
    query_database,
    fallback_format,
)


def ask_dira_question(question, conversation_history=None, user_context=None):
    """
    WhatsApp entry point for the existing Dira AI query pipeline.

    Returns plain text suitable for WhatsApp.
    """

    question = (question or "").strip()

    if not question:
        return "Please send a question."

    if not hasattr(current_app, "llm_client"):
        return "Dira AI is currently unavailable. Please try again later."

    try:
        schema_text = get_database_schema()

        if not schema_text:
            return "I could not load the business data schema."

        client = current_app.llm_client
        system_prompt = get_system_prompt()
        recon_rules = get_reconciliation_rules()

        rules_block = (
            f"\nBusiness and reconciliation rules:\n{recon_rules}\n"
            if recon_rules else ""
        )

        # Keep the history short so the WhatsApp conversation does not
        # create excessively large prompts.
        history = conversation_history or []
        history_text = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}"
            for item in history[-8:]
            if isinstance(item, dict)
        )

        context_text = json.dumps(user_context or {}, default=str)

        sql_prompt = f"""
You are generating a MySQL SELECT query for Diraja.

Database schema:
{schema_text}

Business and reconciliation rules:
{rules_block}

Authenticated WhatsApp user context:
{context_text}

Conversation so far:
{history_text}

Current question:
{question}

Return only one read-only MySQL SELECT query.
Do not generate INSERT, UPDATE, DELETE, or schema-changing SQL.
"""

        sql_response = client.chat.completions.create(
            model=MODEL_NAME_SQL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": sql_prompt}
            ],
            max_completion_tokens=800
        )

        sql = clean_sql(
            sql_response.choices[0].message.content or ""
        ).rstrip(";").strip()

        if not sql or not is_safe_query(sql):
            return "I could not generate a safe query for that question."

        if not uses_only_allowed_tables(sql, get_allowed_tables()):
            return "That question refers to data outside the allowed schema."

        sql = enforce_limit(sql)

        rows = query_database(sql)

        if not rows:
            answer = "No records found in the system."
        else:
            try:
                explanation_prompt = f"""
Explain these Diraja business results in clear, concise language.

Question:
{question}

Results:
{json.dumps(rows, default=str)}

Instructions:
- Use KSh for currency.
- Give the important totals and figures.
- If the result is a list, summarize and rank it where appropriate.
- Keep the response suitable for a WhatsApp message.
- Do not invent figures.
"""

                response = client.chat.completions.create(
                    model=MODEL_NAME_EXPLAIN,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are Dira, a business reporting assistant "
                                "for Diraja. Explain database results accurately."
                            )
                        },
                        {"role": "user", "content": explanation_prompt}
                    ],
                    max_completion_tokens=800
                )

                answer = (
                    response.choices[0].message.content or ""
                ).strip()

                if not answer:
                    answer = fallback_format(rows)

            except Exception:
                traceback.print_exc()
                answer = fallback_format(rows)

        return answer

    except Exception:
        traceback.print_exc()
        return (
            "Sorry, I encountered an error while processing your question. "
            "Please try again."
        )