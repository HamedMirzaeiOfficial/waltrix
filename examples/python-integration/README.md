# Python integration example

A marketplace checkout (hold, partial capture, partial refund) using the `waltrix` SDK.

```bash
pip install -e packages/python-sdk
WALTRIX_API_KEY=wtx_key_... python examples/python-integration/checkout.py
```

Create the key in the dashboard (API keys, role `finance_operator`) or use the one printed by `waltrix seed-demo`.
