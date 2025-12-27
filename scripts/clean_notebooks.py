import sys
import json
from pathlib import Path

# Add project root to path so we can import packages like 'db_utils'
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from db_utils.paths import PROJECT_ROOT

def clean_notebook(notebook_path):
    """Remove all outputs from a Jupyter notebook."""
    # Path objects can be passed directly to open()
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook = json.load(f)
    
    # Check if it's actually a notebook
    if 'cells' not in notebook:
        return False
        
    is_clean = True
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            if len(cell.get('outputs', [])) > 0 or cell.get('execution_count') is not None:
                cell['outputs'] = []
                cell['execution_count'] = None
                is_clean = False
    
    if not is_clean:
        with open(notebook_path, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=1, ensure_ascii=False)
            f.write('\n')
    
    return not is_clean

def main():
    """Clean all notebooks in the repository."""
    # Use PROJECT_ROOT.rglob to find all notebooks regardless of CWD
    notebooks = list(PROJECT_ROOT.rglob('*.ipynb'))
    
    # Filter out checkpoints
    notebooks = [nb for nb in notebooks if '.ipynb_checkpoints' not in str(nb)]
    
    cleaned = 0
    for nb in notebooks:
        if clean_notebook(nb):
            print(f"Cleaned {nb.relative_to(PROJECT_ROOT)}")
            cleaned += 1
    
    if cleaned > 0:
        print(f"\nCleaned outputs from {cleaned} notebook{'s' if cleaned > 1 else ''}")
        sys.exit(1)  # Exit with error so git will abort if notebooks were cleaned
    else:
        print("No notebook outputs to clean")
        sys.exit(0)

if __name__ == '__main__':
    main()
 