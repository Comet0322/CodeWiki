"""
Single source of truth for language support.
All extension lists in the codebase should derive from here.
"""

# Language name → extensions that codewiki can parse
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "Python":     [".py"],
    "Java":       [".java"],
    "JavaScript": [".js", ".jsx", ".mjs", ".cjs"],
    "TypeScript": [".ts", ".tsx"],
    "C":          [".c", ".h"],
    "C++":        [".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx"],
    "C#":         [".cs"],
    "PHP":        [".php", ".phtml", ".inc"],
    "Kotlin":     [".kt", ".kts"],
    "VB6":        [".bas", ".frm", ".cls"],
}

# Flat set — use wherever you only need membership testing
SUPPORTED_EXTENSIONS: set[str] = {
    ext for exts in LANGUAGE_EXTENSIONS.values() for ext in exts
}
