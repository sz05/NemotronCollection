"""Seed the real challenge Tasks (Tech / Marketing / Content Writing).

Idempotent: a task whose title already exists is left as-is. Also deactivates
the old "Build a FastAPI to-do API" demo task so it drops out of the picker.
Run: PYTHONPATH=. python scripts/seed_task.py
"""

import asyncio

from sqlalchemy import select

from app.db import async_session_factory, init_db
from app.models import Task

# Titles retired from earlier demos -- set inactive so they stop appearing.
_RETIRED_TITLES = ["Build a FastAPI to-do API"]

# proof_types reused per kind of deliverable.
_BUILD_PROOF = ["url", "file", "image"]  # repo link / screenshot / demo
_DOC_PROOF = ["file", "url"]  # deck / doc / link

TASKS = [
    # --- Tech ---
    {
        "title": "2-D multiplayer FPS (Krunker-style)",
        "description": (
            "Build a 2-D multiplayer first person shooting game in Python with "
            "mechanics like Krunker."
        ),
        "difficulty": "hard",
        "base_points": 250,
        "proof_types": _BUILD_PROOF,
        "instructions": "Submit a repo link and a short gameplay clip or screenshots.",
    },
    {
        "title": "Realtime shared whiteboard (Excalidraw-style)",
        "description": (
            "Build a shared whiteboard with low latency like Excalidraw: multiple "
            "users draw, move, and edit shapes on one canvas simultaneously, with "
            "changes appearing in realtime for every connected client."
        ),
        "difficulty": "hard",
        "base_points": 250,
        "proof_types": _BUILD_PROOF,
        "instructions": "Submit a repo/live link showing two clients syncing in realtime.",
    },
    {
        "title": "Daily word-guessing game (Wordle-style)",
        "description": (
            "Build a daily word-guessing game with mechanics like Wordle: a 5x6 grid "
            "where users have six tries to guess a secret word, with tiles smoothly "
            "flipping to green, yellow, or gray based on letter accuracy."
        ),
        "difficulty": "medium",
        "base_points": 150,
        "proof_types": _BUILD_PROOF,
        "instructions": "Submit a live link or screenshots of the tile-flip states.",
    },
    {
        "title": "Scroll-driven storytelling landing page (Apple-style)",
        "description": (
            "Build an interactive storytelling landing page with mechanics like "
            "Apple's product sites: heavily scroll-driven animations where elements "
            "scale, rotate, or fade in precisely tied to the user's scroll position "
            "down the page."
        ),
        "difficulty": "medium",
        "base_points": 150,
        "proof_types": _BUILD_PROOF,
        "instructions": "Submit a live link or a screen recording of the scroll animations.",
    },
    {
        "title": "Seat-booking engine with seat locks (BookMyShow-style)",
        "description": (
            "Build a dynamic seat-booking engine with mechanics like BookMyShow or "
            "Ticketmaster: an interactive SVG theater layout where users can select "
            "contiguous seats, triggering a temporary lock in the database that "
            "expires if they don't complete checkout within a 5-minute countdown timer."
        ),
        "difficulty": "hard",
        "base_points": 250,
        "proof_types": _BUILD_PROOF,
        "instructions": "Submit a repo/live link demonstrating the lock + expiry timer.",
    },
    # --- Marketing ---
    {
        "title": "Rebrand plan for an existing company",
        "description": (
            "Plan a rebrand for an existing company - from brand audit and competitor "
            "positioning through new visual identity, messaging pillars, and a "
            "customer-communication rollout that avoids alienating loyal users."
        ),
        "difficulty": "medium",
        "base_points": 150,
        "proof_types": _DOC_PROOF,
        "instructions": "Submit the rebrand deck/document or a link to it.",
    },
    {
        "title": "Mahindra hackathon sponsorship proposal",
        "description": (
            "Design a proposal convincing Mahindra to sponsor your hackathon."
        ),
        "difficulty": "medium",
        "base_points": 150,
        "proof_types": _DOC_PROOF,
        "instructions": "Submit the proposal document/deck or a link to it.",
    },
    # --- Content Writing ---
    {
        "title": "10 personalized creator cold-outreach DMs",
        "description": (
            "Write a batch of personalized cold-outreach DMs to 10 different creators "
            "for a sponsorship campaign - same core ask, but each one has to reference "
            "something specific and real about that creator's actual content, not a "
            "templated mail-merge feel."
        ),
        "difficulty": "easy",
        "base_points": 100,
        "proof_types": _DOC_PROOF,
        "instructions": "Submit the 10 DMs as a document or link.",
    },
    {
        "title": "Twitter product-launch campaign",
        "description": (
            "Plan and write a Twitter launch campaign for a new product - a countdown "
            "teaser sequence, the launch-day thread itself, and a week of follow-up "
            "amplification content, all in one consistent voice."
        ),
        "difficulty": "medium",
        "base_points": 150,
        "proof_types": _DOC_PROOF,
        "instructions": "Submit the full campaign copy as a document or link.",
    },
]


async def main() -> None:
    await init_db()
    async with async_session_factory() as db:
        # Retire old demo tasks so they leave the picker.
        for title in _RETIRED_TITLES:
            old = (
                await db.execute(select(Task).where(Task.title == title))
            ).scalars().first()
            if old is not None and old.active:
                old.active = False
                db.add(old)
                print(f"retired demo task: {old.id} ({title})")

        seeded, skipped = 0, 0
        for spec in TASKS:
            existing = (
                await db.execute(select(Task).where(Task.title == spec["title"]))
            ).scalars().first()
            if existing is not None:
                skipped += 1
                continue
            db.add(Task(**spec))
            seeded += 1

        await db.commit()
        print(f"seeded {seeded} task(s), skipped {skipped} existing.")


if __name__ == "__main__":
    asyncio.run(main())
