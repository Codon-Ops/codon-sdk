import importlib
import warnings

from importlib import metadata as importlib_metadata


def _reload_langgraph(monkeypatch, version_value, *, silence=False):
    monkeypatch.setattr(importlib_metadata, "version", lambda name: version_value)
    if silence:
        monkeypatch.setenv("CODON_LANGGRAPH_DEPRECATION_SILENCE", "1")
    else:
        monkeypatch.delenv("CODON_LANGGRAPH_DEPRECATION_SILENCE", raising=False)
    module = importlib.import_module("codon.instrumentation.langgraph")
    return importlib.reload(module)


def _has_deprecation_warning(captured):
    for warning in captured:
        if issubclass(warning.category, DeprecationWarning) and "LangGraph <1.0" in str(
            warning.message
        ):
            return True
    return False


def test_deprecation_warning_emitted(monkeypatch):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        _reload_langgraph(monkeypatch, "0.3.2")
    assert _has_deprecation_warning(captured)


def test_deprecation_warning_suppressed(monkeypatch):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        _reload_langgraph(monkeypatch, "0.3.2", silence=True)
    assert not _has_deprecation_warning(captured)


def test_no_warning_for_v1(monkeypatch):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        _reload_langgraph(monkeypatch, "1.0.0")
    assert not _has_deprecation_warning(captured)
