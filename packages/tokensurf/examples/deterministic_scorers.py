"""Example: deterministic scorers (ExactMatch, Contains, Regex, JSONSchemaValid).

Run as a library:
    from deterministic_scorers import main; main()
Run via the CLI:
    tokensurf eval run packages/tokensurf/examples/deterministic_scorers.py

Fully offline — no network, no provider key. The "agent" under test is a tiny
in-memory order-lookup tool that returns a JSON string per order id.
"""

from __future__ import annotations

import json

import tokensurf as ts
from tokensurf.eval.reporter import render_console

_ORDERS = {
    "o1": {"status": "shipped", "total": 42.50},
    "o2": {"status": "pending", "total": 10.00},
    "o3": {"status": "shipped", "total": 7.25},
}


def task(order_id: str) -> str:
    """Looks up an order and returns it as a JSON string."""
    with ts.span("lookup_order", type="tool", input=order_id) as sp:
        order = _ORDERS.get(order_id, {"status": "not_found", "total": 0})
        output = json.dumps(order)
        sp.output = output
        return output


data = ts.Dataset.from_list(
    [
        {"id": "c1", "input": "o1", "expected": '{"status": "shipped", "total": 42.5}'},
        {"id": "c2", "input": "o2", "expected": '{"status": "pending", "total": 10.0}'},
        {"id": "c3", "input": "o4", "expected": '{"status": "not_found", "total": 0}'},
    ]
)


scorers: list[ts.Scorer] = [
    # Byte-for-byte compare against case.expected.
    ts.ExactMatch(),
    # Loose substring check: every shipped order mentions "shipped" somewhere.
    ts.Contains("shipped", case_sensitive=False),
    # The output always looks like a JSON object.
    ts.Regex(r"^\{.*\}$"),
    # The output must parse as JSON matching this shape.
    ts.JSONSchemaValid(
        schema={
            "type": "object",
            "required": ["status", "total"],
            "properties": {
                "status": {"type": "string"},
                "total": {"type": "number"},
            },
        }
    ),
]


def main() -> ts.EvalReport:
    report = ts.evaluate(task=task, data=data, scorers=scorers)
    print(render_console(report))
    ts.assert_eval(report, min_pass_rate=0.5)
    return report


if __name__ == "__main__":
    main()
