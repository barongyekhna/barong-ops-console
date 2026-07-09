"""Idempotent seed: register the P notification agent.

Run once after deploy (like a migration):
    python -m backend.app.modules.notifications.seed
"""

from __future__ import annotations

from ...db.session import SessionLocal
from .agent import P_NOTIFICATIONS_AGENT_ID, ensure_p_notifications_agent


def main() -> None:
    db = SessionLocal()
    try:
        created = ensure_p_notifications_agent(db)
        db.commit()
        if created:
            print(f"registered agent: {P_NOTIFICATIONS_AGENT_ID}")
        else:
            print(f"agent already present: {P_NOTIFICATIONS_AGENT_ID}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
