"""C ABI ownership, JSON envelopes and per-library runtime state."""

import base64
import ctypes
from ctypes.util import find_library
import hashlib
import json
import os


_ABI_VERSION = 1
_SCHEMA_VERSION = 1
_REQUIRED_FEATURES = 1 | 2  # Buffer-v1 and JSON-v1.


class LogifosError(Exception):
    """Base for native loading, transport and engine failures."""


class NativeLibraryError(LogifosError):
    """The selected library cannot be loaded or is incompatible."""


class ProtocolError(LogifosError):
    """The native response violates the supported envelope contract."""


class TransportError(LogifosError):
    """A transport failure with no JSON response."""

    def __init__(self, status):
        self.status = status
        self.code = {1: "INVALID_REQUEST", 2: "ALLOCATION_FAILED",
                     3: "INTERNAL_ERROR"}.get(status, "UNKNOWN_TRANSPORT_STATUS")
        super().__init__(f"{self.code} (transport status {status})")


class EngineError(LogifosError):
    """A typed native refusal; diagnostics retain code, message, path and stage."""

    def __init__(self, code, message, path, stage):
        self.code, self.message = code, message
        self.path, self.stage = path, stage
        super().__init__(f"{code} at {path or '/'} ({stage}): {message}")


class OperationNotImplementedError(EngineError, NotImplementedError):
    """The requested native operation is not implemented."""


class UnsupportedOutputError(EngineError):
    """The core does not provide the requested output."""


class InvalidRequestError(EngineError, ValueError):
    """The native decoder or request validator rejected the input."""


class ResourceLimitError(EngineError):
    """A per-call resource ceiling was exceeded."""


class FontError(EngineError):
    """Caller-supplied font resources could not be used."""


class ContractError(EngineError):
    """An external contract is unavailable or mismatched."""


_ERROR_TYPES = {
    "NOT_IMPLEMENTED": OperationNotImplementedError,
    "UNSUPPORTED_OUTPUT": UnsupportedOutputError,
    "RESOURCE_LIMIT": ResourceLimitError,
    **dict.fromkeys(("INVALID_UTF8", "INVALID_JSON", "INVALID_REQUEST",
                     "UNSUPPORTED_ABI", "UNSUPPORTED_SCHEMA", "UNKNOWN_OPTION"),
                    InvalidRequestError),
    **dict.fromkeys(("INVALID_FONT", "FONT_HASH_MISMATCH", "MISSING_FONT",
                     "MISSING_GLYPH"), FontError),
    **dict.fromkeys(("UNPINNED_CONTRACT", "CONTRACT_MISMATCH"), ContractError),
}


class _Buffer(ctypes.Structure):
    _fields_ = [("ptr", ctypes.POINTER(ctypes.c_uint8)), ("len", ctypes.c_size_t)]


def _bytes(value):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("expected bytes, bytearray or memoryview")
    return bytes(value)


def font_resource(resource_id, data, face_index=0):
    """Encode caller bytes without loading, discovering or validating fonts."""
    data = _bytes(data)
    return {"id": resource_id, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes_base64": base64.b64encode(data).decode("ascii"),
            "face_index": face_index}


