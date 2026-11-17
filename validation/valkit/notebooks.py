"""
Execute a parameterised notebook headlessly.

    python -m validation.valkit.notebooks validation/units/02_lifting_accuracy/lifting_accuracy.ipynb \
        --param DATASET=prrs --param RUN_ID=latest --out validation/outputs/<run_id>/notebooks/

The notebook's first code cell tagged `parameters` holds defaults; each
--param NAME=VALUE is appended to that cell as a Python assignment, the way
papermill does it, so the notebook also works interactively with its defaults.
Values are parsed as Python literals when possible, otherwise kept as strings.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List, Optional

import nbformat
from nbclient import NotebookClient


def inject_parameters(nb, params: Dict[str, object]):
    for cell in nb.cells:
        if cell.cell_type == "code" and "parameters" in cell.metadata.get("tags", []):
            lines = [f"{name} = {value!r}" for name, value in params.items()]
            cell.source = cell.source.rstrip() + "\n\n# injected by validation.valkit.notebooks\n" + "\n".join(lines) + "\n"
            return nb
    raise ValueError("notebook has no code cell tagged 'parameters'")


def execute(notebook: Path, out: Path, params: Optional[Dict[str, object]] = None, timeout: int = 3600) -> Path:
    nb = nbformat.read(notebook, as_version=4)
    if params:
        inject_parameters(nb, params)
    client = NotebookClient(nb, timeout=timeout, kernel_name="python3",
                            resources={"metadata": {"path": str(notebook.parent)}})
    client.execute()
    out.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, out)
    return out


def _literal(text: str):
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notebook", type=Path)
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--out", type=Path, required=True, help="Executed notebook path (.ipynb) or directory")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    params = {}
    for item in args.param:
        name, _, value = item.partition("=")
        params[name.strip()] = _literal(value.strip())
    out = args.out
    if out.suffix != ".ipynb":
        suffix = "_".join(str(v) for v in params.values()) or "run"
        out = out / f"{args.notebook.stem}_{suffix}.ipynb"
    executed = execute(args.notebook, out, params, args.timeout)
    print(executed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
