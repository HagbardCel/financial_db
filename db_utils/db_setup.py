#!/usr/bin/env python3 
import os
import psycopg2
import sys
from pathlib import Path
from db_utils.config import get_database_config

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

def main():
    # Check for --reset flag
    reset_flag = '--reset' in sys.argv

    # Retrieve database connection details
    try:
        config = get_database_config()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Connect to your database
    conn = psycopg2.connect(**config)

    # Open a cursor to perform database operations
    cur = conn.cursor()

    # Reset the database if the flag is set
    if reset_flag:
        reset_database(cur)

    # Resolve SQL script path relative to this script
    current_dir = Path(__file__).parent
    sql_path = current_dir / 'db_setup.sql'

    # Read the SQL file
    with open(sql_path, 'r') as file:
        sql_script = file.read()

    # Execute the SQL script
    cur.execute(sql_script)

    # Commit the changes
    conn.commit()

    # Close communication with the database
    cur.close()
    conn.close()
    print("Database setup completed successfully.")

if __name__ == "__main__":
    main()