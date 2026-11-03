from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    run_time_limit_seconds: int = 180
    worker_poll_seconds: float = 1.0
