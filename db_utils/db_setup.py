#! env python3 
import os
import psycopg2

# Retrieve database connection details from environment variables
db_user = os.getenv('POSTGRES_USER')
db_password = os.getenv('POSTGRES_PASSWORD')
db_name = os.getenv('POSTGRES_DB')
db_host = os.getenv('POSTGRES_HOST', 'localhost')  # Default to 'localhost' if not set
db_port = os.getenv('POSTGRES_PORT', '5432')  # Default to '5432' if not set

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