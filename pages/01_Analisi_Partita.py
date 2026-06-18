"""
pages/01_Analisi_Partita.py

Pagina principale di analisi: carica lo storico, calcola Poisson/Elo,
valida le formazioni (doppio feed o gerarchico), confronta con le quote
di mercato per il calcolo dell'EV, e genera il commento di rischio
qualitativo via Claude.

Il prefisso numerico (01_) controlla l'ordine nella sidebar di
navigazione di Streamlit: è una convenzione del framework, non
arbitraria.
"""
import pandas as pd
import streamlit as st
import sys
import os

# Aggiunge la cartella principale al percorso di ricerca
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Aggiunge la cartella 'modules' al percorso di ricerca
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'modules'))

import config
import odds_fetcher
import elo_model
import poisson_model
import bankroll_manager


st.set_page_config(page_title="Analisi Partita", page_icon="📊", layout="wide")
st.title("📊 Analisi Partita")


# --- Sezione 1: caricamento storico ---
# --- Sezione 1: caricamento storico ---
st.header("1. Storico partite")

# Usiamo una sola volta l'uploader con una chiave univoca
file_caricato = st.file_uploader("Carica il tuo CSV storico", type=["csv"], key="uploader_storico_unico")

if file_caricato is None:
    st.info("Carica un CSV per procedere con l'analisi.")
    st.stop()
try:
    df_storico_grezzo = pd.read_csv(file_caricato, sep=None, engine='python', encoding='utf-8-sig')
    
    # 1. Normalizzazione (quella che funziona!)
    mapping_colonne = {
        'Div': 'Campionato',
        'Date': 'Data',
        'HomeTeam': 'Squadra casa', # Nota: ho usato lo spazio come nello screenshot
        'AwayTeam': 'Squadra ospite',
        'FTHG': 'Gol casa',
        'FTAG': 'Gol ospite'
    }
    storico = df_storico_grezzo.rename(columns=mapping_colonne)
    
    # 2. ELIMINIAMO il pezzo che crasha (non salvare su tmp, non ricaricare)
    # storico = elo_model.carica_storico(path_temporaneo) # <--- ELIMINA O COMMENTA QUESTA RIGA
    
    st.success(f"Caricate {len(storico)} partite valide.")
    
except Exception as e:
    st.error(f"Errore: {e}")
    st.stop()
# --- A QUI ---
    
    # --- LOGICA DI NORMALIZZAZIONE (come concordato) ---
    mapping_colonne = {
        'Div': 'Campionato',
        'Date': 'Data',
        'HomeTeam': 'SquadraCasa',
        'AwayTeam': 'SquadraOspite',
        'FTHG': 'GolCasa',
        'FTAG': 'GolOspite'
    }
    df_storico_grezzo = df_storico_grezzo.rename(columns=mapping_colonne)
    
    # Assegnazione finale
    storico = df_storico_grezzo
    
    # ... resto del tuo codice ...
    
except Exception as e:
    st.error(f"Errore tecnico durante la lettura del file: {e}")
    st.write("Verifica se il file è un CSV testuale o un file Excel salvato erroneamente.")
    st.stop()
    # ---------------------------------------

    path_temporaneo = "/tmp/storico_caricato_streamlit.csv"
    df_storico_grezzo.to_csv(path_temporaneo, index=False)
    storico = elo_model.carica_storico(path_temporaneo)
    
    # Importante: ri-assegnamo il df normalizzato anche alla variabile 'storico' 
    # se la funzione carica_storico non lo fa internamente
    storico = df_storico_grezzo 

except Exception as e:
    st.error(f"Errore nel caricamento: {e}")
    st.stop()
if file_caricato is None:
    st.info("Carica un CSV per procedere con l'analisi. Il motore non genera dati di esempio: "
            "serve uno storico reale per produrre stime affidabili.")
    st.stop()

try:
    df_storico_grezzo = pd.read_csv(file_caricato)
    # Riutilizzo la stessa funzione di validazione già testata in
    # elo_model.py, scrivendo temporaneamente su disco perché quella
    # funzione si aspetta un path file, non un DataFrame già in memoria.
    path_temporaneo = "/tmp/storico_caricato_streamlit.csv"
    df_storico_grezzo.to_csv(path_temporaneo, index=False)
    storico = elo_model.carica_storico(path_temporaneo)
