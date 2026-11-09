"""Compatibility entry point for the current cadastral-only acceptance check."""
from verify_vmd_cadastral_registration import run

if __name__=='__main__':
    run(live=False)
