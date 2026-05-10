# Bidtool Albert Cuypstraat — Streamlit Demo

AI-biedadviseur voor de Albert Cuypstraat, gebaseerd op 22 recente verkopen + Claude Sonnet 4.6.

## Lokaal draaien (test op je Mac)

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run bidtool_streamlit.py
```

## Deployen naar Streamlit Cloud

1. **Push deze map naar een GitHub-repo** (publiek — Streamlit Cloud free tier vereist dat).
   Als je dat via de GitHub-website doet: nieuwe repo aanmaken → "Add file" → "Upload files" → sleep alle 4 bestanden van deze map (`bidtool_streamlit.py`, `bidtool_albert_cuyp.db`, `requirements.txt`, `README.md`).

2. **Login op share.streamlit.io** met je GitHub-account.

3. **Klik "New app"** → kies je repo → main branch → file `bidtool_streamlit.py` → "Deploy".

4. **API-key configureren** (NIET in de repo!):
   - Ga naar je app op Streamlit Cloud → ⋮ menu → "Settings" → tabblad "Secrets"
   - Plak deze regel:
     ```
     ANTHROPIC_API_KEY = "sk-ant-..."
     ```
   - Save. App herstart automatisch.

5. Je app is nu live op `https://[username]-[repo].streamlit.app`. Test 'm.

## Optioneel: koppel aan dehuizenmarkt.nu

Op je Netlify-landingspagina maak je een button met `<a href="https://[je-streamlit-url]">Probeer de bid-tool</a>`. Of zet een redirect via Netlify.
