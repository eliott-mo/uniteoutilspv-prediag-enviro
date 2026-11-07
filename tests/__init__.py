"""Les tests de l'outil.

    python -m unittest            depuis la racine du dépôt, avec le Python de l'outil

Ils n'ont besoin d'aucun référentiel : chaque cas porte sa remarque de BDC.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
