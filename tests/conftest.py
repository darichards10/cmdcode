"""
Shared pytest configuration and path setup for cmdcode tests.
"""
import sys
import os

# Make server module importable from tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

# Make CLI package importable from tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cli", "src"))
