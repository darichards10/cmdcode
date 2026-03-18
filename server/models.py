from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.types import JSON
from database import Base


class DBUser(Base):
    __tablename__ = "users"

    username = Column(String(20), primary_key=True)
    email = Column(String, nullable=False)
    public_key_pem = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)  # ISO-8601 string


class DBChallenge(Base):
    __tablename__ = "challenges"

    challenge_id = Column(String(36), primary_key=True)  # UUID
    username = Column(String(20), ForeignKey("users.username"), nullable=False)
    nonce = Column(String(64), nullable=False)  # 32 bytes hex-encoded
    expires_at = Column(String, nullable=False)  # ISO-8601 string


class DBSession(Base):
    __tablename__ = "sessions"

    token = Column(String(64), primary_key=True)
    username = Column(String(20), ForeignKey("users.username"), nullable=False)
    expires_at = Column(String, nullable=False)  # ISO-8601 string


class DBProblem(Base):
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    difficulty = Column(String, nullable=False)
    starter_code = Column(JSON, nullable=False)  # dict: lang -> code
    test_cases = Column(JSON, nullable=False)    # list of {input, output, hidden}


class DBSubmission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    username = Column(String(20), ForeignKey("users.username"), nullable=False)
    filename = Column(String, nullable=False)
    code = Column(Text, nullable=False)
    language = Column(String, nullable=False)
    submitted_at = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    passed = Column(Boolean, nullable=False)
    results = Column(JSON)
