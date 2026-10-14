"""Root conftest — makes ``eolex`` importable without a separate pip install.

Inserts the ``eolex/`` subdirectory (which contains the ``eolex`` Python
package) into ``sys.path`` so tests can ``import eolex`` directly from the
working tree.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "eolex"))