except ValueError as e:
    st.error(f"Errore nel formato del CSV: {e}")
    st.stop()
except Exception as e:
    st.error(f"Errore imprevisto nel caricamento: {e}")
    st.stop()

st.success(f"Caricate {len(storico)} partite valide.")
with st.expander("Vedi storico caricato"):
    st.dataframe(storico, use_container_width=True)


# --- Sezione 2: selezione partita da analizzare ---
st.header("2. Partita da analizzare")

campionati_disponibili = sorted(storico["Campionato"].unique())
campionato_selezionato = st.selectbox("Campionato", campionati_disponibili)

squadre_nel_campionato = sorted(pd.unique(
    storico[storico["Campionato"] == campionato_selezionato][["SquadraCasa", "SquadraOspite"]].values.ravel()
))

colonna_casa, colonna_ospite = st.columns(2)
with colonna_casa:
    squadra_casa = st.selectbox("Squadra di casa", squadre_nel_campionato, key="squadra_casa")
with colonna_ospite:
    opzioni_ospite = [s for s in squadre_nel_campionato if s != squadra_casa]
    squadra_ospite = st.selectbox("Squadra ospite", opzioni_ospite, key="squadra_ospite")


# --- Sezione 3: calcolo Poisson/Elo ---
st.header("3. Motore quantitativo (Poisson / Elo)")

if st.button("Calcola probabilità", type="primary"):
    try:
        medie = poisson_model.calcola_medie_campionato(storico, campionato_selezionato)
        forza = poisson_model.calcola_forza_squadre(storico, campionato_selezionato)
        lam_casa, lam_ospite = poisson_model.calcola_lambda_partita(
            forza, medie, squadra_casa, squadra_ospite
        )
        matrice = poisson_model.matrice_probabilita_risultati(lam_casa, lam_ospite)
        prob_1x2 = poisson_model.probabilita_1x2(matrice)
        prob_ou_25 = poisson_model.probabilita_over_under(matrice, soglia=2.5)

        # Salvo in session_state così le sezioni successive (EV, commento
        # rischio) possono usare questi risultati senza ricalcolarli ad
        # ogni interazione dell'utente con altri widget della pagina.
        st.session_state["ultima_analisi"] = {
            "squadra_casa": squadra_casa,
            "squadra_ospite": squadra_ospite,
            "campionato": campionato_selezionato,
            "lambda_casa": lam_casa,
            "lambda_ospite": lam_ospite,
            "prob_1x2": prob_1x2,
            "prob_ou_25": prob_ou_25,
        }
    except ValueError as e:
        st.error(f"Impossibile calcolare: {e}")
        st.stop()

if "ultima_analisi" in st.session_state:
    analisi = st.session_state["ultima_analisi"]

    if analisi["squadra_casa"] == squadra_casa and analisi["squadra_ospite"] == squadra_ospite:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Gol attesi casa", f"{analisi['lambda_casa']:.2f}")
        col_b.metric("Gol attesi ospite", f"{analisi['lambda_ospite']:.2f}")
        col_c.metric(
            "Totale gol attesi",
            f"{analisi['lambda_casa'] + analisi['lambda_ospite']:.2f}",
        )

        st.subheader("Probabilità 1X2")
        prob_1x2 = analisi["prob_1x2"]
        col_1, col_x, col_2 = st.columns(3)
        col_1.metric(f"1 ({squadra_casa})", f"{prob_1x2['VittoriaCasa']*100:.1f}%")
        col_x.metric("X (Pareggio)", f"{prob_1x2['Pareggio']*100:.1f}%")
        col_2.metric(f"2 ({squadra_ospite})", f"{prob_1x2['VittoriaOspite']*100:.1f}%")

        st.subheader("Over/Under 2.5")
        prob_ou = analisi["prob_ou_25"]
        col_under, col_over = st.columns(2)
        col_under.metric("Under 2.5", f"{prob_ou['Under2.5']*100:.1f}%")
        col_over.metric("Over 2.5", f"{prob_ou['Over2.5']*100:.1f}%")

        st.caption(
            "Queste probabilità sono stime statistiche da dati storici (modello Poisson "
            "indipendente). Non considerano infortuni, meteo, motivazioni: per quello "
            "vedi la sezione 'Commento di rischio' più sotto, che è un'analisi testuale "
            "separata, non un correttivo numerico a questi valori."
        )
    else:
        st.info("Hai cambiato la selezione delle squadre: premi 'Calcola probabilità' per aggiornare i risultati.")


