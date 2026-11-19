# Chapter 9 — API and SDK design

**English** · [فارسی](../09-api-and-sdks.md)

Files for this chapter: `apps/api/src/waltrix_api/{schemas,presenters,errors}.py`, `services/queries.py::paginate`, `packages/python-sdk/src/waltrix/`, `packages/typescript-sdk/src/`, [rest.md](../../api/rest.md)

## 1. One error shape

```json
{"error": {"code": "insufficient_funds", "message": "...", "details": {"transaction_id": "..."},
           "correlation_id": "4f2c..."}}
```

- `code` is stable and machine-readable; clients decide on it, not on the message text.
- Every error carries a `correlation_id`; the user gives it to support, and support finds exactly that request in the logs.
- 500 errors never reveal internals (stack traces, SQL).

Domain errors (`WaltrixError`) carry a `status_hint`, and `errors.install` translates them into HTTP. The core does not know HTTP; it only "suggests".

## 2. 422 for business failures

What status should `insufficient_funds` have? 400 (bad request)? 409 (conflict)? 402? Waltrix returns 422 and gives the id of the recorded FAILED transaction in `details.transaction_id`. More important than the number is **consistency**: the code table in `rest.md` and the SDK's distinction between "business failure" and "validation" (`isBusinessFailure`).

## 3. Cursor pagination, not offset

```python
stmt.where(or_(model.created_at < ts, and_(model.created_at == ts, model.id < id_)))
    .order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)
```

With `OFFSET 50`:

- If a new transaction arrives between requesting page 1 and page 2, everything shifts by one and a row is seen **twice**. In a ledger that keeps growing, this is a certainty.
- `OFFSET 100000` means the database reads 100,000 rows and throws them away.

A cursor (keyset) remembers the position of the last row as `(created_at, id)`. The `id` is needed as a tie-breaker because two rows can share a `created_at`. `limit + 1` rows are read so we know whether there is a next page without a `COUNT`. The cursor is opaque base64 so that clients do not depend on its structure.

## 4. Versioning and the contract

Everything lives under `/api/v1`. OpenAPI is published automatically at `/api/v1/openapi.json`. A test (`test_openapi_documents_idempotency`) checks that `Idempotency-Key` is documented as **required** in the schema. At first it was not (chapter 13): the function enforced it, but the schema said it was optional.

## 5. The Python SDK: one table, two clients

The problem: we want sync and async clients with the same 25 methods and the same type hints. Writing them twice means writing every bug twice.

The solution in `_endpoints.py` and `client.py`: each endpoint is a typed function that returns a `Spec[T]` (a description of the request). Two helpers using `ParamSpec` turn it into a sync or an async method:

```python
def _sync(fn: Callable[P, ep.Spec[T]]) -> Callable[Concatenate[Any, P], T]:
    def method(self: Any, /, *args: P.args, **kwargs: P.kwargs) -> T: ...

class Wallets(_Resource):
    create = _sync(ep.create_wallet)

class AsyncWallets(_Resource):
    create = _async(ep.create_wallet)
```

`ParamSpec` preserves the original function's signature, so mypy reports "float instead of int" for `client.transfers.create(a, b, 1.5, "USD")`, and `await aclient.wallets.get(...)` is typed `Wallet`. We checked this with `reveal_type`.

The slash in `self: Any, /` makes `self` positional-only. Without it mypy complained that someone might pass `self=` as a keyword, and the signature would not match `Concatenate`.

## 6. The TypeScript SDK

- **Two authentication modes:** `apiKey` for servers, `session` for browsers (cookie + CSRF header + organization). Combining both is an error.
- **Cancellation:** every method accepts an `AbortSignal`; the internal timeout is combined with it through a separate `AbortController`.
- **Ids in paths:** `seg()` uses `encodeURIComponent` and rejects `/`, which stops `../api-keys` (path traversal in the client).
- **The money module:** `parseMoney`/`formatMoney` work on strings and integers. `Intl.NumberFormat` accepts a decimal string directly, so no float division is ever needed.

## 7. The examples were actually run

`examples/python-integration/checkout.py` (hold, partial capture, refund) and `examples/typescript-integration/index.ts` (a payout with an idempotency key from the domain) both ran against a real server. An example that was never run is not documentation; it is hope.

## Exercises

1. Add a `wallets.close` method to the Python SDK (the API endpoint exists). How many lines did it take? Do both sync and async work?
2. Implement offset pagination for `/wallets` and write a test that, with a concurrent insert between two pages, shows a duplicated row. Then run the same test with the cursor.
3. The TypeScript SDK does not retry a 500 on GET. Should it? Argue your case and implement it if needed.
4. Write a `.pyi` or a mypy test that proves `client.holds.capture("h", amount=1.5)` is a type error.
