import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://csap:testpassword@localhost:5432/csap_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "0" * 64)
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "dGVzdC1rZXktZm9yLWNpLW9ubHktMzItYnl0ZXMtbG8=")
os.environ.setdefault("CSAP_ADMIN_PASSWORD", "ci-test-password-123")
