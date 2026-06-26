# Shared config and secrets loading — keeps .yaml parsing in one place

import yaml
import os


def load_config(path='.yaml'):
    with open(path) as f:
        return yaml.safe_load(f)


def load_anthropic_key(config_path='.yaml'):
    cfg = load_config(config_path)
    os.environ['ANTHROPIC_API_KEY'] = cfg['anthropic_api_key']