# --- Sezione 4: confronto con quote di mercato (EV) ---
st.header("4. Value Betting (EV vs quote di mercato)")

if "ultima_analisi" not in st.session_state:
    st.info("Calcola prima le probabilità nella sezione 3.")
else:
    analisi = st.session_state["ultima_analisi"]
    prob_1x2 = analisi["prob_1x2"]

    modalita_quote = st.radio(
        "Origine delle quote",
        ["Recupera automaticamente (The Odds API)", "Inserisci manualmente"],
        horizontal=True,
    )

    quota_1, quota_x, quota_2 = None, None, None

    if modalita_quote == "Recupera automaticamente (The Odds API)":
        if st.button("Recupera quote"):
            try:
                import odds_fetcher
                with st.spinner("Recupero quote in corso..."):
                    partite_con_quote = odds_fetcher.recupera_partite_con_quote(campionato_selezionato)
                    esito_match = odds_fetcher.trova_partita_corrispondente(
                        partite_con_quote, squadra_casa, squadra_ospite
                    )

                if esito_match["esito"] == "non_trovata":
                    st.warning(
                        f"Nessuna partita trovata su The Odds API che corrisponda a "
                        f"'{squadra_casa}' vs '{squadra_ospite}'. Possibili motivi: la partita "
                        f"non è ancora coperta dai bookmaker, oppure i nomi squadra nel tuo CSV "
                        f"sono troppo diversi da quelli usati dall'API. Passa a 'Inserisci "
                        f"manualmente' per procedere comunque."
                    )
                elif esito_match["esito"] == "ambigua":
                    st.warning(
                        "Trovate più partite con confidenza simile, non scelgo automaticamente "
                        "quale sia quella giusta:"
                    )
                    for candidato in esito_match["candidati"]:
                        p = candidato["partita"]
                        st.write(f"- {p['squadra_casa']} vs {p['squadra_ospite']} "
                                 f"(confidenza: {candidato['punteggio_confidenza']})")
                    st.info("Passa a 'Inserisci manualmente' se nessuna di queste è corretta, "
                            "oppure verifica i nomi squadra nel tuo CSV storico.")
                else:
                    partita_trovata = esito_match["partita"]
                    st.session_state["quote_recuperate"] = odds_fetcher.estrai_quote_1x2_medie(partita_trovata)
                    st.session_state["quote_recuperate"]["confidenza_match"] = esito_match["punteggio_confidenza"]

            except config.ChiaveMancanteError as e:
                st.error(str(e))
            except ValueError as e:
                st.error(f"Errore: {e}")
            except Exception as e:
                st.error(f"Errore nel recupero quote: {e}")

        if "quote_recuperate" in st.session_state:
            qr = st.session_state["quote_recuperate"]
            st.success(
                f"Quote recuperate (media di {qr['n_bookmaker']} bookmaker, "
                f"confidenza match squadre: {qr['confidenza_match']})"
            )
            quota_1, quota_x, quota_2 = qr["quota_1"], qr["quota_x"], qr["quota_2"]
            col_q1, col_qx, col_q2 = st.columns(3)
            col_q1.metric("Quota 1", quota_1)
            col_qx.metric("Quota X", quota_x if quota_x else "N/D")
            col_q2.metric("Quota 2", quota_2)

    else:
        col_quota_1, col_quota_x, col_quota_2 = st.columns(3)
        with col_quota_1:
            quota_1 = st.number_input("Quota 1 (vittoria casa)", min_value=1.01, value=2.00, step=0.01)
        with col_quota_x:
            quota_x = st.number_input("Quota X (pareggio)", min_value=1.01, value=3.20, step=0.01)
        with col_quota_2:
            quota_2 = st.number_input("Quota 2 (vittoria ospite)", min_value=1.01, value=3.80, step=0.01)

    if quota_1 is not None and quota_x is not None and quota_2 is not None:
        if st.button("Calcola EV"):
            # EV = (probabilità stimata * quota) - 1. Calcolo diretto,
            # nessun coinvolgimento dell'IA in questo passaggio: è
            # matematica pura sulle probabilità già calcolate da Poisson.
            ev_1 = (prob_1x2["VittoriaCasa"] * quota_1) - 1
            ev_x = (prob_1x2["Pareggio"] * quota_x) - 1
            ev_2 = (prob_1x2["VittoriaOspite"] * quota_2) - 1

            df_ev = pd.DataFrame([
                {"Mercato": f"1 ({squadra_casa})", "Probabilità": f"{prob_1x2['VittoriaCasa']*100:.1f}%", "Quota": quota_1, "EV": f"{ev_1*100:+.1f}%"},
                {"Mercato": "X (Pareggio)", "Probabilità": f"{prob_1x2['Pareggio']*100:.1f}%", "Quota": quota_x, "EV": f"{ev_x*100:+.1f}%"},
                {"Mercato": f"2 ({squadra_ospite})", "Probabilità": f"{prob_1x2['VittoriaOspite']*100:.1f}%", "Quota": quota_2, "EV": f"{ev_2*100:+.1f}%"},
            ])
            st.dataframe(df_ev, use_container_width=True, hide_index=True)

            ev_massimo = max(ev_1, ev_x, ev_2)
            if ev_massimo >= bm.EV_MINIMO_PER_PROCEDERE:
                st.success(
                    f"Almeno un mercato supera la soglia minima di EV "
                    f"({bm.EV_MINIMO_PER_PROCEDERE*100:.0f}%) configurata nel bankroll manager. "
                    f"Questo NON è un consiglio di puntata: è un confronto matematico tra la "
                    f"probabilità stimata e la quota offerta. Vai alla sezione Diario per "
                    f"calcolare uno stake suggerito, se decidi di procedere."
                )
            else:
                st.warning(
                    "Nessun mercato supera la soglia minima di EV configurata. Ricorda: un EV "
                    "positivo qui dipende dall'accuratezza della probabilità Poisson, che è una "
                    "stima da dati storici, non un valore certo."
                )


