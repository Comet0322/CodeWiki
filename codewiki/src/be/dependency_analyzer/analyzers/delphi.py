import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

from tree_sitter import Parser, Language
import tree_sitter_pascal

from codewiki.src.be.dependency_analyzer.models.core import Node, CallRelationship

logger = logging.getLogger(__name__)

_PROC_KEYWORD_TYPES = {
    "kFunction",
    "kProcedure",
    "kConstructor",
    "kDestructor",
}

_COMPONENT_TYPE = {
    "kFunction": "function",
    "kProcedure": "procedure",
    "kConstructor": "constructor",
    "kDestructor": "destructor",
}

_FILE_COMPONENT_TYPE = {
    ".pas": "unit",
    ".dpr": "program",
    ".dpk": "package",
}


class TreeSitterDelphiAnalyzer:
    def __init__(self, file_path: str, content: str, repo_path: Optional[str] = None):
        self.file_path = Path(file_path)
        self.content = content
        self.repo_path = repo_path or ""
        self.nodes: List[Node] = []
        self.call_relationships: List[CallRelationship] = []
        self._analyze()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _get_relative_path(self) -> str:
        if self.repo_path:
            try:
                return os.path.relpath(str(self.file_path), self.repo_path)
            except ValueError:
                return str(self.file_path)
        return str(self.file_path)

    def _get_file_type(self) -> str:
        return _FILE_COMPONENT_TYPE.get(self.file_path.suffix.lower(), "unit")

    # ------------------------------------------------------------------
    # Top-level analysis
    # ------------------------------------------------------------------

    def _analyze(self):
        try:
            lang = Language(tree_sitter_pascal.language())
            parser = Parser(lang)
            tree = parser.parse(bytes(self.content, "utf8"))
            root = tree.root_node
            lines = self.content.splitlines()
            rel_path = self._get_relative_path()
            file_type = self._get_file_type()

            top_node = next(
                (c for c in root.children if c.type in ("unit", "program", "package")),
                None,
            )
            if top_node is None:
                logger.warning(f"No unit/program/package found in {self.file_path}")
                return

            module_name = self._extract_module_name(top_node)
            file_node_id = f"{rel_path}::{module_name}"

            self.nodes.append(Node(
                id=file_node_id,
                name=module_name,
                component_type=file_type,
                file_path=str(self.file_path),
                relative_path=rel_path,
                source_code=self.content[:500],
                start_line=1,
                end_line=len(lines),
                has_docstring=False,
                docstring="",
                parameters=None,
                node_type=file_type,
                base_classes=None,
                class_name=None,
                display_name=f"{file_type} {module_name}",
                component_id=file_node_id,
                language="delphi",
                qualified_name=module_name,
            ))

            self._extract_type_declarations(top_node, rel_path, module_name, lines)
            self._extract_implementations(top_node, rel_path, module_name, lines)

            logger.debug(
                f"Delphi analysis complete for {self.file_path}: "
                f"{len(self.nodes)} nodes, {len(self.call_relationships)} relationships"
            )
        except Exception as e:
            logger.error(f"Error analyzing Delphi file {self.file_path}: {e}", exc_info=True)

    def _extract_module_name(self, top_node) -> str:
        name_node = next((c for c in top_node.children if c.type == "moduleName"), None)
        if name_node:
            ident = next((c for c in name_node.children if c.type == "identifier"), None)
            if ident:
                return ident.text.decode()
        return self.file_path.stem

    # ------------------------------------------------------------------
    # Type declarations (classes / interfaces)
    # ------------------------------------------------------------------

    def _extract_type_declarations(self, top_node, rel_path: str, module_name: str, lines):
        for node in self._iter_descendants(top_node):
            if node.type != "declTypes":
                continue
            for decl_type in node.children:
                if decl_type.type != "declType":
                    continue
                ident = next((c for c in decl_type.children if c.type == "identifier"), None)
                if not ident:
                    continue
                class_name = ident.text.decode()

                class_def = next(
                    (c for c in decl_type.children if c.type in ("declClass", "declIntf")),
                    None,
                )
                if not class_def:
                    continue

                base_classes = [
                    c.text.decode().strip()
                    for c in class_def.children
                    if c.type == "typeref" and c.text.decode().strip()
                ]

                node_type = "class" if class_def.type == "declClass" else "interface"
                component_id = f"{rel_path}::{class_name}"
                start_line = decl_type.start_point[0] + 1
                end_line = decl_type.end_point[0] + 1
                source = "\n".join(lines[decl_type.start_point[0]:decl_type.end_point[0] + 1])

                self.nodes.append(Node(
                    id=component_id,
                    name=class_name,
                    component_type=node_type,
                    file_path=str(self.file_path),
                    relative_path=rel_path,
                    source_code=source,
                    start_line=start_line,
                    end_line=end_line,
                    has_docstring=False,
                    docstring="",
                    parameters=None,
                    node_type=node_type,
                    base_classes=base_classes or None,
                    class_name=module_name,
                    display_name=f"{node_type} {class_name}",
                    component_id=component_id,
                    language="delphi",
                    qualified_name=f"{module_name}.{class_name}",
                ))

    # ------------------------------------------------------------------
    # Procedure / function implementations
    # ------------------------------------------------------------------

    def _extract_implementations(self, top_node, rel_path: str, module_name: str, lines):
        for node in self._iter_descendants(top_node):
            if node.type == "defProc":
                self._extract_def_proc(node, rel_path, module_name, lines)

    def _extract_def_proc(self, def_proc_node, rel_path: str, module_name: str, lines):
        decl_proc = next((c for c in def_proc_node.children if c.type == "declProc"), None)
        if not decl_proc:
            return

        keyword_node = next((c for c in decl_proc.children if c.type in _PROC_KEYWORD_TYPES), None)
        component_type = _COMPONENT_TYPE.get(keyword_node.type, "procedure") if keyword_node else "procedure"

        # Method (TMyClass.Method) vs standalone (StandaloneProc)
        generic_dot = next((c for c in decl_proc.children if c.type == "genericDot"), None)
        bare_ident = next((c for c in decl_proc.children if c.type == "identifier"), None)

        if generic_dot:
            idents = [c for c in generic_dot.children if c.type == "identifier"]
            if len(idents) >= 2:
                class_name = idents[0].text.decode()
                method_name = idents[-1].text.decode()
            elif len(idents) == 1:
                class_name = None
                method_name = idents[0].text.decode()
            else:
                return
            qualified = f"{class_name}.{method_name}" if class_name else method_name
            display_name = f"{component_type} {qualified}"
        elif bare_ident:
            class_name = None
            method_name = bare_ident.text.decode()
            qualified = method_name
            display_name = f"{component_type} {method_name}"
        else:
            return

        params = []
        decl_args = next((c for c in decl_proc.children if c.type == "declArgs"), None)
        if decl_args:
            for arg in decl_args.children:
                if arg.type == "declArg":
                    arg_ident = next((c for c in arg.children if c.type == "identifier"), None)
                    if arg_ident:
                        params.append(arg_ident.text.decode())

        start_line = def_proc_node.start_point[0] + 1
        end_line = def_proc_node.end_point[0] + 1
        source = "\n".join(lines[def_proc_node.start_point[0]:def_proc_node.end_point[0] + 1])

        component_id = f"{rel_path}::{qualified}"

        self.nodes.append(Node(
            id=component_id,
            name=qualified,
            component_type=component_type,
            file_path=str(self.file_path),
            relative_path=rel_path,
            source_code=source,
            start_line=start_line,
            end_line=end_line,
            has_docstring=False,
            docstring="",
            parameters=params,
            node_type=component_type,
            base_classes=None,
            class_name=class_name,
            display_name=display_name,
            component_id=component_id,
            language="delphi",
            qualified_name=qualified,
        ))

        block = next((c for c in def_proc_node.children if c.type == "block"), None)
        if block:
            self._walk_calls(block, component_id)

    # ------------------------------------------------------------------
    # Call extraction
    # ------------------------------------------------------------------

    def _walk_calls(self, node, caller_id: str):
        """Recursively walk a syntax node, emitting call relationships."""
        if node.type == "exprCall":
            callee = self._callee_from_expr_call(node)
            if callee:
                self.call_relationships.append(CallRelationship(
                    caller=caller_id,
                    callee=callee,
                    call_line=node.start_point[0] + 1,
                    is_resolved=False,
                ))
            # Don't recurse into args to avoid double-counting nested calls here
            return
        elif node.type == "exprDot":
            # Standalone member access in a statement (no parentheses)
            idents = [c for c in node.children if c.type == "identifier"]
            if len(idents) >= 2:
                self.call_relationships.append(CallRelationship(
                    caller=caller_id,
                    callee=f"{idents[0].text.decode()}.{idents[-1].text.decode()}",
                    call_line=node.start_point[0] + 1,
                    is_resolved=False,
                ))
            return

        for child in node.children:
            self._walk_calls(child, caller_id)

    def _callee_from_expr_call(self, node) -> Optional[str]:
        first = node.children[0] if node.children else None
        if first is None:
            return None
        if first.type == "identifier":
            return first.text.decode()
        if first.type == "exprDot":
            idents = [c for c in first.children if c.type == "identifier"]
            if len(idents) >= 2:
                return f"{idents[0].text.decode()}.{idents[-1].text.decode()}"
            if len(idents) == 1:
                return idents[0].text.decode()
        return None

    def _iter_descendants(self, node):
        for child in node.children:
            yield child
            yield from self._iter_descendants(child)


def analyze_delphi_file(
    file_path: str,
    content: str,
    repo_path: Optional[str] = None,
) -> Tuple[List[Node], List[CallRelationship]]:
    analyzer = TreeSitterDelphiAnalyzer(file_path, content, repo_path)
    return analyzer.nodes, analyzer.call_relationships
