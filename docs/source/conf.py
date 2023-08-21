# type: ignore
# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from __future__ import annotations

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
project = "EasyNetwork"
copyright = "2023, Francis Clairicia-Rose-Claire-Josephine"
author = "FrankySnow9"
release = "1.0.0rc4"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    # Built-in
    "sphinx.ext.autodoc",
    "sphinx.ext.duration",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    # Dependencies
    "enum_tools.autoenum",
    "sphinx_rtd_theme",
    "sphinx_tabs.tabs",
    "sphinx_toolbox.github",
    "sphinx_toolbox.sidebar_links",
    "sphinx_toolbox.more_autodoc.genericalias",
    "sphinx_toolbox.more_autodoc.autonamedtuple",
    "sphinx_toolbox.more_autodoc.autoprotocol",
    "sphinx_toolbox.more_autodoc.typevars",
]

highlight_language = "python3"

manpages_url = "https://manpages.debian.org/{path}"

templates_path = []
exclude_patterns = ["_include"]


# -- sphinx.ext.autodoc configuration -------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html

autoclass_content = "both"
autodoc_member_order = "bysource"
autodoc_default_options = {
    "undoc-members": None,
    "member-order": "bysource",
    "no-value": None,
    "show-inheritance": None,
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented_params"
autodoc_type_aliases = {
    "_typing_bz2.BZ2Compressor": "bz2.BZ2Compressor",
    "_typing_bz2.BZ2Decompressor": "bz2.BZ2Decompressor",
    "_typing_zlib._Compress": "zlib.Compress",
    "_typing_zlib._Decompress": "zlib.Decompress",
    "_typing_pickle.Pickler": "pickle.Pickler",
    "_typing_pickle.Unpickler": "pickle.Unpickler",
    "_typing_struct.Struct": "struct.Struct",
    "_typing_ssl.SSLContext": "ssl.SSLContext",
    "_socket._RetAddress": "typing.Any",
    "_socket.socket": "socket.socket",
}
autodoc_inherit_docstrings = False

# -- sphinx.ext.intersphinx configuration ------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "cbor2": ("https://cbor2.readthedocs.io/en/latest", None),
    "cryptography": ("https://cryptography.io/en/latest", None),
    "msgpack": ("https://msgpack-python.readthedocs.io/en/latest", None),
}


# -- sphinx.ext.napoleon configuration -------------------------------------------
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
html_static_path = []
