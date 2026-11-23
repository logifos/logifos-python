# logifos-python

The `logifos` Python package is a bootstrap package. It exposes
`logifos.render(formula, fmt="svg")`, but every call raises
`NotImplementedError`. It does not render formulas or return image bytes.
There is no native renderer, bundled native library, or native library loader
yet. The current wheel contains only Python code and package metadata.

The package requires Python 3.9 or later. To install from source, run these
commands in a Unix shell from the root of this checkout. They create a
temporary virtual environment and install the local package into it.

```sh
checkout="$(pwd)"
scratch="$(mktemp -d)"
python3 -m venv "$scratch/venv"
python="$scratch/venv/bin/python"
"$python" -m pip install .
```

To run the checks, continue in the same shell. Install the check tools, then
build a source distribution and a wheel. The build needs access to the Python
package index to install its build dependencies.

```sh
"$python" -m pip install build pytest
"$python" -m build --outdir "$scratch/dist"
```

Install the wheel and run the checks from outside the checkout. The
distribution check verifies the wheel contents, metadata, file hashes,
installed import location, and rendering refusal. The pytest check also
verifies that rendering raises `NotImplementedError`. These checks exercise
the bootstrap package; they do not test native rendering.

```sh
"$python" -m pip install --force-reinstall --no-deps "$scratch"/dist/*.whl
cd "$scratch"
"$python" -I "$checkout/tests/test_distribution.py" "$scratch"/dist/*.whl
"$python" -I -m pytest --import-mode=importlib -p no:cacheprovider "$checkout/tests/test_render.py"
```
