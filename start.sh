#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
exec python3 -m streamlit run streamlit_app.py
