import pytest
from db_utils.database import DatabaseConnection, close_connection_pool, init_connection_pool
from db_utils.config import get_database_config


@pytest.fixture
def db_config():
    try:
        return get_database_config()
    except ValueError as exc:
        pytest.skip(str(exc))


@pytest.fixture(autouse=True)
def reset_pool():
    close_connection_pool()
    yield
    close_connection_pool()


def test_connection_pooling(db_config):
    """Test that connections are reused from the pool."""
    # Initialize pool
    init_connection_pool(db_config, minconn=1, maxconn=2)

    with DatabaseConnection(db_config) as db1:
        conn1 = db1.conn
        cursor1 = db1.cursor
        assert conn1 is not None
        assert cursor1 is not None

        # Connection ID in Python
        id1 = id(conn1)

    with DatabaseConnection(db_config) as db2:
        conn2 = db2.conn
        id2 = id(conn2)

    # Since we only have 1 minconn and we closed db1 (returned to pool),
    # db2 should get the same connection object.
    assert id1 == id2


def test_transaction_rollback(db_config):
    """Test that errors cause a rollback."""
    with pytest.raises(Exception):
        with DatabaseConnection(db_config) as db:
            db.cursor.execute("SELECT 1/0") # This will fail

    # The pool should still be functional
    with DatabaseConnection(db_config) as db:
        db.cursor.execute("SELECT 1")
        result = db.cursor.fetchone()
        assert result[0] == 1


def test_close_connection_pool_allows_clean_reinit(db_config):
    init_connection_pool(db_config, minconn=1, maxconn=2)
    with DatabaseConnection(db_config) as db:
        db.cursor.execute("SELECT 1")
        assert db.cursor.fetchone()[0] == 1

    close_connection_pool()

    init_connection_pool(db_config, minconn=1, maxconn=2)
    with DatabaseConnection(db_config) as db:
        db.cursor.execute("SELECT 1")
        assert db.cursor.fetchone()[0] == 1
