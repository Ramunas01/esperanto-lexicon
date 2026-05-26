# Setup

## Python dependencies
pip install -r requirements.txt --break-system-packages
python3 -m spacy download lt_core_news_sm

## Database setup
python3 src/lexicon/migrate_v1_to_v2.py

## Running the extraction pipeline
See docs/ for pipeline documentation.
