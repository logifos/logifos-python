"""Length-delimited native transport for the Logifos engine."""

from ._runtime import (
    ContractError,
    EngineError,
    FontError,
    InvalidRequestError,
    LogifosError,
    NativeContext,
    NativeLibraryError,
    OperationNotImplementedError,
    ProtocolError,
    ResourceLimitError,
    TransportError,
    UnsupportedOutputError,
    font_resource,
)


def _context(context, library_path):
    if context is not None:
        if library_path is not None:
            raise ValueError("choose context or library_path")
        if not isinstance(context, NativeContext):
            raise TypeError("context must be a NativeContext")
        return context
    return NativeContext(library_path)


def negotiate(*, context=None, library_path=None, options=None):
    """Return capabilities from the selected native library."""
    return _context(context, library_path).negotiate(options=options)


def render(formula, fmt="svg", *, formula_contract=None, options=None,
           context=None, library_path=None) -> bytes:
    """Send a render request; native refusals raise EngineError subclasses."""
    return _context(context, library_path).render(
        formula, fmt, formula_contract=formula_contract, options=options
    )
