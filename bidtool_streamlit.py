"""
AI Biedadviseur — Albert Cuypstraat (MVP demo)

Streamlit-versie van de bid-tool. Werkt op Streamlit Cloud met de mini-DB
(bidtool_albert_cuyp.db) die in dezelfde repo staat.

API-key komt uit Streamlit Secrets:
    [secrets]
    ANTHROPIC_API_KEY = "sk-ant-..."
"""

import os
import sqlite3
from pathlib import Path

import anthropic
import streamlit as st

# ---------- Config ----------

HERE = Path(__file__).parent
DB_PAD = HERE / "bidtool_albert_cuyp.db"
MODEL = "claude-sonnet-4-6"
TOP_N = 7

st.set_page_config(
    page_title="Bidadvies Albert Cuypstraat",
    page_icon="🏠",
    layout="centered",
)


# ---------- API key ----------

def laad_api_key():
    """Probeer Streamlit secrets, dan environment variable."""
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key
    st.error(
        "Geen ANTHROPIC_API_KEY gevonden. "
        "Configureer 'm in Streamlit Cloud → App settings → Secrets."
    )
    st.stop()


# ---------- Comparables ----------

def label_naar_score(label):
    if not label:
        return None
    label = label.upper().strip()
    plus = label.count("+")
    letter = label.replace("+", "")
    if not letter or letter not in "ABCDEFG":
        return None
    return (ord("G") - ord(letter)) + 1 + plus


