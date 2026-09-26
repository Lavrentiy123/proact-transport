"""Корневой conftest: добавляет корень репозитория в sys.path (пакеты contracts, features, ml_core)."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
