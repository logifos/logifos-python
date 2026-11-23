"""Focused checks of the Python binding using fixed ABI responses."""

import ctypes
import json
import os

import pytest

import logifos
from logifos import _runtime


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class Library:
    """Return predetermined transport bytes and track their ownership."""

    def __init__(self, response=b'{}', *, abi=1, schema=1, features=3, status=0):
        self.response, self.status = response, status
        self.live, self.freed, self.inputs = {}, [], []
        self.logifos_abi_version = Function(lambda: abi)
        self.logifos_schema_version = Function(lambda: schema)
        self.logifos_features = Function(lambda: features)
        self.logifos_engine_version = Function(lambda: b'test-version')
        self.logifos_request_v1 = Function(self.request)
        self.logifos_buffer_free_v1 = Function(self.free)

    def request(self, source, length, out):
        self.inputs.append(ctypes.string_at(source, length))
        if self.status:
            return self.status
        storage = (ctypes.c_uint8 * len(self.response)).from_buffer_copy(self.response)
        address = ctypes.addressof(storage)
        self.live[address] = storage
        buffer = ctypes.cast(out, ctypes.POINTER(_runtime._Buffer)).contents
        buffer.ptr = ctypes.cast(storage, ctypes.POINTER(ctypes.c_uint8))
        buffer.len = len(self.response)
        return 0

    def free(self, buffer):
        address = ctypes.cast(buffer.ptr, ctypes.c_void_p).value
        assert buffer.len == len(self.live.pop(address))
        self.freed.append((address, buffer.len))


def envelope(result):
    return json.dumps({'abi_version': 1, 'schema_version': 1,
                       'ok': True, 'result': result}, ensure_ascii=False).encode('utf-8')


def bind(monkeypatch, library):
    monkeypatch.setattr(_runtime.ctypes, 'CDLL', lambda path: library)
    return logifos.NativeContext('selected-library')


def test_negotiate_ctypes_signatures_and_unknown_feature_bits(monkeypatch):
    library = Library(features=3 | (1 << 48))
    context = bind(monkeypatch, library)
    assert context.features == 3 | (1 << 48)
    assert context.engine_version == 'test-version'
    assert library.logifos_request_v1.argtypes == [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ctypes.POINTER(_runtime._Buffer)]
    assert library.logifos_request_v1.restype is ctypes.c_uint32
    assert library.logifos_buffer_free_v1.argtypes == [_runtime._Buffer]
    assert library.logifos_buffer_free_v1.restype is None
    assert library.logifos_features.restype is ctypes.c_uint64
    assert library.logifos_engine_version.restype is ctypes.c_char_p


@pytest.mark.parametrize('settings', [{'abi': 2}, {'schema': 2}, {'features': 1},
                                     {'features': 2}, {'features': 0}])
def test_negotiate_rejects_incompatible_libraries(monkeypatch, settings):
    library = Library(**settings)
    with pytest.raises(logifos.NativeLibraryError):
        bind(monkeypatch, library)
    assert not library.inputs


def test_negotiate_missing_export_is_a_library_error(monkeypatch):
    library = Library()
    del library.logifos_buffer_free_v1
    with pytest.raises(logifos.NativeLibraryError):
        bind(monkeypatch, library)


@pytest.mark.parametrize('use_environment', [False, True])
def test_negotiate_explicit_path_never_falls_back(monkeypatch, use_environment):
    attempted = []

    def fail(path):
        attempted.append(path)
        raise OSError('unavailable')

    def forbidden(name):
        pytest.fail('explicit selection must not search for a different library')

    monkeypatch.setattr(_runtime.ctypes, 'CDLL', fail)
    monkeypatch.setattr(_runtime, 'find_library', forbidden)
    monkeypatch.setenv('LOGIFOS_LIBRARY_PATH', 'environment-library')
    selected = 'environment-library' if use_environment else 'requested-library'
    with pytest.raises(logifos.NativeLibraryError):
        logifos.NativeContext(None if use_environment else selected)
    assert attempted == [os.path.abspath(selected)]


def test_negotiate_empty_explicit_path_is_an_error(monkeypatch):
    monkeypatch.setenv('LOGIFOS_LIBRARY_PATH', 'other-library')
    with pytest.raises(logifos.NativeLibraryError):
        logifos.NativeContext('')


@pytest.mark.parametrize('status,code', [(1, 'INVALID_REQUEST'), (2, 'ALLOCATION_FAILED'),
                                        (3, 'INTERNAL_ERROR'), (77, 'UNKNOWN_TRANSPORT_STATUS')])
def test_refusal_transport_status_has_no_json_or_cleanup(monkeypatch, status, code):
    library = Library(status=status)
    context = bind(monkeypatch, library)
    with pytest.raises(logifos.TransportError) as caught:
        context.request(b'{}')
    assert (caught.value.status, caught.value.code) == (status, code)
    assert not library.live and not library.freed


@pytest.mark.parametrize('response', [b'\xff', b'{}', b'{"abi_version":1,"abi_version":1}',
                                     b'{"abi_version":true,"schema_version":1}',
                                     b'{"abi_version":1,"schema_version":1,"ok":false,"error":{}}',
                                     envelope({'number': float('nan')}), b''])
def test_refusal_malformed_response_is_freed(monkeypatch, response):
    library = Library(response)
    context = bind(monkeypatch, library)
    with pytest.raises(logifos.ProtocolError):
        context.request(b'{}')
    assert not library.live and len(library.freed) == 1


def test_bytes_unicode_svg_adapter_and_unchanged_options(monkeypatch):
    # Fixed text exercises encoding only; it is not an engine render baseline.
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><title>α\x00𝛽</title></svg>'
    library = Library(envelope({'kind': 'svg', 'media_type': 'image/svg+xml',
                                'encoding': 'utf-8', 'svg': svg}))
    context = bind(monkeypatch, library)
    formula = {'opaque': 'αe\u0301𝛽'}
    options = {'color': '#123456', 'fonts': [logifos.font_resource('math', b'\x00\xff')],
               'fallback_order': ['math']}
    before = json.dumps(options)
    result = logifos.render(formula, context=context, formula_contract={'opaque': True},
                            options=options)
    assert result == svg.encode('utf-8') and type(result) is bytes
    wire = json.loads(library.inputs[0])
    assert wire['formula'] == formula and wire['options'] == options
    assert '𝛽'.encode('utf-8') in library.inputs[0]
    assert json.dumps(options) == before
    assert not library.live and len(library.freed) == 1


def test_independent_contexts_keep_allocator_pairs(monkeypatch):
    first, second = Library(b'first'), Library(b'second')
    contexts = iter([first, second])
    monkeypatch.setattr(_runtime.ctypes, 'CDLL', lambda path: next(contexts))
    left, right = logifos.NativeContext('left'), logifos.NativeContext('right')
    for _ in range(20):
        assert left.request_bytes(b'a\x00b') == b'first'
        assert right.request_bytes(b'\xff') == b'second'
    assert first.inputs == [b'a\x00b'] * 20
    assert second.inputs == [b'\xff'] * 20
    assert len(first.freed) == len(second.freed) == 20
    assert not first.live and not second.live


def test_bytes_context_and_path_are_mutually_exclusive(monkeypatch):
    context = bind(monkeypatch, Library())
    with pytest.raises(ValueError, match='context or library_path'):
        logifos.render({}, context=context, library_path='other')
