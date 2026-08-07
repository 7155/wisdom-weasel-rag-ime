"""Pure Room lifecycle policies.

Modules in this package must not import persistence, runtime, projection,
workspace, HTTP, or UI code. Application services collect facts, call these
policies, and persist the returned past-tense decisions atomically.
"""

from .model import DomainPolicyError

__all__ = ["DomainPolicyError"]
