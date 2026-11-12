"""Point d'entrée de l'application Streamlit.

Lancement :  streamlit run app.py

Habillage : palette « parchemin et encre », lisible que le système soit en
mode clair ou en mode sombre. Les couleurs sont imposées par la feuille de
style ci-dessous ET par le fichier .streamlit/config.toml, écrit
automatiquement au premier démarrage s'il est absent (c'est lui qui permet
aux tableaux et aux menus natifs de Streamlit d'adopter la même teinte).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

RACINE = Path(__file__).resolve().parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import database  # noqa: E402
from ui import (  # noqa: E402
    annotation_page,
    corpus_page,
    export_page,
    import_tableur_page,
    parametres_page,
    referentiel_page,
    tableau_de_bord_page,
    validation_page,
)

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
PARCHEMIN = "#F4EFE4"        # fond principal
PARCHEMIN_CLAIR = "#FBF8F1"  # champs de saisie
PARCHEMIN_OMBRE = "#E8E0CF"  # fonds secondaires
ENCRE = "#2B2721"            # texte principal
ENCRE_DOUCE = "#5F564A"      # légendes, texte secondaire
BOIS = "#262219"             # bandeau latéral
BOIS_TEXTE = "#E7DDC7"       # texte du bandeau latéral
OR = "#A98B50"               # filets et séparateurs
BORDEAUX = "#76382B"         # accent (boutons, onglet actif)

CONFIG_TOML = f"""# Thème de l'application (généré automatiquement, modifiable).
[theme]
base = "light"
primaryColor = "{BORDEAUX}"
backgroundColor = "{PARCHEMIN}"
secondaryBackgroundColor = "{PARCHEMIN_OMBRE}"
textColor = "{ENCRE}"
"""


def _installer_theme() -> None:
    """Écrit .streamlit/config.toml au premier lancement, s'il n'existe pas."""
    try:
        dossier = RACINE / ".streamlit"
        fichier = dossier / "config.toml"
        if not fichier.exists():
            dossier.mkdir(exist_ok=True)
            fichier.write_text(CONFIG_TOML, encoding="utf-8")
    except OSError:
        # Dossier en lecture seule : la feuille de style suffit à l'affichage.
        pass


_installer_theme()

st.set_page_config(
    page_title="Annotation XML-TEI — entités nommées",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)

SERIF = '"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif'

STYLE = f"""
<style>
/* ---------- Fond et texte ------------------------------------------- */
.stApp {{ background-color: {PARCHEMIN}; }}
.stApp, .stApp p, .stApp li, .stApp label, .stApp .stMarkdown,
.stApp [data-testid="stWidgetLabel"] {{ color: {ENCRE}; }}
.block-container {{ padding-top: 2.4rem; max-width: 1400px; }}

/* ---------- Titres --------------------------------------------------- */
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
  font-family: {SERIF} !important;
  color: {ENCRE} !important;
  font-weight: 600;
  letter-spacing: 0.012em;
}}
.stApp h1 {{
  font-size: 1.72rem !important;
  border-bottom: 1px solid {OR};
  padding-bottom: 0.45rem;
  margin-bottom: 0.3rem;
}}
.stApp h2 {{ font-size: 1.3rem !important; margin-top: 1.4rem; }}
.stApp h3 {{ font-size: 1.08rem !important; }}
.stApp h4 {{ font-size: 1rem !important; }}

/* ---------- Légendes et séparateurs ---------------------------------- */
.stApp [data-testid="stCaptionContainer"], .stApp small {{
  color: {ENCRE_DOUCE} !important;
  font-style: italic;
}}
.stApp hr {{ border-color: {OR}; opacity: 0.55; }}

/* ---------- Bandeau latéral ------------------------------------------ */
[data-testid="stSidebar"] {{
  background-color: {BOIS};
  border-right: 1px solid #120F0A;
}}
[data-testid="stSidebar"] * {{ color: {BOIS_TEXTE} !important; }}
[data-testid="stSidebar"] h1 {{
  font-family: {SERIF} !important;
  font-size: 1.3rem !important;
  border-bottom: 1px solid {OR};
  padding-bottom: 0.4rem;
}}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {{
  font-family: {SERIF}; font-size: 1.35rem;
}}
[data-testid="stSidebar"] hr {{ border-color: {OR}; opacity: 0.4; }}
[data-testid="stSidebar"] code {{ background: rgba(255,255,255,0.08); }}

