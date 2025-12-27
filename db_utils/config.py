import os
from typing import Dict

def get_database_config() -> Dict[str, str]:
    """
    Reads database configuration from environment variables.
    Returns a dictionary suitable for psycopg2.connect kwargs.
    
    Raises:
        ValueError: If required environment variables are missing.
    """
    config = {
        'dbname': os.getenv('POSTGRES_DB'),
        'user': os.getenv('POSTGRES_USER'),
        'password': os.getenv('POSTGRES_PASSWORD'),
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432')
    }
    
    required = ['dbname', 'user', 'password']
    missing = [k for k in required if not config[k]]
    if missing:
        raise ValueError(f"Missing required database environment variables: {', '.join(['POSTGRES_' + k.upper() for k in missing])}")
        
    return config
