"""
HTML generator for GitHub Pages documentation viewer.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any

from codewiki.cli.utils.errors import FileSystemError
from codewiki.cli.utils.fs import safe_write, safe_read


class HTMLGenerator:
    """
    Generates static HTML documentation viewer for GitHub Pages.
    
    Creates a self-contained index.html with embedded styles, scripts,
    and configuration for client-side markdown rendering.
    """
    
    def __init__(self, template_dir: Optional[Path] = None):
        """
        Initialize HTML generator.
        
        Args:
            template_dir: Path to template directory (default: package templates)
        """
        if template_dir is None:
            # Use package templates
            template_dir = Path(__file__).parent.parent / "templates" / "github_pages"
        
        self.template_dir = Path(template_dir)
        
    
    def load_module_tree(self, docs_dir: Path) -> Dict[str, Any]:
        """
        Load module tree from documentation directory.
        
        Args:
            docs_dir: Documentation directory path
            
        Returns:
            Module tree structure
        """
        module_tree_path = docs_dir / "module_tree.json"
        if not module_tree_path.exists():
            # Fallback to a simple structure
            return {
                "Overview": {
                    "description": "Repository overview",
                    "components": [],
                    "children": {}
                }
            }
        
        try:
            content = safe_read(module_tree_path)
            return json.loads(content)
        except Exception as e:
            raise FileSystemError(f"Failed to load module tree: {e}")
    
    def load_metadata(self, docs_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Load metadata from documentation directory.
        
        Args:
            docs_dir: Documentation directory path
            
        Returns:
            Metadata dictionary or None if not found
        """
        metadata_path = docs_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        
        try:
            content = safe_read(metadata_path)
            return json.loads(content)
        except Exception:
            # Non-critical, return None
            return None
            
    def generate(
        self,
        output_path: Path,
        title: str,
        module_tree: Optional[Dict[str, Any]] = None,
        repository_url: Optional[str] = None,
        github_pages_url: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        docs_dir: Optional[Path] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Generate HTML documentation viewer.
        
        Args:
            output_path: Output file path (index.html)
            title: Documentation title
            module_tree: Module tree structure (auto-loaded from docs_dir if not provided)
            repository_url: GitHub repository URL
            github_pages_url: Expected GitHub Pages URL
            config: Additional configuration
            docs_dir: Documentation directory (for auto-loading module_tree and metadata)
            metadata: Metadata dictionary (auto-loaded from docs_dir if not provided)
        """
        # Auto-load module_tree and metadata from docs_dir if not provided
        if docs_dir:
            if module_tree is None:
                module_tree = self.load_module_tree(docs_dir)
            if metadata is None:
                metadata = self.load_metadata(docs_dir)
        
        # Default values
        if module_tree is None:
            module_tree = {}
        if config is None:
            config = {}
        
        # Load template
        template_path = self.template_dir / "viewer_template.html"
        if not template_path.exists():
            raise FileSystemError(f"Template not found: {template_path}")
        
        template_content = safe_read(template_path)
        
        # Build info content HTML
        info_content = self._build_info_content(metadata)
        show_info = "block" if info_content else "none"
        
        # Build repository link
        repo_link = ""
        if repository_url:
            repo_link = f'<a href="{repository_url}" class="repo-link" target="_blank">🔗 View Repository</a>'
        
        # Determine docs base path
        # For GitHub Pages: relative path to docs folder
        # For local: relative path to docs folder
        docs_base_path = ""
        if docs_dir and output_path.parent != docs_dir:
            # Calculate relative path from output to docs
            try:
                docs_base_path = Path(docs_dir.name).as_posix()
            except Exception:
                docs_base_path = "."
        
        # Prepare JSON data for embedding
        config_json = json.dumps(config, indent=2)
        module_tree_json = json.dumps(module_tree, indent=2)
        metadata_json = json.dumps(metadata, indent=2) if metadata else "null"
        
        # Replace placeholders
        html_content = template_content
        replacements = {
            "{{TITLE}}": self._escape_html(title),
            "{{REPO_LINK}}": repo_link,
            "{{SHOW_INFO}}": show_info,
            "{{INFO_CONTENT}}": info_content,
            "{{CONFIG_JSON}}": config_json,
            "{{MODULE_TREE_JSON}}": module_tree_json,
            "{{METADATA_JSON}}": metadata_json,
            "{{DOCS_BASE_PATH}}": docs_base_path,
        }
        
        for placeholder, value in replacements.items():
            html_content = html_content.replace(placeholder, value)
        
        # Write output
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write(output_path, html_content)
    
    def _build_info_content(self, metadata: Optional[Dict[str, Any]]) -> str:
        if not metadata:
            return ""

        html_parts = []

        if metadata.get('language'):
            html_parts.append(f'<div class="info-row"><strong>Language:</strong> {self._escape_html(metadata["language"])}</div>')
        if metadata.get('target_audience'):
            html_parts.append(f'<div class="info-row"><strong>Audience:</strong> {self._escape_html(metadata["target_audience"])}</div>')
        if metadata.get('generated'):
            html_parts.append(f'<div class="info-row"><strong>Generated:</strong> {self._escape_html(metadata["generated"])}</div>')
        if metadata.get('commit_id'):
            html_parts.append(f'<div class="info-row"><strong>Commit:</strong> {self._escape_html(metadata["commit_id"][:8])}</div>')
        if metadata.get('total_components') is not None:
            html_parts.append(f'<div class="info-row"><strong>Components:</strong> {metadata["total_components"]:,}</div>')
        if metadata.get('documents') is not None:
            html_parts.append(f'<div class="info-row"><strong>Documents:</strong> {metadata["documents"]}</div>')

        return '\n                '.join(html_parts)
    
    def _escape_html(self, text: str) -> str:
        """
        Escape HTML special characters.
        
        Args:
            text: Text to escape
            
        Returns:
            Escaped text
        """
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))
       

    
    def detect_repository_info(self, repo_path: Path) -> Dict[str, Optional[str]]:
        """
        Detect repository information from git.
        
        Args:
            repo_path: Repository path
            
        Returns:
            Dictionary with 'name', 'url', 'github_pages_url'
        """
        info = {
            'name': repo_path.name,
            'url': None,
            'github_pages_url': None,
        }
        
        try:
            import git
            repo = git.Repo(repo_path)
            
            # Get repository name
            info['name'] = repo_path.name
            
            # Get remote URL
            if repo.remotes:
                remote_url = repo.remotes.origin.url
                
                # Clean URL
                if remote_url.startswith('git@github.com:'):
                    remote_url = remote_url.replace('git@github.com:', 'https://github.com/')
                
                remote_url = remote_url.rstrip('/').replace('.git', '')
                info['url'] = remote_url
                
                # Compute GitHub Pages URL
                if 'github.com' in remote_url:
                    parts = remote_url.split('/')
                    if len(parts) >= 2:
                        owner = parts[-2]
                        repo = parts[-1]
                        info['github_pages_url'] = f"https://{owner}.github.io/{repo}/"
        
        except Exception:
            pass
        
        return info