/* ---------- Indicateurs ---------------------------------------------- */
.stApp [data-testid="stMetricValue"] {{
  font-family: {SERIF}; font-size: 1.5rem; color: {ENCRE};
}}
.stApp [data-testid="stMetricLabel"] {{ color: {ENCRE_DOUCE} !important; }}

/* ---------- Onglets --------------------------------------------------- */
.stTabs [data-baseweb="tab-list"] {{
  gap: 1.4rem; border-bottom: 1px solid #D8CDB5;
}}
.stTabs [data-baseweb="tab"] {{ font-family: {SERIF}; font-size: 0.97rem; }}
.stTabs [aria-selected="true"] {{ color: {BORDEAUX} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {BORDEAUX}; }}

/* ---------- Boutons --------------------------------------------------- */
.stApp button[kind="primary"] {{
  background-color: {BORDEAUX} !important;
  border: 1px solid #5B2A20 !important;
  color: #F8F3E7 !important;
}}
.stApp button[kind="primary"]:hover {{ background-color: #8A4334 !important; }}
.stApp button[kind="secondary"] {{
  background-color: {PARCHEMIN_CLAIR} !important;
  border: 1px solid #C3B596 !important;
  color: {ENCRE} !important;
}}
.stApp button[kind="secondary"]:hover {{ border-color: {BORDEAUX} !important; }}

/* ---------- Champs de saisie ----------------------------------------- */
.stApp .stTextInput input, .stApp .stTextArea textarea,
.stApp .stNumberInput input, .stApp [data-baseweb="select"] > div {{
  background-color: {PARCHEMIN_CLAIR} !important;
  color: {ENCRE} !important;
  border-color: #C8BA9C !important;
}}
[data-baseweb="popover"] li {{ font-size: 0.93rem; }}

/* ---------- Encadrés et messages -------------------------------------- */
.stAlert p {{ margin-bottom: 0; }}
.stApp [data-testid="stExpander"] details {{
  background-color: {PARCHEMIN_CLAIR};
  border: 1px solid #DCD0B8;
}}
.stApp [data-testid="stDataFrame"] {{ border: 1px solid #DCD0B8; }}

/* ---------- Surlignage des mentions annotées --------------------------
   Les couleurs sont posées en ligne par corpus.py ; on les reteinte ici
   pour qu'elles s'accordent au parchemin.                               */
span[style*="#b3d4fc"] {{ background: #C6D2DD !important; }}  /* PERSON  */
span[style*="#c8e6c9"] {{ background: #CAD7C2 !important; }}  /* PLACE   */
span[style*="#ffe0b2"] {{ background: #E7D4B2 !important; }}  /* ORG     */
span[style*="#e1bee7"] {{ background: #D7C8DA !important; }}  /* WORK    */
span[style*="#ffcdd2"] {{ background: #E2C6BD !important; }}  /* EVENT   */
span[style*="#e0e0e0"] {{ background: #DCD6CA !important; }}  /* OTHER   */
span[style*="#9e9e9e"] {{ border-color: #8C7E64 !important; }}
span[style*="#d32f2f"] {{ border-color: #8C3A2B !important; }}
</style>
"""


@st.cache_resource(show_spinner=False)
def connexion(chemin: str):
    """Connexion SQLite partagée par toutes les pages de la session."""
    return database.ouvrir(chemin)


PAGES = {
    "Tableau de bord": tableau_de_bord_page.afficher,
    "Corpus": corpus_page.afficher,
    "Annotation": annotation_page.afficher,
    "Référentiel des entités": referentiel_page.afficher,
    "Validation": validation_page.afficher,
    "Import tableur": import_tableur_page.afficher,
    "Export": export_page.afficher,
    "Paramètres": parametres_page.afficher,
}


def main() -> None:
    st.markdown(STYLE, unsafe_allow_html=True)

    chemin = st.session_state.get("chemin_base", str(database.CHEMIN_BASE_DEFAUT))
    cx = connexion(chemin)

    with st.sidebar:
        st.title("📜 Entités nommées")
        st.caption("Annotation et référentiel pour corpus XML-TEI")
        page = st.radio("Navigation", list(PAGES), label_visibility="collapsed")
        st.divider()
        stats = database.statistiques(cx)
        st.metric("Documents", stats["documents"])
        st.metric("Entités", stats["entites"])
        st.metric("Mentions annotées", stats["annotations"])
        st.divider()
        st.caption(f"Base : `{Path(chemin).name}`")
        st.caption("Les modifications sont enregistrées immédiatement.")

    PAGES[page](cx)


if __name__ == "__main__":
    main()
