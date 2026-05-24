#!/usr/bin/env python3
"""MiMo Token Vesting - Token vesting schedule calculator and tracker."""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("token-vesting")


@dataclass
class VestingSchedule:
    beneficiary: str
    total_tokens: float
    start_time: int
    cliff_duration: int
    vesting_duration: int
    released: float = 0.0
    category: str = "team"

    @property
    def cliff_end(self) -> int:
        return self.start_time + self.cliff_duration

    @property
    def vesting_end(self) -> int:
        return self.start_time + self.vesting_duration

    def get_vested_amount(self, current_time: int) -> float:
        if current_time < self.cliff_end:
            return 0.0
        if current_time >= self.vesting_end:
            return self.total_tokens
        elapsed = current_time - self.start_time
        return self.total_tokens * elapsed / self.vesting_duration

    def get_releasable(self, current_time: int) -> float:
        return max(0, self.get_vested_amount(current_time) - self.released)

    def get_progress(self, current_time: int) -> Dict:
        vested = self.get_vested_amount(current_time)
        return {
            "beneficiary": self.beneficiary,
            "category": self.category,
            "total": f"{self.total_tokens:,.0f}",
            "vested": f"{vested:,.0f}",
            "released": f"{self.released:,.0f}",
            "releasable": f"{self.get_releasable(current_time):,.0f}",
            "progress": f"{vested / self.total_tokens:.2%}" if self.total_tokens > 0 else "0%",
            "cliff_passed": current_time >= self.cliff_end,
            "fully_vested": current_time >= self.vesting_end,
            "days_remaining": max(0, (self.vesting_end - current_time) // 86400),
        }


class VestingManager:
    def __init__(self, db_path: str = "vesting.db"):
        self.schedules: List[VestingSchedule] = []
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                beneficiary TEXT, total_tokens REAL, start_time INTEGER,
                cliff_duration INTEGER, vesting_duration INTEGER,
                released REAL DEFAULT 0, category TEXT DEFAULT 'team'
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                beneficiary TEXT, amount REAL, timestamp INTEGER,
                FOREIGN KEY (beneficiary) REFERENCES schedules(beneficiary)
            )""")

    def create_schedule(self, beneficiary: str, total_tokens: float, start_time: int,
                        cliff_days: int, vesting_days: int, category: str = "team") -> VestingSchedule:
        schedule = VestingSchedule(
            beneficiary=beneficiary, total_tokens=total_tokens,
            start_time=start_time, cliff_duration=cliff_days * 86400,
            vesting_duration=vesting_days * 86400, category=category,
        )
        self.schedules.append(schedule)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO schedules (beneficiary, total_tokens, start_time, cliff_duration, vesting_duration, category) VALUES (?,?,?,?,?,?)",
                (beneficiary, total_tokens, start_time, cliff_days * 86400, vesting_days * 86400, category)
            )
        logger.info(f"Created vesting: {beneficiary[:10]}... ({total_tokens:,.0f} tokens, {vesting_days}d)")
        return schedule

    def release_tokens(self, beneficiary: str, current_time: int, amount: Optional[float] = None) -> Optional[float]:
        for schedule in self.schedules:
            if schedule.beneficiary == beneficiary:
                releasable = schedule.get_releasable(current_time)
                release_amount = min(amount or releasable, releasable)
                if release_amount > 0:
                    schedule.released += release_amount
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            "UPDATE schedules SET released = ? WHERE beneficiary = ?",
                            (schedule.released, beneficiary)
                        )
                        conn.execute(
                            "INSERT INTO releases (beneficiary, amount, timestamp) VALUES (?,?,?)",
                            (beneficiary, release_amount, current_time)
                        )
                    logger.info(f"Released {release_amount:,.0f} to {beneficiary[:10]}...")
                    return release_amount
        return None

    def get_summary(self, current_time: int) -> Dict:
        total_locked = sum(s.total_tokens for s in self.schedules)
        total_vested = sum(s.get_vested_amount(current_time) for s in self.schedules)
        total_released = sum(s.released for s in self.schedules)
        by_category = {}
        for s in self.schedules:
            if s.category not in by_category:
                by_category[s.category] = {"count": 0, "total": 0, "vested": 0}
            by_category[s.category]["count"] += 1
            by_category[s.category]["total"] += s.total_tokens
            by_category[s.category]["vested"] += s.get_vested_amount(current_time)

        return {
            "total_schedules": len(self.schedules),
            "total_tokens": f"{total_locked:,.0f}",
            "total_vested": f"{total_vested:,.0f}",
            "total_released": f"{total_released:,.0f}",
            "locked": f"{total_locked - total_vested:,.0f}",
            "releasable": f"{total_vested - total_released:,.0f}",
            "by_category": {k: {"count": v["count"], "total": f"{v['total']:,.0f}", "vested": f"{v['vested']:,.0f}"} for k, v in by_category.items()},
        }

    def get_all_progress(self, current_time: int) -> List[Dict]:
        return [s.get_progress(current_time) for s in self.schedules]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MiMo Token Vesting")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--check", help="Check beneficiary vesting status")
    parser.add_argument("--release", help="Release tokens for beneficiary")
    parser.add_argument("--db", default="vesting.db")
    parser.add_argument("--day", type=int, default=150, help="Day to check (from start)")
    args = parser.parse_args()

    manager = VestingManager(db_path=args.db)

    now = 1700000000
    check_time = now + args.day * 86400

    if not manager.schedules:
        schedules = [
            ("0xTeam1", 10000000, now, 90, 365, "team"),
            ("0xTeam2", 5000000, now, 90, 365, "team"),
            ("0xAdvisor1", 2000000, now, 30, 180, "advisor"),
            ("0xInvestor1", 15000000, now, 30, 730, "investor"),
            ("0xEcosystem", 20000000, now, 0, 1095, "ecosystem"),
        ]
        for ben, tokens, start, cliff, vest, cat in schedules:
            manager.create_schedule(ben, tokens, start, cliff, vest, cat)

    if args.summary:
        print(json.dumps(manager.get_summary(check_time), indent=2))
    elif args.check:
        progress = [s.get_progress(check_time) for s in manager.schedules if s.beneficiary == args.check]
        print(json.dumps(progress[0] if progress else {"error": "Not found"}, indent=2))
    else:
        print("MiMo Token Vesting Manager")
        summary = manager.get_summary(check_time)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
