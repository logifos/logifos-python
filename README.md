# logifos-python

`logifos` is a bootstrap Python package for a future math formula renderer.
It can be installed and imported, but it cannot render formulas yet.

## Current runtime

The package exposes `logifos.render(formula, fmt="svg")`. Calling it raises
`NotImplementedError`, including when requesting SVG or PNG. It returns no
image bytes and does not validate or convert formula models.

There is no native engine, ctypes binding, library loader, or bundled native
library. The current wheel contains Python code and distribution metadata,
including the MIT license. Installing it does not build a Rust engine.

## Python support

The package requires Python 3.9 or later. The commands below were checked with
Python 3.10.12 on Linux. They verify installation and the rendering refusal;
they do not establish native rendering or native platform support.

## Install from this checkout

Run these commands in a Unix shell from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install build pytest
.venv/bin/python -m build
.venv/bin/python -m pip install --no-deps dist/*.whl
```

## Check the installed package

Run the consumer checks with isolated imports, so they use the installed wheel
and not the source tree:

```sh
.venv/bin/python -I tests/test_distribution.py dist/*.whl
.venv/bin/python -I -m pytest --import-mode=importlib tests/test_render.py
```

The distribution check verifies the wheel's files, metadata and recorded
hashes, checks that the import comes from the installed distribution, and
confirms that rendering raises `NotImplementedError`. The focused test checks
the rendering refusal too. Passing these checks means the bootstrap package
installs and refuses rendering as expected.

## Planned native runtime

The intended runtime will call the Rust engine's C ABI through Python's
`ctypes`. That binding is planned, along with formula transport, rendered
bytes and engine error handling. None of those operations is implemented in
this package today.

The planned library policy is to allow explicit library selection with a
separate context for each library. An invalid explicit path should fail
without falling back to a different library or changing the process-wide
library choice. Native results should be released through the same context
that allocated them. There is no library-path option or native context API
to use yet.

Bundling native libraries in platform wheels and qualifying those wheels
are later packaging work. The current Python-only wheel is not evidence of
native platform coverage. Native loading, wheel availability and release
instructions will need verification before they can be documented as
supported behavior.
