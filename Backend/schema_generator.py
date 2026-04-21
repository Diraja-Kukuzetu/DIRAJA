from app import db


def generate_schema_from_models():
    output = "Database Schema:\n\n"

    for table in db.metadata.tables.values():
        output += f"Table: {table.name}\nColumns:\n"

        for column in table.columns:
            col_type = str(column.type)
            output += f"- {column.name} ({col_type})\n"

        output += "\n"

    return output


def generate_relationships():
    output = "Relationships:\n"

    for table in db.metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                output += f"- {table.name}.{column.name} = {fk.column.table.name}.{fk.column.name}\n"

    return output


def write_schema_file():
    schema_text = generate_schema_from_models()
    relationships = generate_relationships()

    # 🔥 Add business hints (VERY IMPORTANT for Gemini accuracy)
    business_rules = """
Business Rules:
- created_at is used for date filtering
- amount fields usually represent money values
- total_amount represents full transaction totals
- balance represents unpaid amounts

Security Rules:
- ONLY SELECT queries are allowed
- DELETE, UPDATE, INSERT, DROP, ALTER are strictly forbidden
- Do not modify the database
"""

    full_text = f"""
You are a MySQL expert.

{schema_text}

{relationships}

{business_rules}

Rules:
- Use only the tables provided
- Use relationships when joining tables
- Do not guess column names
- Return only valid MySQL SQL queries
"""

    with open("schema.txt", "w") as f:
        f.write(full_text.strip())

    print("✅ schema.txt generated successfully!")