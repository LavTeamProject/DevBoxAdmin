# Python and Homebrew packages

## Python (Languages → Python)
- **Installed versions**: every Python found (uv, Homebrew, pyenv, python.org, the system one). “Make default” creates the links `python`, `python3`, `pip`, `pip3` in `~/.service-admin/bin` and (once) a block in `~/.zshrc` that puts this folder at the start of PATH. After that `python3` works **without a full path**; in open terminals run `hash -r` or open a new window. “Clear the choice” restores the PATH order.
- **Install a Python version**: 3.10–3.14 via uv (into your own folder, no administrator rights) or Homebrew (`python@X.Y`). Versions are installed side by side and change nothing by default.
- **Remove a version**: a button on versions installed by uv, Homebrew or pyenv. The default Python, the one the panel runs on, a python.org version and Apple's system Python cannot be removed.
- **pip packages**: pick a Python in the list, see, install (`pip install`) and remove packages. pip, setuptools and wheel are protected. For Pythons protected by PEP 668 (Homebrew) the panel suggests pipx or a virtual environment.

## Homebrew packages (Packages & services)
- Filters: **All installed**, **Installed by you**, **Dependencies**, **Unneeded**, CLI, Apps, Updates, Services.
- Each package shows where it comes from (manual / dependency / app), **what needs it** and how much space it takes. Sorting by size helps find the big ones.
- **Unneeded** — dependencies nothing needs any more. “Remove unneeded” runs `brew autoremove` after a confirmation with the list. A package needed by others has no “Uninstall” button.
- “Clean the cache and old versions” — `brew cleanup`.
