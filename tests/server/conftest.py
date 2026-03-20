"""
Test DB setup for server tests.

Uses an in-memory SQLite database. Tables are created and seeded before each
test and dropped after, ensuring full isolation between tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import main
from main import app, _sync_problems, _register_ip_counts

TEST_DATABASE_URL = "sqlite:///:memory:"
# StaticPool makes all sessions share one connection so in-memory data is visible everywhere
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=test_engine)
    # Reset mtime cache so _sync_problems always loads into the fresh DB
    main._problems_file_mtime = 0.0
    db = TestSessionLocal()
    try:
        _sync_problems(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=test_engine)
    _register_ip_counts.clear()


@pytest.fixture
def db_session():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()
