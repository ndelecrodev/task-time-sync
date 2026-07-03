import requests
from dotenv import load_dotenv
import os


load_dotenv()

headers = {
    "X-Api-Key": os.getenv("API_KEY_CLOCKIFY")
}
try:
    with open(".env", "+a", encoding="utf-8") as file_env:
        file_env.seek(0)
        if "WORKSPACE_NAME" in file_env.read():
            if "WORKSPACE_ID" not in file_env.read():
                response = requests.get("https://api.clockify.me/api/v1/workspaces", headers=headers)
                response_json = response.json()
                for i in response_json:
                    if i['name'] == str(os.getenv("WORKSPACE_NAME")):
                        response_id = i["id"]
                        file_env.write(f"\nWORKSPACE_ID={response_id}")
            else:
                print("The WORKSPACE_ID already exists in your .env file.")
        else:
            print("There is no way to retrieve a workspace ID without its name.")
except Exception:
    print("There was an error")