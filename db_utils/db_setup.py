#! env python3 
import os
import psycopg2
import sys

def reset_database(cursor):
    """Delete all tables in the database and verify that no tables remain."""
    cursor.execute("""
        DO $$ DECLARE
        r RECORD;
        BEGIN
            FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP;
        END $$;
    """)

    # Verify that no tables remain
    cursor.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'")
    table_count = cursor.fetchone()[0]
    if table_count > 0:
        raise RuntimeError("Error: There are still tables in the database after reset.")

# Retrieve database connection details from environment variables
db_user = os.getenv('POSTGRES_USER')
db_password = os.getenv('POSTGRES_PASSWORD')
db_name = os.getenv('POSTGRES_DB')
db_host = os.getenv('POSTGRES_HOST', 'localhost')  # Default to 'localhost' if not set
db_port = os.getenv('POSTGRES_PORT', '5432')  # Default to '5432' if not set

# Check for --reset flag
reset_flag = '--reset' in sys.argv

# Connect to your database
conn = psycopg2.connect(
    dbname=db_name,
    user=db_user,
    password=db_password,
    host=db_host,
    port=db_port
)

# Open a cursor to perform database operations
cur = conn.cursor()

# Reset the database if the flag is set
if reset_flag:
    reset_database(cur)

# Read the SQL file
with open('/workspaces/financial_db/db_utils/db_setup.sql', 'r') as file:
    sql_script = file.read()

# Execute the SQL script
cur.execute(sql_script)

# Commit the changes
conn.commit()

# Close communication with the database
cur.close()
conn.close()