#!/usr/bin/env python3
import os
import sys
import argparse
import asyncio
from importlib.util import spec_from_file_location, module_from_spec

def import_module_from_path(path, module_name):
    """Import a module from a file path."""
    spec = spec_from_file_location(module_name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    parser = argparse.ArgumentParser(description='Run The Seekret in either CLI or Bot mode')
    parser.add_argument('mode', choices=['cli', 'bot'], help='Run mode: cli or bot')
    args = parser.parse_args()

    if args.mode == 'cli':
        # Import and run CLI version
        cli_module = import_module_from_path(os.path.join('cli', 'seek_jobs_monitor.py'), 'seek_jobs_monitor')
        asyncio.run(cli_module.main())
    else:
        # Import and run Bot version
        bot_module = import_module_from_path(os.path.join('bot', 'bot.py'), 'bot')
        asyncio.run(bot_module.main())

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0) 