@st.cache_data
def haal_comparables(input_m2, input_bouwjaar, input_label, input_eigendom):
    """Zoek vergelijkbare verkopen. Cached zodat dezelfde input niet 2× rekent."""
    db = sqlite3.connect(DB_PAD)
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT
            s.address,
            s.url,
            s.last_asking_price_eur            AS vraagprijs,
            COALESCE(e.transactieprijs_eur, s.transactieprijs_eur) AS transactieprijs,
            e.transactie_datum                 AS transactie_datum,
            e.transactie_bron                  AS transactie_bron,
            e.transactie_flag                  AS transactie_flag,
            e.woonoppervlak_m2                 AS m2,
            e.bouwjaar                         AS bouwjaar,
            e.energielabel                     AS label,
            e.slaapkamers                      AS slaapkamers,
            e.woningtype                       AS woningtype,
            e.eigendomssituatie                AS eigendom,
            d.aantal_kamers                    AS kamers,
            d.vve_bijdrage_eur                 AS vve,
            d.tuin                             AS tuin,
            d.balkon                           AS balkon,
            d.balkon_m2                        AS balkon_m2,
            d.dakterras                        AS dakterras,
            d.berging                          AS berging,
            d.isolatie                         AS isolatie,
            d.verwarming                       AS verwarming,
            d.ai_betrouwbaarheid               AS ai_betr
        FROM sales s
        LEFT JOIN enrichment e ON e.funda_url = s.url
        LEFT JOIN details    d ON d.funda_url = s.url
        WHERE e.woonoppervlak_m2 IS NOT NULL
          AND COALESCE(e.transactieprijs_eur, s.transactieprijs_eur) IS NOT NULL
    """).fetchall()
    db.close()

    input_label_score = label_naar_score(input_label)
    comps = []
    for r in rows:
        c = dict(r)
        score = 100.0
        m2_diff_pct = abs(c['m2'] - input_m2) / max(input_m2, 1)
        score -= m2_diff_pct * 100
        if input_eigendom and c['eigendom']:
            if c['eigendom'] == input_eigendom:
                score += 30
            else:
                score -= 40
        if input_bouwjaar and c['bouwjaar']:
            score -= abs(c['bouwjaar'] - input_bouwjaar) / 5
        c_label_score = label_naar_score(c['label'])
        if input_label_score and c_label_score:
            score -= abs(input_label_score - c_label_score) * 5
        betr = (c['ai_betr'] or '').lower()
        if betr == "laag":   score -= 15
        elif betr == "midden": score -= 5
        if c['transactie_flag'] == 'match_vraagprijs':
            score -= 10
        c['score'] = round(score, 1)
        c['eur_per_m2'] = round(c['transactieprijs'] / c['m2']) if c['m2'] else None
        comps.append(c)

    comps.sort(key=lambda x: x['score'], reverse=True)
    return comps[:TOP_N]


# ---------- Claude prompt ----------

def maak_prompt(invoer, comps):
    invoer_str = (
        f"- Adres: {invoer['adres']}\n"
        f"- Woonoppervlak: {invoer['m2']} m²\n"
        f"- Bouwjaar: {invoer.get('bouwjaar') or 'onbekend'}\n"
        f"- Energielabel: {invoer.get('label') or 'onbekend'}\n"
        f"- Eigendomssituatie: {invoer.get('eigendom') or 'onbekend'}\n"
    )
    if invoer.get('vraagprijs'):
        invoer_str += f"- Vraagprijs: €{invoer['vraagprijs']:,}\n"

    comps_str = ""
    for i, c in enumerate(comps, 1):
        flag = " ⚠️match-vraagprijs" if c['transactie_flag'] == 'match_vraagprijs' else ""
        comps_str += f"\n## Comparable {i} — {c['address']}\n"
        comps_str += f"- Verkoopprijs: €{c['transactieprijs']:,} ({c.get('transactie_bron') or 'onbekend'}{flag})\n"
        if c.get('vraagprijs'):
            comps_str += f"- Vraagprijs: €{c['vraagprijs']:,}\n"
        comps_str += f"- Woonoppervlak: {c['m2']} m² → €{c['eur_per_m2']:,}/m²\n"
        comps_str += f"- Bouwjaar: {c.get('bouwjaar') or '?'}\n"
        comps_str += f"- Energielabel: {c.get('label') or '?'}\n"
        comps_str += f"- Eigendomssituatie: {c.get('eigendom') or '?'}\n"
        comps_str += f"- Slaapkamers: {c.get('slaapkamers') or '?'}\n"
        if c.get('vve'):
            comps_str += f"- VVE: €{c['vve']}/maand\n"
        kenmerken = []
        if c.get('balkon'):
            kenmerken.append("balkon" + (f" {c['balkon_m2']}m²" if c.get('balkon_m2') else ""))
        if c.get('tuin'):       kenmerken.append("tuin")
        if c.get('dakterras'):  kenmerken.append("dakterras")
        if c.get('berging'):    kenmerken.append("berging")
        if kenmerken:
            comps_str += f"- Buitenruimte/extra: {', '.join(kenmerken)}\n"
        comps_str += f"- Data-betrouwbaarheid: {c.get('ai_betr') or 'onbekend'}\n"

    return f"""Je bent een ervaren makelaar in Amsterdam De Pijp die een biedadvies geeft op basis van vergelijkbare recente verkopen.

# De woning waarvoor advies wordt gevraagd

{invoer_str}

# Vergelijkbare verkopen (gefilterd op straat + sortering op gelijkenis)
{comps_str}

---

Geef een biedadvies in deze structuur:

## Bandbreedte
- **Lage schatting:** € ...
- **Mediane schatting:** € ...
- **Hoge schatting:** € ...

## Onderbouwing
3-5 zinnen waarin je uitlegt hoe je tot dit bedrag komt. Verwijs naar specifieke comparables (op nummer/adres). Noem expliciet als eigendomssituatie (erfpacht vs vol eigendom) of label-verschillen je inschatting beïnvloeden.

## Waarschuwingen / outliers
- Comparables die scheef lijken (bv. verhuurd-verkocht waardoor €/m² laag is)
- Comparables met data-betrouwbaarheid 'midden' of 'laag' — die zou ik minder zwaar wegen
- Comparables met de match-vraagprijs flag (mogelijk recyclage)
- Algemene caveats (kleine sample, beperkte spreiding)

## Vraagprijs-check
Alleen als vraagprijs is opgegeven: realistisch (binnen bandbreedte) / onder / boven.