# --- Sezione 5: commento di rischio qualitativo ---
st.header("5. Commento di rischio (qualitativo)")
st.caption(
    "Genera un commento testuale basato su notizie pre-partita reperite via ricerca web "
    "(non sentiment di social/forum). Questo commento non modifica le probabilità calcolate "
    "sopra: è un'analisi separata che leggi accanto al dato statistico, non un correttivo "
    "fuso in un unico numero."
)

manuale_imprenditore = st.text_area(
    "Il tuo Manuale (direttive su quali rischi prioritizzare)",
    placeholder="Es: Dai priorità ai rischi che riguardano portieri e difensori centrali...",
    height=100,
)

contesto_manuale = st.text_area(
    "Dati grezzi pre-partita (infortuni, formazioni, meteo)",
    placeholder="Incolla qui notizie o dati raccolti manualmente, oppure collega match_finder.py "
                "per la ricerca automatica (vedi modules/match_finder.py).",
    height=150,
)

if st.button("Genera commento di rischio"):
    if "ultima_analisi" not in st.session_state:
        st.error("Calcola prima le probabilità nella sezione 3.")
    elif not contesto_manuale.strip():
        st.warning("Inserisci almeno qualche dato grezzo pre-partita, altrimenti il commento "
                   "non avrebbe nulla su cui basarsi.")
    else:
        try:
            import risk_commentary
            analisi = st.session_state["ultima_analisi"]
            with st.spinner("Generazione commento in corso..."):
                contesto_dict = {
                    "infortuni_e_formazioni": [contesto_manuale],
                    "meteo": [],
                }
                commento = risk_commentary.genera_commento_rischio(
                    squadra_casa=squadra_casa,
                    squadra_ospite=squadra_ospite,
                    contesto_prepartita=contesto_dict,
                    manuale_imprenditore=manuale_imprenditore or "Nessuna direttiva specifica fornita.",
                    lambda_casa=analisi["lambda_casa"],
                    lambda_ospite=analisi["lambda_ospite"],
                )
            st.markdown(commento)
        except config.ChiaveMancanteError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Errore nella generazione del commento: {e}")
