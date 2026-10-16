import os
import yaml
from dotenv import dotenv_values

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
dotenv_values(".env")

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

DEFAULT = {
    'port': 8000,
    'workers': 1,
    'debug': False,
    'log_level': 'info',
    'api_key': 'default-secret-8000'
}

def to_values(key, value):
    if key in {'port', 'workers'}:
        return int(value)

    if key == 'debug':
        return str(value).lower() in {'true', '1', 'yes', 'no'}

def load_config():
    config = DEFAULT.copy()
    
    # YAML Layer
    with open('./config.development.yaml', 'r') as f:
        yaml_config = yaml.safe_load(f) or {}
    
    for key, value in yaml_config.items():
        config[key] = to_values(key, value)
    # .env Layer
    env_file = dotenv_values(".env")

    for key, value in env_file.items():
        if value is None:   
            continue 
        
        if key == 'NUM_WORKEES':
            config['workers'] = to_values('workers', value)
        
        elif key.startswith('APP_'):
            config[key[4:].lower()] = to_values(key[4:].lower(), value)
    
    
    # OS Env Layer
    for key, value in os.environ.items():
        if key.startswith('APP_'):
            config[key[4:].lower()] = to_values(key[4:].lower(), value)
            
    return config


@app.get("/effective-config")
def effective_config(set: list[str] | None = Query(default=None)):
    config = load_config()

    # Query parameters have highest precedence
    for item in set or []:
        if "=" not in item:
            continue

        key, value = item.split("=", 1)
        config[key] = to_values(key, value)

    # Never expose the real API key
    config["api_key"] = "****"

    return {
        "port": config.get("port"),
        "workers": config.get("workers"),
        "debug": config.get("debug"),
        "log_level": config.get("log_level"),
        "api_key": config.get("api_key"),
    }