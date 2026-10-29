"""pmg-assist API, Milestone 0 skeleton: STUB with no routes yet.

Exists so api/tests/test_contract.py can import create_app and fail cleanly
before the real app is written. Replaced wholesale in the next step.
"""

from fastapi import FastAPI


def create_app(min_client_version=None, spec_path=None):
    return FastAPI(title="pmg-assist API")


app = create_app()
