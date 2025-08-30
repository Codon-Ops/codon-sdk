import re
from codon_sdk.instrumentation.schemas.nodespec.version import __version__


def test_version():
    """
    Tests that the version is a string and conforms to the semantic versioning scheme.
    """
    assert isinstance(__version__, str)
    assert re.match(r"\d+\.\d+\.\d+", __version__)
