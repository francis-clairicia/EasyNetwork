# Development Environment

## Project Setup

### System Requirements

- CPython >= 3.11.0
- [PDM](https://pdm-project.org/latest/#installation) >= 2.22
- The [Rust Toolchain](https://rustup.rs/)

### Virtual environment

#### Option 1: Use an already created virtual environment via `pyenv-virtualenv`

```sh
# Create the virtual environment
pyenv virtualenv 3.11 easynetwork-3.11

# Set the local python (3.12 and upward are still needed for tox)
pyenv local "easynetwork-3.11" 3.12 3.13

# Tell pdm to use your virtualenv
pdm use -f $VIRTUAL_ENV
# -> Using Python interpreter: /path/to/.pyenv/versions/3.11.x/envs/easynetwork-3.11/bin/python3 (3.11)
```

#### Option 2: Let `pdm` create a `.venv` folder

0. For the `pyenv` users, set the local python :
```sh
pyenv local 3.11 3.12 3.13
```

1. Create the virtual environment :
```sh
# Creates the virtual environment ( in .venv directory )
pdm venv create 3.11

# Tell pdm to use this virtualenv
pdm use --venv in-project
```

2. Activate the virtual environment in the current shell using either :
    - the [manual way](https://docs.python.org/3.11/library/venv.html#how-venvs-work)
    - the [pdm venv CLI tool](https://pdm-project.org/latest/usage/venv/#activate-a-virtualenv)

### Installation

1. Install the project with its dependencies and development tools :
```sh
pdm install -G:all
```

2. If it is a clone of the `git` project, run :
```sh
pre-commit install
```

3. Check the installation :
```sh
# Run pre-commit hooks
pre-commit run --all-files

# Run mypy against all the project
tox run -q -f mypy
```

### Configure the IDE

#### Visual Studio Code

1. The recommended extensions are in [.vscode/extensions.json](.vscode/extensions.json)

2. Copy [.vscode/settings.example.json](.vscode/settings.example.json) to `.vscode/settings.json`

3. (Optional) To enable VS code's integrated testing tool, add this in your `settings.json`:
```json
{
    "python.testing.unittestEnabled": false,
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": [
        "-n",
        "auto"
    ]
}
```
> :warning: **NEVER** run all the test suite with VS code integrated testing tool ! There are 10_000+ tests.
