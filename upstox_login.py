import asyncio
import os
import re
import httpx
from urllib.parse import urlencode

from portfolio_mcp.config import get_settings

def update_env_file(access_token: str):
    env_path = ".env"
    if not os.path.exists(env_path):
        return

    with open(env_path, "r") as f:
        lines = f.readlines()

    new_lines = []
    found = False
    for line in lines:
        if line.startswith("UPSTOX_ACCESS_TOKEN="):
            new_lines.append(f"UPSTOX_ACCESS_TOKEN={access_token}\n")
            found = True
        else:
            new_lines.append(line)
            
    if not found:
        new_lines.append(f"UPSTOX_ACCESS_TOKEN={access_token}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)
    print("✅ .env file successfully updated with new access token!")


async def main():
    settings = get_settings()
    
    api_key = settings.upstox_api_key
    api_secret = settings.upstox_api_secret
    
    if not api_key or not api_secret:
        print("❌ Please ensure UPSTOX_API_KEY and UPSTOX_API_SECRET are set in your .env file.")
        return

    redirect_uri = "https://127.0.0.1" # A common redirect URI for native apps - update if needed in Upstox dev console

    params = {
        "response_type": "code",
        "client_id": api_key,
        "redirect_uri": redirect_uri,
    }
    
    auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?{urlencode(params)}"
    
    print("\n--- Upstox Authentication ---")
    print("\n1. Open this URL in your browser to login and authorize:")
    print(auth_url)
    print("\n2. After logging in, you will be redirected to an empty or error page.")
    print("3. Check the URL in your address bar -> it will look like:")
    print(f"   {redirect_uri}/?code=xxxxxx")
    
    code = input("\n👉 Paste the authorization code (the value of 'code=...') here: ").strip()
    
    if not code:
        print("❌ No code provided.")
        return
        
    print("\n⏳ Fetching access token...")
    
    async with httpx.AsyncClient() as client:
        # Standard Upstox Token Exchange
        token_url = "https://api.upstox.com/v2/login/authorization/token"
        data = {
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        response = await client.post(token_url, data=data, headers=headers)
        
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get("access_token")
            if access_token:
                print("✅ Access token retrieved successfully!")
                update_env_file(access_token)
            else:
                print("❌ Authentication failed. Upstox didn't return an access token.")
        else:
            print(f"❌ Failed to get access token ({response.status_code})")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(main())
