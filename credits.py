from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "bot_data.json")


@dataclass
class UserData:
    user_id: int
    username: str = ""
    balance: int = 0
    total_views: int = 0
    is_banned: bool = False
    ban_reason: str = ""
    pending_credits: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TicketData:
    ticket_id: int
    user_id: int
    channel_id: int
    status: str = "open"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    amount: int = 0
    type: str = "credit"


class DataManager:
    def __init__(self):
        self.users: Dict[int, UserData] = {}
        self.tickets: Dict[int, TicketData] = {}
        self.pending_charges: Dict[int, int] = {}
        self.pending_tickets: Dict[int, dict] = {}
        self.ticket_counter: int = 1
        self._load()

    def _load(self):
        if not os.path.exists(DATA_PATH):
            self._save()
            return
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            for uid, udata in data.get("users", {}).items():
                try:
                    self.users[int(uid)] = UserData(**udata)
                except Exception:
                    pass

            for tid, tdata in data.get("tickets", {}).items():
                try:
                    self.tickets[int(tid)] = TicketData(**tdata)
                except Exception:
                    pass

            for uid, amount in data.get("pending_charges", {}).items():
                self.pending_charges[int(uid)] = int(amount)

            raw_pending = data.get("_pending_tickets") or {}
            self.pending_tickets = {int(k): v for k, v in raw_pending.items()}

            self.ticket_counter = data.get("ticket_counter", 1)

            if self.pending_charges:
                for uid, amount in self.pending_charges.items():
                    self.get_user(uid).balance += amount
                self.pending_charges.clear()
                self._save()
        except Exception:
            self.users = {}

    def _save(self):
        try:
            data = {
                "users": {str(uid): asdict(u) for uid, u in self.users.items()},
                "tickets": {str(tid): asdict(t) for tid, t in self.tickets.items()},
                "ticket_counter": self.ticket_counter,
                "pending_charges": {str(uid): amt for uid, amt in self.pending_charges.items()},
                "_pending_tickets": {str(k): v for k, v in self.pending_tickets.items()},
            }
            tmp = DATA_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_PATH)
        except Exception:
            pass

    def save_data(self):
        self._save()

    def get_user(self, user_id: int, username: str = "") -> UserData:
        if user_id not in self.users:
            self.users[user_id] = UserData(user_id=user_id, username=username or str(user_id))
            self._save()
        elif username and self.users[user_id].username != username:
            self.users[user_id].username = username
            self._save()
        return self.users[user_id]

    def add_credits(self, user_id: int, amount: int):
        u = self.get_user(user_id)
        u.balance += max(0, int(amount))
        u.last_active = datetime.now().isoformat()
        self._save()

    def remove_credits(self, user_id: int, amount: int) -> bool:
        u = self.get_user(user_id)
        if u.balance < amount:
            return False
        u.balance -= int(amount)
        u.last_active = datetime.now().isoformat()
        self._save()
        return True

    def add_total_views(self, user_id: int, amount: int):
        u = self.get_user(user_id)
        u.total_views += int(amount)
        u.last_active = datetime.now().isoformat()
        self._save()

    def set_pending_charge(self, user_id: int, amount: int):
        self.pending_charges[user_id] = amount
        self._save()

    def clear_pending_charge(self, user_id: int):
        if user_id in self.pending_charges:
            del self.pending_charges[user_id]
            self._save()

    def create_ticket(self, user_id: int, channel_id: int, amount: int, ticket_type: str = "credit") -> TicketData:
        ticket = TicketData(
            ticket_id=self.ticket_counter,
            user_id=user_id,
            channel_id=channel_id,
            amount=amount,
            type=ticket_type,
        )
        self.tickets[self.ticket_counter] = ticket
        self.ticket_counter += 1
        user = self.get_user(user_id)
        user.pending_credits = amount
        self._save()
        return ticket

    def approve_ticket(self, ticket_id: int) -> bool:
        ticket = self.tickets.get(ticket_id)
        if ticket and ticket.type == "credit" and ticket.status == "open":
            self.add_credits(ticket.user_id, ticket.amount)
            ticket.status = "approved"
            self._save()
            return True
        return False

    def reject_ticket(self, ticket_id: int) -> bool:
        ticket = self.tickets.get(ticket_id)
        if ticket and ticket.type == "credit" and ticket.status == "open":
            user = self.get_user(ticket.user_id)
            user.pending_credits = 0
            ticket.status = "rejected"
            self._save()
            return True
        return False

    def save_pending_tickets(self, tickets: dict):
        self.pending_tickets = tickets
        self._save()

    def load_pending_tickets(self) -> dict:
        return dict(self.pending_tickets)


data_manager = DataManager()
