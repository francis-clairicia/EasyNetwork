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
    "sphinx.ext.autodoc",
    "sphinx.ext.duration",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    "sphinx_rtd_theme",
    "sphinx_tabs.tabs",
    "sphinx_toolbox.github",
    "sphinx_toolbox.sidebar_links",
    "sphinx_toolbox.more_autodoc.autoprotocol",
]

highlight_language = "python3"

manpages_url = "https://manpages.debian.org/{path}"

templates_path = []
exclude_patterns = ["_include"]


# -- sphinx.ext.autodoc configuration -------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html

autodoc_class_signature = "separated"
autodoc_member_order = "bysource"
autodoc_default_options = {
    "undoc-members": True,
    "member-order": "bysource",
    "no-value": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented_params"
autodoc_type_aliases = {
    "_Pickler": "pickle.Pickler",
    "_Unpickler": "pickle.Unpickler",
    "_Struct": "struct.Struct",
    "SocketAddress": "SocketAddress",
}
autodoc_inherit_docstrings = False
# autodoc_preserve_defaults = True

# -- sphinx.ext.intersphinx configuration ------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}


# -- sphinx.ext.napoleon configuration -------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html

napoleon_numpy_docstring = False


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
