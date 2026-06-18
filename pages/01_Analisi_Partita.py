import pandas as pd
import streamlit as st
import sys
import os

# --- Configurazione Percorsi ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'modules'))

import config
import odds_fetcher
import elo_model
import poisson_model
import bankroll_manager as bm
import risk_commentary

st.set_page_config(page_title="Analisi Partita", page_icon="📊", layout="wide")
st.title("📊 Analisi Partita")

# --- Sezione 1: caricamento storico ---
st.header("1. Storico partite")
file_caricato = st.file_uploader("Carica il tuo CSV storico", type=["csv"], key="uploader_storico_unico")

if file_caricato is None:
    st.info("Carica un CSV per procedere con l'analisi.")
    st.stop()

try:
    df_storico_grezzo = pd.read_csv(file_caricato, sep=None, engine='python', encoding='utf-8-sig')
    mapping_colonne = {
        'Div': 'Campionato',
        'Date': 'Data',
        'HomeTeam': 'SquadraCasa',
        'AwayTeam': 'SquadraOspite',
        'FTHG': 'GolCasa',
        'FTAG': 'GolOspite'
    }
    storico = df_storico_grezzo.rename(columns={k: v for k, v in mapping_colonne.items() if k in df_storico_grezzo.columns})
    st.success(f"Caricate {len(storico)} partite valide.")
except Exception as e:
    st.error(f"Errore nel caricamento: {e}")
    st.stop()

# --- Sezione 2: selezione partita ---
st.header("2. Partita da analizzare")
campionati_disponibili = sorted(storico["Campionato"].unique().astype(str))
campionato_selezionato = st.selectbox("Campionato", campionati_disponibili)
squadre_nel_campionato = sorted(pd.unique(
    storico[storico["Campionato"] == campionato_selezionato][["SquadraCasa", "SquadraOspite"]].values.ravel()
))
col_c1, col_c2 = st.columns(2)
squadra_casa = col_c1.selectbox("Squadra di casa", squadre_nel_campionato, key="squadra_casa")
opzioni_ospite = [s for s in squadre_nel_campionato if s != squadra_casa]
squadra_ospite = col_c2.selectbox("Squadra ospite", opzioni_ospite, key="squadra_ospite")

# --- Sezione 3: calcolo Poisson ---
st.header("3. Motore quantitativo (Poisson)")
if st.button("Calcola probabilità", type="primary"):
    try:
        medie = poisson_model.calcola_medie_campionato(storico, campionato_selezionato)
        forza = poisson_model.calcola_forza_squadre(storico, campionato_selezionato)
        lam_casa, lam_ospite = poisson_model.calcola_lambda_partita(forza, medie, squadra_casa, squadra_ospite)
        matrice = poisson_model.matrice_probabilita_risultati(lam_casa, lam_ospite)
        st.session_state["ultima_analisi"] = {
            "squadra_casa": squadra_casa, "squadra_ospite": squadra_ospite,
            "lambda_casa": lam_casa, "lambda_ospite": lam_ospite,
            "prob_1x2": poisson_model.probabilita_1x2(matrice),
            "prob_ou_25": poisson_model.probabilita_over_under(matrice, soglia=2.5)
        }
    except Exception as e:
        st.error(f"Errore calcolo: {e}")

if "ultima_analisi" in st.session_state:
    analisi = st.session_state["ultima_analisi"]
    if analisi["squadra_casa"] == squadra_casa and analisi["squadra_ospite"] == squadra_ospite:
        c1, c2, c3 = st.columns(3)
        c1.metric("Gol casa", f"{analisi['lambda_casa']:.2f}")
        c2.metric("Gol ospite", f"{analisi['lambda_ospite']:.2f}")
        c3.metric("Totale", f"{analisi['lambda_casa'] + analisi['lambda_ospite']:.2f}")
        
        st.subheader("Probabilità 1X2")
        p1, px, p2 = st.columns(3)
        p1.metric("1", f"{analisi['prob_1x2']['VittoriaCasa']*100:.1f}%")
        px.metric("X", f"{analisi['prob_1x2']['Pareggio']*100:.1f}%")
        p2.metric("2", f"{analisi['prob_1x2']['VittoriaOspite']*100:.1f}%")

# --- Sezione 4: EV ---
st.header("4. Value Betting (EV)")
if "ultima_analisi" in st.session_state:
    analisi = st.session_state["ultima_analisi"]
    modalita = st.radio("Origine quote", ["Recupera automaticamente", "Manuale"], horizontal=True)
    
    quota_1, quota_x, quota_2 = None, None, None
    if modalita == "Recupera automaticamente":
        if st.button("Recupera quote"):
            try:
                partite = odds_fetcher.recupera_partite_con_quote(campionato_selezionato)
                match = odds_fetcher.trova_partita_corrispondente(partite, squadra_casa, squadra_ospite)
                if match["esito"] == "trovata":
                    qr = odds_fetcher.estrai_quote_1x2_medie(match["partita"])
                    st.session_state["quote_recuperate"] = qr
            except Exception as e: st.error(f"Errore: {e}")
        if "quote_recuperate" in st.session_state:
            qr = st.session_state["quote_recuperate"]
            quota_1, quota_x, quota_2 = qr["quota_1"], qr["quota_x"], qr["quota_2"]
    else:
        c1, c2, c3 = st.columns(3)
        quota_1 = c1.number_input("Quota 1", 1.01, 10.0, 2.0)
        quota_x = c2.number_input("Quota X", 1.01, 10.0, 3.2)
        quota_2 = c3.number_input("Quota 2", 1.01, 10.0, 3.8)

    if quota_1 and st.button("Calcola EV"):
        p = analisi["prob_1x2"]
        df_ev = pd.DataFrame([
            {"Mercato": "1", "EV": f"{(p['VittoriaCasa']*quota_1)-1:.1%}"},
            {"Mercato": "X", "EV": f"{(p['Pareggio']*quota_x)-1:.1%}"},
            {"Mercato": "2", "EV": f"{(p['VittoriaOspite']*quota_2)-1:.1%}"}
        ])
        st.dataframe(df_ev, use_container_width=True)

# --- Sezione 5: Commento rischio ---
st.header("5. Commento di rischio")
man = st.text_area("Manuale")
dati = st.text_area("Dati grezzi")
if st.button("Genera commento"):
    try:
        comm = risk_commentary.genera_commento_rischio(
            squadra_casa, squadra_ospite, {"infortuni_e_formazioni": [dati]}, man,
            analisi["lambda_casa"], analisi["lambda_ospite"]
        )
        st.markdown(comm)
    except Exception as e: st.error(f"Errore: {e}")
