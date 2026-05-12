import re
from datetime import datetime


class NegotiationLogParser:
    """Extract negotiation-related timestamps from connector logs."""

    EVENT_PATTERNS = {
        "negotiation_start": re.compile(r"(?P<ts>\d{2}:\d{2}:\d{2}).*contract negotiation initiated", re.IGNORECASE),
        "agreement": re.compile(r"(?P<ts>\d{2}:\d{2}:\d{2}).*contract agreement finalized", re.IGNORECASE),
        "transfer_start": re.compile(r"(?P<ts>\d{2}:\d{2}:\d{2}).*transfer process started", re.IGNORECASE),
    }

    @classmethod
    def parse_log_text(cls, log_text, connector_name=None):
        if not log_text:
            return []

        events = {}
        for line in str(log_text).splitlines():
            for event_name, pattern in cls.EVENT_PATTERNS.items():
                match = pattern.search(line)
                if match and event_name not in events:
                    events[event_name] = match.group("ts")

        if not events:
            return []

        record = {
            "connector": connector_name,
            "negotiation_start": events.get("negotiation_start"),
            "agreement": events.get("agreement"),
            "transfer_start": events.get("transfer_start"),
        }

        if events.get("negotiation_start") and events.get("agreement"):
            start = datetime.strptime(events["negotiation_start"], "%H:%M:%S")
            end = datetime.strptime(events["agreement"], "%H:%M:%S")
            record["log_negotiation_latency_ms"] = int((end - start).total_seconds() * 1000)

        return [record]
