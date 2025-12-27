import pytest
import psycopg2
from db_utils.database import DatabaseConnection, init_connection_pool, _CONNECTION_POOL
from db_utils.config import get_database_config

def test_connection_pooling():
    """Test that connections are reused from the pool."""
    config = get_database_config()
    
    # Initialize pool
    init_connection_pool(config, minconn=1, maxconn=2)
    
    with DatabaseConnection(config) as db1:
        conn1 = db1.conn
        cursor1 = db1.cursor
        assert conn1 is not None
        assert cursor1 is not None
        
        # Connection ID in Python
        id1 = id(conn1)
        
    with DatabaseConnection(config) as db2:
        conn2 = db2.conn
        id2 = id(conn2)
        
    # Since we only have 1 minconn and we closed db1 (returned to pool), 
    # db2 should get the same connection object.
    assert id1 == id2
    
def test_transaction_rollback():
    """Test that errors cause a rollback."""
    config = get_database_config()
    
    with pytest.raises(Exception):
        with DatabaseConnection(config) as db:
            db.cursor.execute("SELECT 1/0") # This will fail
            
    # The pool should still be functional
    with DatabaseConnection(config) as db:
        db.cursor.execute("SELECT 1")
        result = db.cursor.fetchone()
        assert result[0] == 1
