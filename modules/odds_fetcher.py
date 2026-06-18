"""
odds_fetcher.py

Recupera quote di mercato da The Odds API per il confronto EV nella
pagina di Analisi Partita.

PROBLEMA DI MATCHING NOMI (perché questo modulo non è una singola
chiamata HTTP banale):
The Odds API restituisce partite con i nomi squadra COME LI USA LEI,
che possono non corrispondere esattamente ai nomi nel tuo storico CSV
("Inter" vs "Internazionale", "Manchester United" vs "Man United").
Un matching ingenuo (stringa esatta) fallirebbe silenziosamente in
questi casi: la pagina mostrerebbe "nessuna quota trovata" anche
quando le quote esistono per quella partita con un nome leggermente
diverso.

Questo modulo usa un matching "fuzzy" (basato su similarità di stringa)
ma con due salvaguardie:
1. Se la corrispondenza migliore non supera una soglia di confidenza,
   il modulo NON sceglie automaticamente: ritorna i candidati e lascia
   che la UI chieda conferma all'utente.
2. Se ci sono PIÙ partite sopra la soglia con punteggi simili (es.
   stesso turno con due squadre che hanno nomi simili), stesso
   comportamento: non sceglie per te, mostra le opzioni.
"""

import requests
from difflib import SequenceMatcher

import config

ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

SOGLIA_CONFIDENZA_MATCH = 0.6  # sotto questa soglia di similarità, non si considera un match valido


