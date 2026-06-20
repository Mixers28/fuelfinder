from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # UK — GOV.UK Fuel Finder
    fuel_finder_client_id: str = ""
    fuel_finder_client_secret: str = ""
    fuel_finder_base_url: str = "https://www.fuel-finder.service.gov.uk"
    fuel_finder_user_agent: str = "FuelFinderBackend/0.1"
    fuel_finder_auth_backoff_seconds: int = 300
    diagnostics_token: str = ""
    uk_data_source: str = "api"  # api or csv
    admin_import_token: str = ""

    # Germany — Tankerkönig (creativecommons.tankerkoenig.de)
    tankerkoenig_api_key: str = ""

    # Netherlands — ANWB (api.anwb.nl, key from app traffic interception)
    anwb_api_key: str = ""

    station_cache_ttl: int = 3600  # 1 hour
    price_cache_ttl: int = 900  # 15 minutes

    host: str = "0.0.0.0"
    port: int = 8000

    database_path: str = ""
    database_url: str = "sqlite+aiosqlite:///./fuel_finder.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
