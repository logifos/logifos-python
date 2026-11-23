# logifos-python

`logifos` connects Python to the Logifos native C ABI using `ctypes`.
The current engine supports capability negotiation and typed refusals.
Rendering, font validation and external formula qualification are unavailable;
no SVG or PNG is produced by the current engine.

## Select a native library

Python 3.9 or later is required. The wheel contains Python code and the MIT
license. It does not contain or build a native library. Supply a compatible
native library separately and set `LOGIFOS_LIBRARY_PATH` to its file name:

```python
import os
import logifos

engine = logifos.NativeContext(os.environ["LOGIFOS_LIBRARY_PATH"])
capabilities = engine.negotiate()
assert capabilities["implemented_operations"] == []
assert capabilities["outputs"] == []
assert capabilities["formula_contract"] is None
```

Construction checks ABI version 1, schema version 1, an engine version and the
buffer-v1/JSON-v1 feature bits before transport use. Unknown feature bits are
ignored; the package version is independent of ABI and schema versions.
An explicit `library_path` selects that exact file, including relative file
names. Loading or compatibility failure raises `NativeLibraryError` without
searching elsewhere. When no argument is given, `LOGIFOS_LIBRARY_PATH` selects
the file. Only when both are absent does the system loader search for
`logifos_ffi`. Importing the package does not load a library.

Each context retains its library and matching allocator functions. Contexts
can coexist, and constructing one does not change another. Every response is
copied into Python-owned bytes and freed exactly once through its allocating
context before JSON decoding. No native response pointer escapes the call.

## Requests, resources and refusals

`engine.request(message)` accepts a dictionary or exact `bytes`, `bytearray`
or `memoryview`. It returns the decoded `result` or raises an `EngineError`
subclass with `code`, `message`, `path` and `stage`. Dictionary requests use
UTF-8 without Unicode normalization; byte requests preserve their exact length,
including embedded NULs, for native decoding. `engine.request_bytes(data)` is
the low-level transport: it returns the complete JSON envelope as owned bytes,
including refusal envelopes. It raises for transport or buffer failures.

`engine.render(formula, fmt="svg", formula_contract=identity, options=options)`
forwards the caller's model and immutable external contract descriptor. It
performs no formula conversion or layout. A well-formed request currently raises
`OperationNotImplementedError` with native code `NOT_IMPLEMENTED`; PNG requests
raise `UnsupportedOutputError`. Omitting the identity sends null and receives
the core's `InvalidRequestError`. Negotiation currently supplies no qualified
formula identity, so the runtime never invents one. The SVG-to-UTF-8-bytes
adapter is prepared for a future engine result; it is not evidence of rendering.

Options are per call and use the native envelope keys: `font_size_px`, `display`,
`color`, `limits`, `fonts` and `fallback_order`. The binding does not mutate them
or retain resources between calls. Create a wire font resource from caller bytes
with `logifos.font_resource(resource_id, data, face_index=0)`. It computes SHA-256
and padded base64; put the returned dictionary in `options["fonts"]` and list
its ID in `options["fallback_order"]`. No fonts are bundled, discovered or
fetched. The current core refuses nonempty font resources with
`OperationNotImplementedError`; encoding bytes does not validate a font.

Other native refusals map to `InvalidRequestError`, `ResourceLimitError`,
`FontError`, `ContractError` or the base `EngineError`. Transport failures raise
`TransportError` with numeric `status` and symbolic `code`; malformed native
responses raise `ProtocolError`.

The module functions `logifos.negotiate` and `logifos.render` accept either
`context=engine` or `library_path=...`. Without either they construct a context
using the selection rules above. There is no mutable process-wide context.

## Installed-package checks

Build the wheel with `python -m build --wheel`, install it into a separate
virtual environment, and run checks from outside the source checkout. Set
`LOGIFOS_TEST_LIBRARY` to the matching native library for integration checks.
Use isolated Python imports and disable pytest's cache:

```sh
python -B -I -m pytest --import-mode=importlib -p no:cacheprovider \
  "$checkout/tests/test_render.py" "$checkout/tests/test_native_runtime.py" \
  -k 'negotiate or bytes or unicode or refusal or independent_contexts or repeated_cleanup'
python -B -I "$checkout/tests/test_distribution.py" "$wheel"
```

Here `checkout` and `wheel` identify the source checkout and built wheel.
Without `LOGIFOS_TEST_LIBRARY`, native integration checks are skipped; fixed
ABI-response tests still run. Those fixed responses test Python encoding and
ownership only. Native tests establish negotiation, UTF-8 byte limits, typed
refusals, per-call options, independent library contexts and repeated cleanup.
They do not establish rendering, platform-wheel coverage or release readiness.
