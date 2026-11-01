"""Separate reduction journals sharing the established immutable POSIX IO rules."""

from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore


class LocalReductionCampaignStore(LocalSearchCampaignStore):
    """Cancellation bypasses the coordinator lock; it never replaces an outcome."""

    _namespace_name = "reduction-campaigns"
    _extra_record_names = frozenset({"cancel.json"})
    _result_limit = 128 * 1024

    def get_cancel(self, plan_id: str) -> bytes | None:
        return self._get(plan_id, None, "cancel.json", 64 * 1024)

    def write_cancel(self, plan_id: str, raw: bytes) -> None:
        self._put(plan_id, None, "cancel.json", raw, 64 * 1024)