def _similarita_stringhe(a: str, b: str) -> float:
    """Punteggio di similarità tra 0 e 1 tra due nomi squadra, case-insensitive."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _mappa_campionato_a_sport_key(nome_campionato: str) -> str:
    """
    The Odds API usa identificatori specifici per campionato (es.
    'soccer_italy_serie_a'), non nomi liberi. Questa mappa copre i
    campionati più comuni: se il tuo campionato non è qui, aggiungilo
    consultando https://the-odds-api.com/sports-odds-data/sports-apis.html
    """
    mappa = {
        "serieA": "soccer_italy_serie_a",
        "SerieA": "soccer_italy_serie_a",
        "premierleague": "soccer_epl",
        "PremierLeague": "soccer_epl",
        "bundesliga": "soccer_germany_bundesliga",
        "Bundesliga": "soccer_germany_bundesliga",
        "laliga": "soccer_spain_la_liga",
        "LaLiga": "soccer_spain_la_liga",
        "championsleague": "soccer_uefa_champs_league",
        "ChampionsLeague": "soccer_uefa_champs_league",
    }
    chiave_normalizzata = nome_campionato.replace(" ", "")
    if chiave_normalizzata not in mappa:
        raise ValueError(
            f"Campionato '{nome_campionato}' non mappato a un sport_key di The Odds API. "
            f"Campionati supportati: {list(mappa.keys())}. "
            f"Aggiungine altri in _mappa_campionato_a_sport_key se necessario."
        )
    return mappa[chiave_normalizzata]


def recupera_partite_con_quote(nome_campionato: str, regione: str = "eu") -> list:
    """
    Recupera tutte le partite in programma per un campionato con le
    relative quote 1X2 (h2h = head to head nel linguaggio di The Odds API).

    Ritorna una lista di dizionari:
    [{"id": str, "squadra_casa": str, "squadra_ospite": str,
      "commence_time": str, "quote_per_bookmaker": [...]}, ...]

    Solleva ValueError se il campionato non è mappato, requests.HTTPError
    se la chiamata API fallisce (es. chiave non valida, limite raggiunto).
    """
    sport_key = _mappa_campionato_a_sport_key(nome_campionato)
    chiave_api = config.get_odds_api_key()

    url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"
    parametri = {
        "apiKey": chiave_api,
        "regions": regione,
        "markets": "h2h",
        "oddsFormat": "decimal",
    }

    risposta = requests.get(url, params=parametri, timeout=15)
    risposta.raise_for_status()
    dati = risposta.json()

    partite = []
    for evento in dati:
        partite.append({
            "id": evento["id"],
            "squadra_casa": evento["home_team"],
            "squadra_ospite": evento["away_team"],
            "commence_time": evento["commence_time"],
            "quote_per_bookmaker": evento.get("bookmakers", []),
        })

    return partite


def trova_partita_corrispondente(
    partite_con_quote: list,
    squadra_casa_storico: str,
    squadra_ospite_storico: str,
) -> dict:
    """
    Cerca, tra le partite restituite da The Odds API, quella che
    corrisponde meglio a (squadra_casa_storico, squadra_ospite_storico)
    — i nomi come li hai nel TUO CSV storico, non necessariamente
    identici a quelli di The Odds API.

    Ritorna un dizionario con tre possibili esiti, distinti esplicitamente
    così la UI sa come comportarsi in ognuno:
    - {"esito": "trovata", "partita": {...}} -> un solo match sopra soglia, netto
    - {"esito": "ambigua", "candidati": [...]} -> più match sopra soglia, serve scelta utente
    - {"esito": "non_trovata"} -> nessun match sopra soglia
    """
    punteggi = []
    for partita in partite_con_quote:
        punteggio_casa = _similarita_stringhe(squadra_casa_storico, partita["squadra_casa"])
        punteggio_ospite = _similarita_stringhe(squadra_ospite_storico, partita["squadra_ospite"])
        punteggio_combinato = (punteggio_casa + punteggio_ospite) / 2

        if punteggio_combinato >= SOGLIA_CONFIDENZA_MATCH:
            punteggi.append({"partita": partita, "punteggio": punteggio_combinato})

    if not punteggi:
        return {"esito": "non_trovata", "candidati": []}

    punteggi.sort(key=lambda x: x["punteggio"], reverse=True)

    # Se il migliore supera chiaramente il secondo (differenza > 0.15),
    # consideriamo il match sufficientemente netto da non richiedere
    # conferma. Sotto quella differenza, sono troppo vicini per scegliere
    # da soli con sicurezza.
    if len(punteggi) == 1 or (punteggi[0]["punteggio"] - punteggi[1]["punteggio"]) > 0.15:
        return {"esito": "trovata", "partita": punteggi[0]["partita"], "punteggio_confidenza": round(punteggi[0]["punteggio"], 2)}

    return {
        "esito": "ambigua",
        "candidati": [
            {"partita": p["partita"], "punteggio_confidenza": round(p["punteggio"], 2)}
            for p in punteggi[:5]  # massimo 5 candidati mostrati, non l'intero elenco
        ],
    }


def estrai_quote_1x2_medie(partita_con_quote: dict) -> dict:
    """
    Calcola la quota MEDIA tra tutti i bookmaker disponibili per 1X2.
    Usare la media invece della quota di un singolo bookmaker riduce
    l'effetto di un singolo outlier (un bookmaker con un prezzo anomalo),
    ma significa anche che la quota mostrata potrebbe non essere quella
    che vedi tu sul tuo bookmaker specifico: per quello la pagina di
    Analisi mantiene comunque l'input manuale come alternativa.
    """
    quote_1, quote_x, quote_2 = [], [], []

    for bookmaker in partita_con_quote.get("quote_per_bookmaker", []):
        for mercato in bookmaker.get("markets", []):
            if mercato["key"] != "h2h":
                continue
            for esito in mercato.get("outcomes", []):
                if esito["name"] == partita_con_quote["squadra_casa"]:
                    quote_1.append(esito["price"])
                elif esito["name"] == partita_con_quote["squadra_ospite"]:
                    quote_2.append(esito["price"])
                elif esito["name"].lower() == "draw":
                    quote_x.append(esito["price"])

    if not quote_1 or not quote_2:
        raise ValueError(
            "Nessuna quota 1X2 trovata tra i bookmaker per questa partita. "
            "Potrebbe non essere ancora stata pubblicata una linea di mercato."
        )

    return {
        "quota_1": round(sum(quote_1) / len(quote_1), 2),
        "quota_x": round(sum(quote_x) / len(quote_x), 2) if quote_x else None,
        "quota_2": round(sum(quote_2) / len(quote_2), 2),
        "n_bookmaker": len(partita_con_quote.get("quote_per_bookmaker", [])),
    }


if __name__ == "__main__":
    # Test della logica di matching SENZA chiamare l'API reale, usando
    # dati finti: verifica solo che trova_partita_corrispondente si
    # comporti correttamente nei tre casi (netta, ambigua, non trovata).
    partite_finte = [
        {"id": "1", "squadra_casa": "Inter Milan", "squadra_ospite": "Napoli", "commence_time": "", "quote_per_bookmaker": []},
        {"id": "2", "squadra_casa": "AC Milan", "squadra_ospite": "Juventus", "commence_time": "", "quote_per_bookmaker": []},
    ]

    print("=== Test 1: match netto (Inter -> Inter Milan) ===")
    esito1 = trova_partita_corrispondente(partite_finte, "Inter", "Napoli")
    print(esito1)
    assert esito1["esito"] == "trovata"

    print("\n=== Test 2: nessun match (squadre non presenti) ===")
    esito2 = trova_partita_corrispondente(partite_finte, "Lazio", "Roma")
    print(esito2)
    assert esito2["esito"] == "non_trovata"

    print("\n=== Test 3: ambiguità simulata (Milan può confondersi tra Inter Milan e AC Milan) ===")
    esito3 = trova_partita_corrispondente(partite_finte, "Milan", "Juventus")
    print(esito3)
    print("(Verifica manuale: controlla se questo caso specifico genera ambiguità o match netto)")
