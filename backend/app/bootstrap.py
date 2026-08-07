"""One-time startup work: wait for Postgres, create schema, seed the admin user."""

from __future__ import annotations

import logging
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.models import Base, User

logger = logging.getLogger(__name__)


def wait_for_db(attempts: int = 30, delay: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            logger.info("waiting for postgres (%s/%s)...", attempt, attempts)
            time.sleep(delay)
    raise SystemExit("database never became available")


def seed_admin() -> None:
    db = SessionLocal()
    try:
        email = settings.csap_admin_email.lower()
        if db.query(User).filter(User.email == email).first():
            logger.info("admin user already present")
            return
        db.add(
            User(
                email=email,
                full_name="Platform Administrator",
                hashed_password=hash_password(settings.csap_admin_password),
                role="admin",
                must_change_password=True,
            )
        )
        db.commit()
        logger.info("created initial admin user %s", email)
    finally:
        db.close()


def main() -> None:
    configure_logging()
    wait_for_db()
    Base.metadata.create_all(engine)
    seed_admin()
    logger.info("bootstrap complete (CSAP %s)", settings.csap_version)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("bootstrap failed")
        sys.exit(1)
