"""Installed-package transport checks against a caller-selected native library."""

import base64
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

import logifos
from logifos import _runtime


@pytest.fixture
def library_path():
    selected = os.environ.get('LOGIFOS_TEST_LIBRARY')
    if not selected:
        pytest.skip('set LOGIFOS_TEST_LIBRARY to exercise native transport')
    return Path(selected).resolve(strict=True)


@pytest.fixture
def native(library_path):
    return logifos.NativeContext(library_path)


@pytest.fixture
def contract():
    # A fresh descriptor exercises envelope validation, not model qualification.
    return {'origin': 'urn:test:formula', 'revision': 'a' * 40,
            'schema_path': 'formula.schema.json', 'sha256': 'b' * 64}


def test_negotiate_native_capabilities(native):
    assert (native.abi_version, native.schema_version, native.features & 7) == (1, 1, 3)
    assert native.engine_version
    result = logifos.negotiate(context=native)
    assert result['kind'] == 'capabilities'
    assert result['implemented_operations'] == result['outputs'] == []
    assert result['formula_contract'] is result['syntax_contract'] is None
    assert result['limits']['request_bytes'] == 8388608


@pytest.mark.parametrize('payload,code', [(b'', 'INVALID_JSON'), (b'\xff', 'INVALID_UTF8'),
                                        (b'{}\x00', 'INVALID_JSON'),
                                        (b'{"op":"a","op":"b"}', 'INVALID_JSON')])
def test_bytes_native_preserves_exact_length_and_refusal(native, payload, code):
    with pytest.raises(logifos.InvalidRequestError) as caught:
        native.request(payload)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (code, 'decode', '')


def test_bytes_native_raw_envelope_and_input_independence(native):
    payload = bytearray(b'{"abi_version":1,"schema_version":1,"op":"negotiate"}')
    original = bytes(payload)
    reply = native.request_bytes(memoryview(payload))
    assert payload == original
    payload[:] = b'x' * len(payload)
    assert type(reply) is bytes and json.loads(reply)['ok'] is True
    assert not reply.endswith(b'\x00')


def test_unicode_native_counts_utf8_bytes(native):
    request = {'abi_version': 1, 'schema_version': 1, 'op': 'parse', 'format': 'mathml',
               'source': 'αe\u0301𝛽', 'options': {'limits': {'source_bytes': 8}}}
    assert len(request['source']) == 4 and len(request['source'].encode('utf-8')) == 9
    with pytest.raises(logifos.ResourceLimitError) as caught:
        native.request(request)
    assert (caught.value.code, caught.value.path) == ('RESOURCE_LIMIT', '/source')
    request['options']['limits']['source_bytes'] = 9
    with pytest.raises(logifos.OperationNotImplementedError) as caught:
        native.request(request)
    assert caught.value.path == '/op'


@pytest.mark.parametrize('fmt,exception,code,path', [
    ('svg', logifos.OperationNotImplementedError, 'NOT_IMPLEMENTED', '/op'),
    ('png', logifos.UnsupportedOutputError, 'UNSUPPORTED_OUTPUT', '/output'),
])
def test_refusal_native_render_details(native, contract, fmt, exception, code, path):
    with pytest.raises(exception) as caught:
        logifos.render({'opaque': 'α'}, fmt, context=native, formula_contract=contract)
    error = caught.value
    assert (error.code, error.path, error.stage) == (code, path, 'contract')
    assert error.message and error.code in str(error)


def test_refusal_native_missing_contract_is_not_invented(native):
    with pytest.raises(logifos.InvalidRequestError) as caught:
        native.render({})
    assert caught.value.path == '/formula_contract'


def test_bytes_native_font_identity_and_per_call_options(native):
    data = bytearray(b'\x00\xff\x01fresh-resource')
    font = logifos.font_resource('math', data, face_index=2)
    assert base64.b64decode(font['bytes_base64'], validate=True) == data
    assert font['sha256'] == hashlib.sha256(data).hexdigest()
    assert font['face_index'] == 2
    options = {'fonts': [font], 'fallback_order': ['math'], 'color': '#102030'}
    before = json.dumps(options)
    with pytest.raises(logifos.OperationNotImplementedError) as caught:
        native.negotiate(options=options)
    assert caught.value.path == '/options/fonts'
    assert json.dumps(options) == before
    assert native.negotiate()['limits']['source_bytes'] == 1048576
    assert native.negotiate(options={'limits': {'source_bytes': 4}})['limits']['source_bytes'] == 4
    assert native.negotiate()['limits']['source_bytes'] == 1048576
    with pytest.raises(logifos.InvalidRequestError) as caught:
        native.negotiate(options={'unknown': True})
    assert caught.value.code == 'UNKNOWN_OPTION'


def test_independent_contexts_native_libraries(library_path, tmp_path, monkeypatch):
    copy = tmp_path / library_path.name
    shutil.copyfile(library_path, copy)
    left, right = logifos.NativeContext(library_path), logifos.NativeContext(copy)
    assert left._library._handle != right._library._handle
    assert left._free is not right._free
    monkeypatch.setenv('LOGIFOS_LIBRARY_PATH', str(copy))
    with pytest.raises(logifos.NativeLibraryError):
        logifos.NativeContext(tmp_path / 'missing-library')
    assert left.negotiate() == right.negotiate()
    assert logifos.negotiate(library_path=library_path) == logifos.negotiate()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda context: context.negotiate()['kind'] == 'capabilities',
                            [left, right] * 20))


def test_repeated_cleanup_native_success_refusal_and_copy_failure(native, contract, monkeypatch):
    original_free = native._free
    freed = []

    def record_free(buffer):
        freed.append((ctypes.cast(buffer.ptr, ctypes.c_void_p).value, buffer.len))
        original_free(buffer)

    monkeypatch.setattr(native, '_free', record_free)
    for _ in range(200):
        assert native.negotiate()['kind'] == 'capabilities'
        with pytest.raises(logifos.OperationNotImplementedError):
            native.render({}, formula_contract=contract)
    assert len(freed) == 400 and all(ptr and size for ptr, size in freed)
    with monkeypatch.context() as patch:
        def copy_failure(*args):
            raise MemoryError('copy failed')
        patch.setattr(_runtime.ctypes, 'string_at', copy_failure)
        with pytest.raises(MemoryError):
            native.negotiate()
    assert len(freed) == 401
    assert native.negotiate()['kind'] == 'capabilities'
    assert len(freed) == 402
