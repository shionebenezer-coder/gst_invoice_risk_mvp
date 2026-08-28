# Invoice Risk & Collections MVP

This is a local MVP for Indian B2B SMEs.

## What it does

- Upload invoices and buyer-history CSVs
- Calculate a simple 0-100 collection-risk score
- Flag high-risk receivables
- Generate collection messages
- Flag potential invoice-discounting candidates
- Export the scored invoice book

## Run

Open PowerShell in this folder and run:

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

If you already set `GEMINI_API_KEY`, the message generator will try Gemini.
If not, the app uses built-in template messages.

## Important production note

The included risk engine is a heuristic MVP, not a credit bureau model.
Do not scrape GST systems or present the score as an official government risk score.
For a commercial product, integrate only with authorized data providers and licensed financing partners.
