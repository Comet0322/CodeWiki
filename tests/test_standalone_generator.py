import json
import pytest
from pathlib import Path
from codewiki.cli.html_generator import HTMLGenerator
from codewiki.cli.utils.errors import FileSystemError
from click.testing import CliRunner
from codewiki.cli.commands.html import html_command


@pytest.fixture
def tmp_docs(tmp_path):
    (tmp_path / "intro.md").write_text("# Introduction\nHello world.", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "details.md").write_text("# Details\nMore info.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def leaves():
    return [
        {"title": "Introduction", "file": "intro.md"},
        {"title": "Details", "file": "sub/details.md"},
    ]


@pytest.fixture
def module_tree():
    return {
        "0": {"title": "Introduction", "file": "intro.md", "components": ["_"], "children": {}},
        "1": {"title": "Details", "file": "sub/details.md", "components": ["_"], "children": {}},
    }


def test_generate_standalone_creates_file(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_generate_standalone_embeds_markdown(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    content = out.read_text(encoding="utf-8")
    assert "Hello world." in content
    assert "intro.md" in content
    assert "More info." in content
    assert "sub/details.md" in content


def test_generate_standalone_no_cdn_references(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    content = out.read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net" not in content


def test_generate_standalone_title_in_output(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="My Project Docs",
        input_dir=tmp_docs,
        leaves=leaves,
        module_tree=module_tree,
    )
    assert "My Project Docs" in out.read_text(encoding="utf-8")


def test_generate_standalone_missing_vendor_raises(tmp_path, tmp_docs, leaves, module_tree):
    gen = HTMLGenerator(vendor_dir=tmp_path / "no_vendor_here")
    out = tmp_path / "site" / "standalone.html"
    with pytest.raises(FileSystemError, match="vendor file missing"):
        gen.generate_standalone(
            output_path=out,
            title="Test",
            input_dir=tmp_docs,
            leaves=leaves,
            module_tree=module_tree,
        )


def test_generate_standalone_script_tag_in_markdown_is_escaped(tmp_path, module_tree):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "evil.md").write_text(
        "# Evil\n```html\n</script><script>alert(1)</script>\n```",
        encoding="utf-8",
    )
    leaves = [{"title": "Evil", "file": "evil.md"}]
    module_tree_evil = {
        "0": {"title": "Evil", "file": "evil.md", "components": ["_"], "children": {}}
    }
    gen = HTMLGenerator()
    out = tmp_path / "site" / "standalone.html"
    gen.generate_standalone(
        output_path=out,
        title="Test",
        input_dir=docs,
        leaves=leaves,
        module_tree=module_tree_evil,
    )
    content = out.read_text(encoding="utf-8")
    # After the MARKDOWN_FILES assignment line, raw </script> must not appear
    # before the next </script> that closes the outer script block
    script_block = content.split("const MARKDOWN_FILES =")[1].split("</script>")[0]
    assert "</script>" not in script_block


@pytest.fixture
def spec_and_docs(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    (docs / "intro.md").write_text("# Intro\nHello.", encoding="utf-8")

    spec = {
        "language": "English",
        "sections": [{"title": "Introduction", "file": "intro.md"}],
    }
    spec_path = docs / "doc_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    dep = {"analyzed_at": "2026-07-05", "commit_id": "abc1234", "total_components": 3}
    (docs / "dependency_graph.json").write_text(json.dumps(dep), encoding="utf-8")

    return tmp_path, docs, spec_path


def test_html_command_generates_standalone(spec_and_docs):
    root, docs, spec_path = spec_and_docs
    out_dir = root / "site"

    runner = CliRunner()
    result = runner.invoke(html_command, [
        "--spec", str(spec_path),
        "--input", str(docs),
        "--output", str(out_dir),
        "--title", "Test Docs",
    ])

    assert result.exit_code == 0, result.output
    assert (out_dir / "standalone.html").exists()
    content = (out_dir / "standalone.html").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net" not in content
    assert "Hello." in content
