"""Creates per-user alerts in Convex when anomalies match user preferences.

The alert pipeline runs after SyncLayer refreshes anomalies into the cache.
It compares current anomaly IDs against previously-seen IDs, then for each
new anomaly matches it against alertable users' category/platform preferences.
Alerts are batched and sent to Convex via the HTTP API.

Throttling:
  - Each anomaly_id is only alerted once per session (dedup set)
  - Max alerts per user per hour is capped (default 10)
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from nexus.core.logging import LoggerMixin
from nexus.sync.convex_client import ConvexClient, ConvexError


class AlertCreator(LoggerMixin):
    """Creates per-user alerts in Convex for new anomalies."""

    def __init__(
        self,
        convex: ConvexClient,
        max_alerts_per_user_per_hour: int = 10,
    ) -> None:
        self._convex = convex
        self._max_per_hour = max_alerts_per_user_per_hour
        # Dedup: anomaly IDs we've already processed this session
        self._alerted_ids: Set[int] = set()
        # Throttle: {user_id: [timestamp, ...]} of recent alert sends
        self._user_alert_times: Dict[str, List[float]] = defaultdict(list)
        # Cache alertable users (refreshed periodically)
        self._users_cache: Optional[List[Dict[str, Any]]] = None
        self._users_cache_ts: float = 0.0
        self._users_cache_ttl: float = 300.0  # 5 minutes

    async def process_new_anomalies(
        self, anomalies: List[Dict[str, Any]]
    ) -> int:
        """Match new anomalies against user preferences and create alerts.

        Args:
            anomalies: List of anomaly dicts from BroadcastCache (same shape
                as the REST API response).

        Returns:
            Number of alerts created.
        """
        # Find anomalies we haven't alerted yet
        new_anomalies = [
            a for a in anomalies
            if a.get("anomalyId") and a["anomalyId"] not in self._alerted_ids
        ]
        if not new_anomalies:
            return 0

        # Get alertable users (cached)
        users = await self._get_alertable_users()
        if not users:
            # Mark as seen even if no users — avoid re-processing
            for a in new_anomalies:
                self._alerted_ids.add(a["anomalyId"])
            return 0

        now = time.time()
        alerts_to_create: List[Dict[str, Any]] = []

        for anomaly in new_anomalies:
            anomaly_id = anomaly["anomalyId"]
            category = (anomaly.get("clusterName") or "").strip()
            # Also check the catalyst category if available
            catalyst = anomaly.get("catalyst")
            if not category and catalyst and isinstance(catalyst, dict):
                category = catalyst.get("catalyst_type", "")

            platform = anomaly.get("platform", "")
            severity = anomaly.get("severity", 0)

            for user in users:
                user_id = user["userId"]

                # Throttle check
                if not self._can_alert_user(user_id, now):
                    continue

                # Preference matching
                if not self._matches_preferences(
                    user, category=category, platform=platform
                ):
                    continue

                # Build alert
                headline = anomaly.get("summary", "Anomaly detected")
                if catalyst and isinstance(catalyst, dict):
                    headline = catalyst.get("headline", headline)

                alerts_to_create.append({
                    "userId": user_id,
                    "type": "anomaly",
                    "title": headline,
                    "message": anomaly.get("summary", ""),
                    "data": {"anomalyId": anomaly_id},
                })
                self._user_alert_times[user_id].append(now)

            self._alerted_ids.add(anomaly_id)

        if not alerts_to_create:
            return 0

        # Batch send to Convex
        return await self._send_alerts(alerts_to_create)

    def _can_alert_user(self, user_id: str, now: float) -> bool:
        """Check if user hasn't exceeded hourly alert limit."""
        cutoff = now - 3600
        recent = [t for t in self._user_alert_times[user_id] if t > cutoff]
        self._user_alert_times[user_id] = recent  # Prune old entries
        return len(recent) < self._max_per_hour

    @staticmethod
    def _matches_preferences(
        user: Dict[str, Any],
        category: str = "",
        platform: str = "",
    ) -> bool:
        """Check if an anomaly matches a user's category/platform preferences.

        Empty preference lists mean "all" (no filtering).
        """
        user_categories = user.get("categories", [])
        user_platforms = user.get("platforms", [])

        # If user has category filters, check match (case-insensitive)
        if user_categories and category:
            cat_lower = category.lower()
            if not any(c.lower() == cat_lower for c in user_categories):
                return False

        # If user has platform filters, check match
        if user_platforms and platform:
            if platform.lower() not in [p.lower() for p in user_platforms]:
                return False

        return True

    async def _get_alertable_users(self) -> List[Dict[str, Any]]:
        """Fetch users with alerts enabled (cached for 5 minutes)."""
        now = time.time()
        if (
            self._users_cache is not None
            and now - self._users_cache_ts < self._users_cache_ttl
        ):
            return self._users_cache

        try:
            users = await self._convex.query("alerts:getAlertableUsers")
            self._users_cache = users or []
            self._users_cache_ts = now
        except ConvexError:
            self.logger.debug("alertable_users_fetch_failed", exc_info=True)
            self._users_cache = self._users_cache or []

        return self._users_cache

    async def _send_alerts(self, alerts: List[Dict[str, Any]]) -> int:
        """Send alerts to Convex in a batch. Returns count created."""
        try:
            result = await self._convex.mutation(
                "alerts:createAlerts", {"alerts": alerts}
            )
            count = result if isinstance(result, int) else len(alerts)
            self.logger.info("alerts_created", count=count)
            return count
        except ConvexError:
            self.logger.warning(
                "alert_creation_failed",
                attempted=len(alerts),
                exc_info=True,
            )
            return 0
