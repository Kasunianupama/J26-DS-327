"""USER-RUN ONLY: opt-in loopback read-only dashboard, without login prompts."""
import argparse
import os


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-local-read-only", action="store_true", required=True,
                        help="Allow other local processes to read Member 4 research outputs without login.")
    parser.parse_args(argv)
    if os.environ.get("APP_ENV", "development") != "development":
        raise ValueError("local_mode_requires_development_environment")
    if os.environ.get("APP_DB_API_USER", "farmx_api") != "farmx_api":
        raise ValueError("local_mode_requires_farmx_api_role")
    os.environ.update(APP_ENV="development", C4_LOCAL_READ_ONLY="on", C4_RESEARCH_DB="on",
                      C4_LOCAL_AUTH_ENABLED="off", APP_DB_API_USER="farmx_api")
    os.environ.setdefault("APP_DB_PORT", "5432")
    print("LOCAL DEVELOPMENT ONLY: Member 4 GET outputs are readable by other local processes. No LAN/proxy access. Stop the server to disable.")
    import uvicorn
    # No reload/proxy trust/LAN bind. Existing backend database configuration only.
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
