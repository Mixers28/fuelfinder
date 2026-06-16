from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # UK — GOV.UK Fuel Finder
    fuel_finder_client_id: str = ""
    fuel_finder_client_secret: str = ""
    fuel_finder_base_url: str = "https://api.fuel-finder.service.gov.uk"

    # Germany — Tankerkönig (creativecommons.tankerkoenig.de)
    tankerkoenig_api_key: str = ""

    # Netherlands — Directprijzen (directprijzen.nl)
    directprijzen_api_key: str = ""

    station_cache_ttl: int = 3600  # 1 hour
    price_cache_ttl: int = 900  # 15 minutes

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./fuel_finder.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
