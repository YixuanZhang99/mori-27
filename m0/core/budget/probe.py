"""M3HealthProbe and efficiency metrics (N13/N11), computed from append-only data.

These are structural ratios, not ledger self-consistency checks: a perfectly
balanced ledger can still reveal budget misallocation here (I-β).
"""
from __future__ import annotations


class M3HealthProbe:
    @staticmethod
    def compute(ledger, funnels) -> dict:
        spent = ledger.spent
        total_spent = sum(spent.values())
        entries = list(ledger.store.read("ledger"))
        deltas = [abs(float(e["payload"].get("settled", 0)))
                  for e in entries if e["payload"]["entry_kind"] == "reconcile_delta"]
        productive = spent["explore"] + spent["exploit"] + spent["reeval"] + spent["control"]
        hidden = spent["reeval"] + spent["repair"] + spent["overhead"]
        admitted = sum(f.admitted for f in funnels)
        return {
            "effective_budget_ratio": productive / total_spent if total_spent else 1.0,
            "reconcile_delta_ratio": sum(deltas) / total_spent if total_spent else 0.0,
            "hidden_account_ratio": hidden / total_spent if total_spent else 0.0,
            "control_fulfillment_ratio": (spent["control"] / ledger.locked_control
                                          if ledger.locked_control else 0.0),
            "admitted_per_1k_tokens": admitted / total_spent * 1000 if total_spent else 0.0,
            "total_spent": total_spent,
            "admitted": admitted,
        }
