#!/bin/bash
# Скрипт для запуска TON Domain Game

echo "Setting up virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting server..."
python3 app.py