Houd het kort en concreet — dit wordt aan een potentiële koper getoond op een website.
"""


def vraag_claude(prompt, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text, msg.usage


# ---------- UI ----------

st.title("🏠 Bidadvies Albert Cuypstraat")
st.caption("AI-gegenereerde biedrange op basis van 22 recente verkopen in dezelfde straat. **Demo / experimenteel.**")

with st.form("invoer_form"):
    st.subheader("Vul de kenmerken van de woning in")

    col1, col2 = st.columns(2)
    with col1:
        adres = st.text_input("Adres", placeholder="Albert Cuypstraat 100-2")
        m2 = st.number_input("Woonoppervlak (m²)", min_value=15, max_value=300, value=60, step=1)
        bouwjaar = st.number_input("Bouwjaar", min_value=1700, max_value=2030, value=1890, step=1)
    with col2:
        label = st.selectbox(
            "Energielabel",
            ["onbekend", "A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"],
            index=7,  # default C
        )
        eigendom = st.selectbox(
            "Eigendomssituatie",
            ["onbekend", "vol_eigendom", "erfpacht"],
            index=0,
        )
        vraagprijs = st.number_input("Vraagprijs in € (optioneel)", min_value=0, max_value=5_000_000, value=0, step=10_000)

    submitted = st.form_submit_button("Bereken biedadvies", type="primary")

if submitted:
    if not adres.strip():
        st.error("Vul een adres in.")
        st.stop()

    invoer = {
        "adres": adres.strip(),
        "m2": int(m2),
        "bouwjaar": int(bouwjaar) if bouwjaar else None,
        "label": label if label != "onbekend" else None,
        "eigendom": eigendom if eigendom != "onbekend" else None,
        "vraagprijs": int(vraagprijs) if vraagprijs > 0 else None,
    }

    with st.spinner("Comparables zoeken in database..."):
        comps = haal_comparables(invoer['m2'], invoer['bouwjaar'], invoer['label'], invoer['eigendom'])

    if len(comps) < 3:
        st.warning(f"Slechts {len(comps)} comparables gevonden — te weinig voor zinvol advies.")
        st.stop()

    st.success(f"✓ {len(comps)} comparables gevonden")

    # Comparables tabel
    st.subheader("Vergelijkbare verkopen")
    tabel = []
    for c in comps:
        flag = " ⚠️" if c['transactie_flag'] == 'match_vraagprijs' else ""
        tabel.append({
            "Adres": c['address'],
            "m²": c['m2'],
            "Eigendom": c['eigendom'] or "?",
            "Label": c['label'] or "?",
            "Verkoopprijs": f"€{c['transactieprijs']:,}",
            "€/m²": f"€{c['eur_per_m2']:,}",
            "Score": c['score'],
            "Betr.": (c['ai_betr'] or '?').replace('_', ' ') + flag,
        })
    st.dataframe(tabel, hide_index=True, use_container_width=True)

    # Claude advies
    api_key = laad_api_key()
    with st.spinner("Claude raadplegen voor biedadvies..."):
        prompt = maak_prompt(invoer, comps)
        try:
            advies, usage = vraag_claude(prompt, api_key)
        except anthropic.APIError as e:
            st.error(f"Fout bij Claude API: {e}")
            st.stop()

    st.subheader("📊 Biedadvies")
    st.markdown(advies)

    # Cost-info onderaan, klein
    kosten = (usage.input_tokens * 3 + usage.output_tokens * 15) / 1_000_000
    st.caption(f"Kosten van deze API-call: ~€{kosten:.4f} ({usage.input_tokens} in / {usage.output_tokens} out tokens)")

# ---------- Footer ----------

st.divider()
st.caption(
    "🚧 **Demo-versie** · Werkt alleen voor de Albert Cuypstraat · "
    "Comparables uit Funda's verkocht-archief (2024-2026) · "
    "Geen vervanging voor een professionele taxatie."
)
