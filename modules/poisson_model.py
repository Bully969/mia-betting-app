def calcola_medie_campionato(storico, campionato): return 1.5, 1.2
def calcola_forza_squadre(storico, campionato): return {}
def calcola_lambda_partita(forza, medie, casa, ospite): return 1.5, 1.2
def matrice_probabilita_risultati(lam_c, lam_o): return {}
def probabilita_1x2(matrice): return {"VittoriaCasa": 0.4, "Pareggio": 0.3, "VittoriaOspite": 0.3}
def probabilita_over_under(matrice, soglia): return {"Under2.5": 0.5, "Over2.5": 0.5}