def _reject_constant(value):
    raise ValueError("nonfinite JSON number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _result(data):
    try:
        reply = json.loads(data.decode("utf-8"), parse_constant=_reject_constant,
                           object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ProtocolError("native response is not valid UTF-8 JSON") from error
    if not isinstance(reply, dict) or any(
        type(reply.get(key)) is not int or reply[key] != 1
        for key in ("abi_version", "schema_version")
    ):
        raise ProtocolError("unsupported native response versions")
    if reply.get("ok") is True:
        if (set(reply) != {"abi_version", "schema_version", "ok", "result"}
                or not isinstance(reply["result"], dict)):
            raise ProtocolError("invalid native success envelope")
        return reply["result"]
    if reply.get("ok") is not False or set(reply) != {"abi_version", "schema_version", "ok", "error"}:
        raise ProtocolError("invalid native response envelope")
    failure = reply["error"]
    if not isinstance(failure, dict) or set(failure) != {"code", "message", "path", "stage"} or any(
        not isinstance(value, str) for value in failure.values()
    ):
        raise ProtocolError("invalid native refusal details")
    raise _ERROR_TYPES.get(failure["code"], EngineError)(**failure)


class NativeContext:
    """Own one loaded library and its matching request/free functions.

    An explicit path, including LOGIFOS_LIBRARY_PATH, is authoritative. Without
    either, the system loader is queried for logifos_ffi. No library is bundled.
    """

    def __init__(self, library_path=None):
        if library_path is None:
            library_path = os.environ.get("LOGIFOS_LIBRARY_PATH")
        explicit = library_path is not None
        if library_path is None:
            library_path = find_library("logifos_ffi")
        if not library_path:
            raise NativeLibraryError("select a native library with library_path or LOGIFOS_LIBRARY_PATH")
        self.library_path = os.fsdecode(os.fspath(library_path))
        if explicit:
            self.library_path = os.path.abspath(self.library_path)
        try:
            self._library = ctypes.CDLL(self.library_path)
            for name, result in (("logifos_abi_version", ctypes.c_uint32),
                                 ("logifos_schema_version", ctypes.c_uint32),
                                 ("logifos_features", ctypes.c_uint64),
                                 ("logifos_engine_version", ctypes.c_char_p)):
                function = getattr(self._library, name)
                function.argtypes, function.restype = [], result
            self.abi_version = self._library.logifos_abi_version()
            self.schema_version = self._library.logifos_schema_version()
            self.features = self._library.logifos_features()
            version = self._library.logifos_engine_version()
            if self.abi_version != _ABI_VERSION or self.schema_version != _SCHEMA_VERSION:
                raise NativeLibraryError("native ABI and schema versions must both be 1")
            if self.features & _REQUIRED_FEATURES != _REQUIRED_FEATURES:
                raise NativeLibraryError("native library requires buffer-v1 and JSON-v1 features")
            if not version:
                raise NativeLibraryError("native engine version is missing")
            self.engine_version = version.decode("utf-8")
            self._request = self._library.logifos_request_v1
            self._request.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                                      ctypes.POINTER(_Buffer)]
            self._request.restype = ctypes.c_uint32
            self._free = self._library.logifos_buffer_free_v1
            self._free.argtypes, self._free.restype = [_Buffer], None
        except (OSError, AttributeError, ValueError) as error:
            raise NativeLibraryError(f"cannot use native library: {error}") from error

    def request_bytes(self, payload) -> bytes:
        """Copy a raw JSON envelope, raising for transport or buffer failures.

        The owned response is released before returning, including when copying
        fails. The input copy stays alive and unchanged until the call returns.
        """
        payload = _bytes(payload)
        source = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        response = _Buffer()
        status = self._request(source, len(payload), ctypes.byref(response))
        if status != 0:
            raise TransportError(status)
        try:
            if not response.ptr or response.len == 0:
                raise ProtocolError("native transport returned an empty response")
            return ctypes.string_at(response.ptr, response.len)
        finally:
            self._free(response)
            response.ptr, response.len = None, 0

    def request(self, payload):
        """Send a JSON object or exact bytes and return its result or raise."""
        if isinstance(payload, dict):
            payload = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
        return _result(self.request_bytes(payload))

    def negotiate(self, *, options=None):
        """Query capabilities with options scoped to this call."""
        request = {"abi_version": 1, "schema_version": 1, "op": "negotiate"}
        if options is not None:
            request["options"] = options
        result = self.request(request)
        if (result.get("kind") != "capabilities"
                or result.get("abi_versions") != [1]
                or result.get("schema_versions") != [1]):
            raise ProtocolError("invalid native capabilities")
        return result

    def render(self, formula, fmt="svg", *, formula_contract=None, options=None) -> bytes:
        """Forward the caller's model, identity and options without conversion.

        A missing identity is sent as null for the core to refuse. Rendering
        requires an implemented native operation and a qualified caller model.
        """
        request = {"abi_version": 1, "schema_version": 1, "op": "render",
                   "formula": formula, "formula_contract": formula_contract,
                   "output": fmt}
        if options is not None:
            request["options"] = options
        result = self.request(request)
        if (result.get("kind") != "svg"
                or result.get("media_type") != "image/svg+xml"
                or result.get("encoding") != "utf-8"
                or not isinstance(result.get("svg"), str)):
            raise ProtocolError("expected a UTF-8 SVG result")
        return result["svg"].encode("utf-8")
