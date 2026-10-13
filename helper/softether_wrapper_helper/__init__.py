"""Privileged D-Bus helper for the SoftEther VPN Wrapper.

This package runs as root under systemd.  It exposes a *fixed, validated*
D-Bus surface that wraps the local ``vpncmd`` binary.  It never executes an
arbitrary command line and never uses a shell.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
