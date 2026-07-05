import json
import pytest
from pathlib import Path
from codewiki.cli.html_generator import HTMLGenerator
from codewiki.cli.utils.errors import FileSystemError


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
