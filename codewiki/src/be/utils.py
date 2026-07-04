import asyncio
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import List, Tuple
import logging


logger = logging.getLogger(__name__)


# PythonMonkey binds its JS engine to the thread that first imports it.
# Recording the main loop here lets validate_single_diagram marshal the call
# back via asyncio.run_coroutine_threadsafe so PythonMonkey finds its home loop.
_main_loop: "asyncio.AbstractEventLoop | None" = None
_main_loop_thread_ident: int | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop, _main_loop_thread_ident
    _main_loop = loop
    _main_loop_thread_ident = threading.get_ident()


# ------------------------------------------------------------
# ---------------------- Mermaid Validation -----------------
# ------------------------------------------------------------

_JS_BUNDLE = Path(__file__).parent / "js" / "parser.bundle.js"
_pm_mermaid_js = None  # lazy-loaded pythonmonkey JS function
_pm_broken = False     # permanent: once True, never retry pythonmonkey


def _init_pythonmonkey() -> bool:
    """Lazily load the bundled JS mermaid parser via pythonmonkey."""
    global _pm_mermaid_js, _pm_broken
    if _pm_broken:
        return False
    if _pm_mermaid_js is not None:
        return True
    try:
        import pythonmonkey as pm
        _pm_mermaid_js = pm.require(str(_JS_BUNDLE))
        return True
    except Exception:
        _pm_broken = True
        return False


async def _parse_via_pythonmonkey_js(src: str) -> dict:
    s = await _pm_mermaid_js(src)
    return json.loads(s)


async def validate_mermaid_diagrams(md_file_path: str, relative_path: str) -> str:
    """
    Validate all Mermaid diagrams in a markdown file.

    Returns:
        "All mermaid diagrams are syntax correct" if all diagrams are valid,
        otherwise an error message with details about invalid diagrams.
    """
    try:
        file_path = Path(md_file_path)
        if not file_path.exists():
            return f"Error: File '{md_file_path}' does not exist"

        content = file_path.read_text(encoding='utf-8')
        mermaid_blocks = extract_mermaid_blocks(content)

        if not mermaid_blocks:
            return "No mermaid diagrams found in the file"

        errors = []
        for i, (line_start, diagram_content) in enumerate(mermaid_blocks, 1):
            error_msg = await validate_single_diagram(diagram_content, i, line_start)
            if error_msg:
                errors.append("\n")
                errors.append(error_msg)

        if errors:
            return "Mermaid syntax errors found in file: " + relative_path + "\n" + "\n".join(errors)
        else:
            return "All mermaid diagrams in file: " + relative_path + " are syntax correct"

    except Exception as e:
        return f"Error processing file: {str(e)}"


def extract_mermaid_blocks(content: str) -> List[Tuple[int, str]]:
    """Extract all mermaid code blocks from markdown content.

    Returns:
        List of (line_number, diagram_content) tuples.
    """
    mermaid_blocks = []
    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if line == '```mermaid' or line.startswith('```mermaid'):
            start_line = i + 1
            diagram_lines = []
            i += 1
            while i < len(lines):
                if lines[i].strip() == '```':
                    break
                diagram_lines.append(lines[i])
                i += 1
            if diagram_lines:
                mermaid_blocks.append((start_line, '\n'.join(diagram_lines)))
        i += 1

    return mermaid_blocks


async def _try_pythonmonkey_parse(diagram_content: str) -> "str | None":
    """Attempt to parse via the embedded pythonmonkey JS engine.

    Returns the extracted parse-error message, "" on success, or None when
    pythonmonkey is unavailable so the caller can fall back to mermaid-py.
    """
    global _pm_mermaid_js, _pm_broken

    if not _init_pythonmonkey():
        return None

    old_stderr = sys.stderr
    sys.stderr = open(os.devnull, 'w')
    try:
        if (
            _main_loop is not None
            and _main_loop.is_running()
            and threading.get_ident() != _main_loop_thread_ident
        ):
            fut = asyncio.run_coroutine_threadsafe(
                _parse_via_pythonmonkey_js(diagram_content), _main_loop
            )
            await asyncio.wrap_future(fut)
        else:
            await _parse_via_pythonmonkey_js(diagram_content)
        return ""
    except Exception as e:
        error_str = str(e)
        if "cannot find a running Python event-loop" in error_str:
            _pm_broken = True  # engine state is unrecoverable — never retry
            return None
        match = re.search(r"Error:(.*?)(?=Stack Trace:|$)", error_str, re.DOTALL)
        if match:
            return match.group(0).strip()
        return None
    finally:
        sys.stderr.close()
        sys.stderr = old_stderr


def _parse_via_mermaid_py(diagram_content: str) -> str:
    """Validate via mermaid-py. Returns parse-error text, or "" if valid."""
    import mermaid as md
    try:
        md.Mermaid(diagram_content)
        return ""
    except Exception as e:
        return str(e)


async def validate_single_diagram(diagram_content: str, diagram_num: int, line_start: int) -> str:
    """Validate a single mermaid diagram. Returns error message or ""."""
    core_error = await _try_pythonmonkey_parse(diagram_content)
    if core_error is None:
        try:
            core_error = _parse_via_mermaid_py(diagram_content)
        except Exception as e:
            return f"  Diagram {diagram_num}: Exception during validation - {str(e)}"

    if not core_error:
        return ""

    line_match = re.search(r'line (\d+)', core_error)
    if line_match:
        error_line_in_diagram = int(line_match.group(1))
        actual_line_in_file = line_start + error_line_in_diagram
        newline = '\n'
        return f"Diagram {diagram_num}: Parse error on line {actual_line_in_file}:{newline}{newline.join(core_error.split(newline)[1:])}"
    return f"Diagram {diagram_num}: {core_error}"
