# type: ignore
# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from __future__ import annotations

import os.path
import sys
from importlib.metadata import version as _get_distribution_version

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
project = "EasyNetwork"
copyright = "2024, Francis Clairicia-Rose-Claire-Josephine"
author = "FrankySnow9"
release = _get_distribution_version("easynetwork")
version = ".".join(release.split(".")[:3])

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

sys.path.append(os.path.abspath(os.path.join(os.curdir, "_extensions")))

extensions = [
    # Built-in
    "sphinx.ext.autodoc",
    "sphinx.ext.duration",
    "sphinx.ext.ifconfig",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    # Dependencies
    "enum_tools.autoenum",
    "sphinx_rtd_theme",
    "sphinx_tabs.tabs",
    "sphinx_toolbox.collapse",
    "sphinx_toolbox.github",
    "sphinx_toolbox.sidebar_links",
    "sphinx_toolbox.more_autodoc.genericalias",
    "sphinx_toolbox.more_autodoc.autonamedtuple",
    "sphinx_toolbox.more_autodoc.autoprotocol",
    "sphinx_toolbox.more_autodoc.typevars",
    "sphinx_toolbox.more_autodoc.no_docstring",
    # Custom
    "sphinx_easynetwork",
]

highlight_language = "python3"

manpages_url = "https://manpages.debian.org/{path}"

templates_path = []
exclude_patterns = [
    "_include",
    "_extensions",
    "_static",
    "_build",  # <- Created by readthedocs.io
]

rst_prolog = """
.. ifconfig:: html_context.get('current_version') == 'latest'

   .. warning::

      This is the documentation for the latest unstable version.
"""


# -- sphinx.ext.autodoc configuration ----------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html

autoclass_content = "class"
autodoc_class_signature = "separated"
autodoc_member_order = "bysource"
autodoc_default_options = {
    "undoc-members": None,  # TODO: To remove when all the project have docstrings
    "member-order": "bysource",
    "no-value": None,
    "show-inheritance": None,
}
autodoc_preserve_defaults = True
autodoc_typehints = "both"
autodoc_typehints_description_target = "documented_params"
autodoc_type_aliases = {
    "_socket._RetAddress": "typing.Any",
    "_socket.socket": "socket.socket",
    "BZ2Compressor": "bz2.BZ2Compressor",
    "BZ2Decompressor": "bz2.BZ2Decompressor",
    "contextvars.Context": "contextvars.Context",
    "MemoryBIO": "ssl.MemoryBIO",
    "Pickler": "pickle.Pickler",
    "ReadableBuffer": "bytes | bytearray | memoryview | collections.abc.Buffer",
    "SSLContext": "ssl.SSLContext",
    "SSLObject": "ssl.SSLObject",
    "SSLSession": "ssl.SSLSession",
    "SSLSocket": "ssl.SSLSocket",
    "Struct": "struct.Struct",
    "Unpickler": "pickle.Unpickler",
    "WriteableBuffer": "bytearray | memoryview | collections.abc.Buffer",
    "ZLibCompress": "zlib.Compress",
    "ZLibDecompress": "zlib.Decompress",
}
autodoc_inherit_docstrings = False
autodoc_mock_imports = [
    "_typesched",
]

# -- sphinx.ext.intersphinx configuration ------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "cbor2": ("https://cbor2.readthedocs.io/en/stable", None),
    "msgpack": ("https://msgpack-python.readthedocs.io/en/stable", None),
}


# -- sphinx.ext.napoleon configuration ---------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html

napoleon_numpy_docstring = False
napoleon_preprocess_types = True
napoleon_use_param = True
napoleon_use_keyword = True
napoleon_custom_sections = [
    ("Common Parameters", "params_style"),
    ("Socket Parameters", "params_style"),
    ("Connection Parameters", "params_style"),
]


# -- sphinx.ext.todo configuration -------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/todo.html

todo_include_todos = True
todo_emit_warnings = False


# -- sphinx-tabs configuration -----------------------------------------------
# https://sphinx-tabs.readthedocs.io/en/latest/

sphinx_tabs_disable_tab_closing = True

# -- sphinx-toolbox.github configuration -------------------------------------
# https://sphinx-toolbox.readthedocs.io/en/stable/extensions/github.html

github_username = "francis-clairicia"
github_repository = "EasyNetwork"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = [
    "_static",
]
html_css_files = [
    "css/details.css",
    "css/rtfd.css",
]

# -- sphinx-rtd-theme configuration ------------------------------------------
# https://sphinx-rtd-theme.readthedocs.io/en/stable/configuring.html

html_theme_options = {
    "navigation_depth": -1,  # Unlimited
}


# -----------------------------------------------------------------------------


def setup(app) -> None:
    import warnings
    from sphinx import RemovedInNextVersionWarning

    warnings.filterwarnings("ignore", category=RemovedInNextVersionWarning, module="sphinx_toolbox.more_autodoc.autoprotocol")
