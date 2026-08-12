# Economics and agent payments

TokenSurf can treat spending as part of an agent's tested behavior. Record each payment result in
the trace, then enforce a per-run budget, a settlement-count limit, and an allowlist of recipients.
The checks are deterministic and run locally or in CI.

The helper is protocol-neutral but defaults to `x402`. In x402, a server responds with HTTP 402
and payment requirements; the client signs a payment and retries; a successful response includes
the settlement result. Call `record_payment()` after that client flow completes. TokenSurf does
not handle wallets, sign payments, or proxy payment traffic.

## Record a settlement

```python
import tokensurf as ts


def buy_resource(client, url):
    response = client.get(url)  # your x402-enabled client handles the payment flow
    settlement = response.payment_response

    ts.record_payment(
        protocol="x402",
        amount=settlement.amount,       # native amount / base units
        amount_usd=0.025,               # conversion known by this application
        asset=settlement.asset,
        network=settlement.network,
        recipient=settlement.pay_to,
        payer=settlement.payer,
        success=settlement.success,
        transaction=settlement.transaction,
    )
    return response.json()
```

The field names on your payment client may differ; map its settlement result into the helper. The
returned `Span` is attached to the current tracked or evaluated trace.

`amount` is the protocol-native value and may be in base units. `amount_usd` is a separate,
optional number. TokenSurf deliberately does not perform exchange-rate or token-decimal lookups.
This avoids a dangerous failure mode where native amounts from different assets are added as if
they were dollars.

Do not put payment signatures, authorization headers, private keys, or secrets into a trace.

## Add economics scorers

```python
scorers = [
    ts.PaymentCostUnder(usd=0.10),
    ts.PaymentCountAtMost(max_payments=3),
    ts.PaymentRecipientsAllowed({"0xmerchant"}),
]

report = ts.evaluate(task=my_agent, data=data, scorers=scorers)
ts.assert_eval(report, min_pass_rate=1.0)
```

- `PaymentCostUnder` sums only successful settlements with explicit USD amounts. An unpriced
  successful payment produces an errored score rather than an incorrect low total.
- `PaymentCountAtMost` limits successful settlements.
- `PaymentRecipientsAllowed` checks every attempt, including failures and missing recipients.
- The existing `CostUnder` includes both ordinary span costs and successful payments when
  `amount_usd` was supplied.

## Dashboard

Push the eval report to your self-hosted TokenSurf server as usual. The **Economics** item in the
left sidebar shows total settled USD, successful and failed payment counts, unpriced settlements,
spend by project, and the latest payment attempts. Payment data stays inside the stored trace, so
this feature requires no new database table or migration.

The dashboard is an eval cost tracker, not an accounting ledger. Production balances, refunds,
confirmations, and reconciliation should continue to come from the payment network and wallet.
