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

    return f"""Je bent een ervaren makelaar in Amsterdam De Pijp die persoonlijk biedadvies geeft aan een potentiële koper. Schrijf alsof je tegenover hem of haar aan tafel zit, niet als een rapport.

# De woning waarvoor advies wordt gevraagd

{invoer_str}

# Vergelijkbare verkopen in dezelfde straat (gesorteerd op gelijkenis)
{comps_str}

---

Schrijf je advies als een lopend verhaal in 3 alinea's, in helder Nederlands. **Geen koppen, geen bullets, geen tabellen.** Je advies wordt op een website getoond aan een echte koper — laat het persoonlijk en menselijk klinken, zoals een makelaar die uitlegt waarom hij iets denkt.

**Alinea 1 — Wat ik van de markt zie**: vat in 2-3 zinnen samen wat de vergelijkbare verkopen je vertellen. Noem 2-3 concrete panden bij naam (bv. "Nummer 60-2 ging recent voor €536.500 voor 58m² vol eigendom, en nummer 163-3 haalde €630.000 mede dankzij een dakterras"). Wijs op patronen die ertoe doen: erfpacht-effect, label-spreiding, premium voor buitenruimte, etc.

**Alinea 2 — Wat dat betekent voor jouw pand**: verbind de comparables naar de woning waar deze koper interesse in heeft. Wat maakt dit pand uniek (groter/kleiner, beter label, vol eigendom of erfpacht, met/zonder tuin)? Welke comparables zijn DE beste anker en welke moet je minder zwaar wegen en waarom? Eindig met een concrete biedrange: "Een realistisch bod ligt tussen €X en €Y, met €Z als beste schatting."

**Alinea 3 — Waar je voorzichtig moet zijn**: 1-2 zinnen over outliers, onzekerheden of openstaande vragen. Bijvoorbeeld: "Pas wel op met nummer 254-A — dat is verkocht in verhuurde staat en niet vergelijkbaar voor een vrije markt-koper" of "Vraag de eigendomssituatie op vóór je biedt, want erfpacht/vol eigendom scheelt hier €100k-€150k". Wees concreet, niet algemeen.

{("Als de koper een vraagprijs van €" + format(invoer.get('vraagprijs', 0), ',') + " heeft genoemd, geef tussendoor je oordeel: realistisch / aan de hoge kant / te laag — en waarom.") if invoer.get('vraagprijs') else ""}

Belangrijk: schrijf alsof je de comparables echt hebt bekeken. Verwijs naar specifieke huisnummers en eigenschappen ("nummer 39-B met label B", "nummer 256-1A in verhuurde staat"). Maak het tastbaar.
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
st.caption("AI-gegenereerde biedrange op basis van 36 recente verkopen in dezelfde straat. **Demo / experimenteel.**")

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

    # Stap 1: comparables zoeken (snel)
    with st.spinner("Vergelijkbare verkopen zoeken..."):
        comps = haal_comparables(invoer['m2'], invoer['bouwjaar'], invoer['label'], invoer['eigendom'])

    if len(comps) < 3:
        st.warning(f"Slechts {len(comps)} vergelijkbare verkopen gevonden in de buurt — te weinig voor een onderbouwd advies.")
        st.stop()

    # Stap 2: advies genereren — staat bovenaan, prominent
    api_key = laad_api_key()
    with st.spinner(f"Analyseer {len(comps)} vergelijkbare verkopen en stel advies op..."):
        prompt = maak_prompt(invoer, comps)
        try:
            advies, usage = vraag_claude(prompt, api_key)
        except anthropic.APIError as e:
            st.error(f"Fout bij Claude API: {e}")
            st.stop()

    # Advies prominent tonen
    st.markdown("### Advies")
    st.markdown(advies)

    st.divider()

    # Comparables-tabel onder advies in uitklap-blok (voor wie wil graven)
    with st.expander(f"📊 De {len(comps)} verkopen waarop dit advies is gebaseerd"):
        tabel = []
        for c in comps:
            flag = " ⚠️" if c['transactie_flag'] == 'match_vraagprijs' else ""
            tabel.append({
                "Adres": c['address'],
                "m²": c['m2'],
                "Eigendom": (c['eigendom'] or "?").replace('_', ' '),
                "Label": c['label'] or "?",
                "Verkoopprijs": f"€{c['transactieprijs']:,}",
                "€/m²": f"€{c['eur_per_m2']:,}",
                "Betrouwbaarheid": (c['ai_betr'] or '?') + flag,
            })
        st.dataframe(tabel, hide_index=True, use_container_width=True)
        st.caption(
            "⚠️ = mogelijke datakwaliteit-flag · Betrouwbaarheid 'hoog/midden/laag' geeft aan hoe zeker we zijn van de "
            "kenmerken van die woning."
        )

    # Cost-info klein onderaan
    kosten = (usage.input_tokens * 3 + usage.output_tokens * 15) / 1_000_000
    st.caption(f"Advies gegenereerd in ~10s · API-kosten ~€{kosten:.4f}")

# ---------- Footer ----------

st.divider()
st.caption(
    "🚧 **Demo-versie** · Werkt alleen voor de Albert Cuypstraat · "
    "Comparables uit Funda's verkocht-archief (2024-2026) · "
    "Geen vervanging voor een professionele taxatie."
)
