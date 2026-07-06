import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

from tree_sitter import Parser, Language
import tree_sitter_vb6

from codewiki.src.be.dependency_analyzer.models.core import Node, CallRelationship

logger = logging.getLogger(__name__)

_DECLARATION_TYPES = {
    "sub_declaration",
    "function_declaration",
    "property_get_declaration",
    "property_let_declaration",
    "property_set_declaration",
}

_COMPONENT_TYPE = {
    "sub_declaration": "function",
    "function_declaration": "function",
    "property_get_declaration": "property",
    "property_let_declaration": "property",
    "property_set_declaration": "property",
}

_FILE_TYPE = {
    ".bas": "module",
    ".frm": "form",
    ".cls": "class",
}


class TreeSitterVB6Analyzer:
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
        return _FILE_TYPE.get(self.file_path.suffix.lower(), "module")

    # ------------------------------------------------------------------
    # Top-level analysis
    # ------------------------------------------------------------------

    def _analyze(self):
        try:
            lang = Language(tree_sitter_vb6.language())
            parser = Parser(lang)
            tree = parser.parse(bytes(self.content, "utf8"))
            root = tree.root_node
            lines = self.content.splitlines()

            module_name = self._extract_module_name(root)
            file_type = self._get_file_type()
            rel_path = self._get_relative_path()

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
                language="vb6",
                qualified_name=module_name,
            ))

            module_body = next((c for c in root.children if c.type == "module_body"), None)
            if module_body:
                self._extract_declarations(module_body, lines, module_name, rel_path)

            logger.debug(
                f"VB6 analysis complete for {self.file_path}: "
                f"{len(self.nodes)} nodes, {len(self.call_relationships)} relationships"
            )
        except Exception as e:
            logger.error(f"Error analyzing VB6 file {self.file_path}: {e}", exc_info=True)

    def _extract_module_name(self, root) -> str:
        for child in root.children:
            if child.type == "attribute_statement":
                dotted = next((c for c in child.children if c.type == "dotted_name"), None)
                if dotted and dotted.text.decode().strip() == "VB_Name":
                    literal = next((c for c in child.children if c.type == "literal"), None)
                    if literal:
                        val = literal.text.decode().strip().strip('"')
                        if val:
                            return val
        return self.file_path.stem

    # ------------------------------------------------------------------
    # Declaration extraction
    # ------------------------------------------------------------------

    def _extract_declarations(self, module_body, lines, module_name: str, rel_path: str):
        for child in module_body.children:
            if child.type not in _DECLARATION_TYPES:
                continue

            name_node = next((c for c in child.children if c.type == "identifier"), None)
            if not name_node:
                continue

            proc_name = name_node.text.decode()
            component_type = _COMPONENT_TYPE[child.type]

            if child.type == "property_get_declaration":
                member_name = f"{module_name}.{proc_name}_Get"
                display_name = f"property {proc_name} (Get)"
            elif child.type == "property_let_declaration":
                member_name = f"{module_name}.{proc_name}_Let"
                display_name = f"property {proc_name} (Let)"
            elif child.type == "property_set_declaration":
                member_name = f"{module_name}.{proc_name}_Set"
                display_name = f"property {proc_name} (Set)"
            else:
                member_name = f"{module_name}.{proc_name}"
                display_name = f"{component_type} {proc_name}"

            component_id = f"{rel_path}::{member_name}"

            param_list = next((c for c in child.children if c.type == "parameter_list"), None)
            params = []
            if param_list:
                for param in param_list.children:
                    if param.type == "parameter":
                        ident = next((c for c in param.children if c.type == "identifier"), None)
                        if ident:
                            params.append(ident.text.decode())

            start_line = child.start_point[0] + 1
            end_line = child.end_point[0] + 1
            source = "\n".join(lines[child.start_point[0] : child.end_point[0] + 1])

            self.nodes.append(Node(
                id=component_id,
                name=member_name,
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
                class_name=module_name,
                display_name=display_name,
                component_id=component_id,
                language="vb6",
                qualified_name=member_name,
            ))

            block = next((c for c in child.children if c.type == "block"), None)
            if block:
                self._walk_calls(block, component_id)

    # ------------------------------------------------------------------
    # Call extraction
    # ------------------------------------------------------------------

    def _walk_calls(self, node, caller_id: str):
        """Recursively walk a syntax node, emitting call relationships."""
        if node.type == "call_statement":
            callee = self._callee_from_call_statement(node)
            if callee:
                self.call_relationships.append(CallRelationship(
                    caller=caller_id,
                    callee=callee,
                    call_line=node.start_point[0] + 1,
                    is_resolved=False,
                ))
        elif node.type == "set_statement":
            # Set obj = New MyClass
            for desc in self._iter_descendants(node):
                if desc.type == "new_expression":
                    ident = next((c for c in desc.children if c.type == "identifier"), None)
                    if ident:
                        self.call_relationships.append(CallRelationship(
                            caller=caller_id,
                            callee=ident.text.decode(),
                            call_line=node.start_point[0] + 1,
                            is_resolved=False,
                        ))
                    break
        elif node.type == "dim_statement":
            # Dim obj As New MyClass  — New keyword only detectable in raw text
            for declarator in node.children:
                if declarator.type != "variable_declarator":
                    continue
                if " New " not in declarator.text.decode():
                    continue
                type_expr = next((c for c in declarator.children if c.type == "type_expression"), None)
                if type_expr:
                    ident = next((c for c in type_expr.children if c.type == "identifier"), None)
                    if ident:
                        self.call_relationships.append(CallRelationship(
                            caller=caller_id,
                            callee=ident.text.decode(),
                            call_line=node.start_point[0] + 1,
                            is_resolved=False,
                        ))

        for child in node.children:
            self._walk_calls(child, caller_id)

    def _callee_from_call_statement(self, node) -> Optional[str]:
        """Extract the callee from a call_statement node.

        Patterns handled:
          Call MySub()          → expression → call_expression → identifier
          Call obj.Method(x)    → expression → index_expression → member_access_expression
          MySub arg             → identifier (bare name call)
          obj.Method arg        → identifier + argument_list_no_parens starting with '.'
          Form1.Show            → same as above
        """
        expr = next((c for c in node.children if c.type == "expression"), None)
        if expr:
            return self._callee_from_expression(expr)

        # logger.Write val → member_access_expression + argument_list_no_parens
        member_access = next((c for c in node.children if c.type == "member_access_expression"), None)
        if member_access:
            obj_expr = next((c for c in member_access.children if c.type == "expression"), None)
            method_ident = next((c for c in member_access.children if c.type == "identifier"), None)
            if obj_expr and method_ident:
                obj_ident = next((c for c in obj_expr.children if c.type == "identifier"), None)
                if obj_ident:
                    return f"{obj_ident.text.decode()}.{method_ident.text.decode()}"
            if method_ident:
                return method_ident.text.decode()

        ident = next((c for c in node.children if c.type == "identifier"), None)
        if not ident:
            return None
        obj_name = ident.text.decode()

        arg_list = next((c for c in node.children if c.type == "argument_list_no_parens"), None)
        if arg_list and arg_list.text.decode().strip().startswith("."):
            method = self._method_from_with_access(arg_list)
            if method:
                return f"{obj_name}.{method}"

        return obj_name

    def _callee_from_expression(self, expr_node) -> Optional[str]:
        """Extract callee name from an expression node."""
        for child in expr_node.children:
            if child.type == "call_expression":
                # Call MySub() → call_expression → expression → identifier
                # Call obj.Method() → call_expression → expression → member_access_expression
                inner = next((c for c in child.children if c.type == "expression"), None)
                if inner:
                    member = next((c for c in inner.children if c.type == "member_access_expression"), None)
                    if member:
                        obj_expr = next((c for c in member.children if c.type == "expression"), None)
                        method_ident = next((c for c in member.children if c.type == "identifier"), None)
                        if obj_expr and method_ident:
                            obj_ident = next((c for c in obj_expr.children if c.type == "identifier"), None)
                            if obj_ident:
                                return f"{obj_ident.text.decode()}.{method_ident.text.decode()}"
                    ident = next((c for c in inner.children if c.type == "identifier"), None)
                    if ident:
                        return ident.text.decode()

            elif child.type == "index_expression":
                # Call obj.Method(args) → index_expression → member_access_expression
                inner = next((c for c in child.children if c.type == "expression"), None)
                if inner:
                    member = next((c for c in inner.children if c.type == "member_access_expression"), None)
                    if member:
                        obj_expr = next((c for c in member.children if c.type == "expression"), None)
                        method_ident = next((c for c in member.children if c.type == "identifier"), None)
                        if obj_expr and method_ident:
                            obj_ident = next((c for c in obj_expr.children if c.type == "identifier"), None)
                            if obj_ident:
                                return f"{obj_ident.text.decode()}.{method_ident.text.decode()}"
                        if method_ident:
                            return method_ident.text.decode()
                    # Bare function call in expression: x = Func(args)
                    bare_ident = next((c for c in inner.children if c.type == "identifier"), None)
                    if bare_ident:
                        return bare_ident.text.decode()

        return None

    def _method_from_with_access(self, arg_list_node) -> Optional[str]:
        """Find method name inside an argument_list_no_parens that starts with '.'."""
        for node in self._iter_descendants(arg_list_node):
            if node.type == "with_member_access_expression":
                ident = next((c for c in node.children if c.type == "identifier"), None)
                if ident:
                    return ident.text.decode()
        return None

    def _iter_descendants(self, node):
        for child in node.children:
            yield child
            yield from self._iter_descendants(child)


def analyze_vb6_file(
    file_path: str,
    content: str,
    repo_path: Optional[str] = None,
) -> Tuple[List[Node], List[CallRelationship]]:
    analyzer = TreeSitterVB6Analyzer(file_path, content, repo_path)
    return analyzer.nodes, analyzer.call_relationships
