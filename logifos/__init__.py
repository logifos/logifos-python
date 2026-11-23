"""Python runtime for the logifos math formula renderer.

Formula models in (the plurimath common model), SVG bytes out, through
the logifos Rust engine. The engine call lands with the engine phase;
the boundary refuses typed until then.
"""


def render(formula, fmt: str = "svg") -> bytes:
    raise NotImplementedError(
        f"the logifos engine boundary lands in the engine phase (got {fmt})"
    )
