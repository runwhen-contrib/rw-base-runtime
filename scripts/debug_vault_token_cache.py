#!/usr/bin/env python3
"""
Debug script to verify Vault token cache integration.

Run this to check if VAULT_TOKEN_FILE and VAULT_TOKEN are set,
and whether the token cache would be used.
"""

import os
import sys

def main():
    print("=" * 60)
    print("Vault Token Cache Debug")
    print("=" * 60)
    
    # Check VAULT_TOKEN_FILE
    token_file = os.getenv('VAULT_TOKEN_FILE')
    print(f"\n1. VAULT_TOKEN_FILE environment variable:")
    if token_file:
        print(f"   ✓ Set to: {token_file}")
        if os.path.exists(token_file):
            print(f"   ✓ File exists")
            try:
                with open(token_file, 'r') as f:
                    token = f.read().strip()
                if token:
                    # Mask the token for security
                    masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "****"
                    print(f"   ✓ Token found: {masked} (length: {len(token)})")
                else:
                    print(f"   ✗ File is empty")
            except Exception as e:
                print(f"   ✗ Error reading file: {e}")
        else:
            print(f"   ✗ File does NOT exist")
    else:
        print(f"   ✗ Not set")
    
    # Check VAULT_TOKEN
    vault_token = os.getenv('VAULT_TOKEN')
    print(f"\n2. VAULT_TOKEN environment variable:")
    if vault_token:
        token = vault_token.strip()
        if token:
            masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "****"
            print(f"   ✓ Set to: {masked} (length: {len(token)})")
        else:
            print(f"   ✗ Set but contains only whitespace")
    else:
        print(f"   ✗ Not set")
    
    # Check other Vault-related env vars
    print(f"\n3. Other Vault environment variables:")
    vault_vars = [
        'RW_VAULT_ADDR',
        'RW_VAULT_URL',
        'RW_VAULT_APPROLE_ROLE_ID',
        'RW_VAULT_APPROLE_SECRET_ID',
        'RW_LOCATION_VAULT_AUTH_MOUNT_POINT',
        'RW_WORKSPACE',
        'RW_LOCATION',
    ]
    for var in vault_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if 'SECRET' in var:
                masked = value[:4] + "..." if len(value) > 4 else "****"
                print(f"   {var}: {masked}")
            else:
                print(f"   {var}: {value}")
        else:
            print(f"   {var}: (not set)")
    
    # Determine what auth method would be used
    print(f"\n4. Authentication method that would be used:")
    if token_file and os.path.exists(token_file):
        with open(token_file, 'r') as f:
            if f.read().strip():
                print(f"   → Would try: CACHED TOKEN FROM FILE first")
                print(f"     (Falls back to AppRole/K8s if token invalid)")
    elif vault_token and vault_token.strip():
        print(f"   → Would try: VAULT_TOKEN from environment first")
        print(f"     (Falls back to AppRole/K8s if token invalid)")
    elif os.getenv('RW_VAULT_APPROLE_ROLE_ID') and os.getenv('RW_VAULT_APPROLE_SECRET_ID'):
        print(f"   → Would use: AppRole authentication")
    else:
        print(f"   → Would use: Kubernetes authentication (default)")
    
    print("\n" + "=" * 60)
    print("To test with a cached token, run:")
    print("  export VAULT_TOKEN_FILE=/home/runwhen/.vault-token")
    print("  echo 's.your-token' > $VAULT_TOKEN_FILE")
    print("  python debug_vault_token_cache.py")
    print("=" * 60)

if __name__ == '__main__':
    main()


