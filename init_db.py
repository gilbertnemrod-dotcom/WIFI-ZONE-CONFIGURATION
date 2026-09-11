"""
Étape 1 : créer la base de données et y charger les tickets.
À exécuter une seule fois (ou à chaque fois que tu ajoutes de nouveaux tickets).
"""

import sqlite3
import csv

DB_PATH = "tickets.db"
CSV_PATH = "tickets.csv"


def creer_table():
    """Crée la table 'tickets' si elle n'existe pas encore."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            duree_jours INTEGER NOT NULL,
            prix INTEGER NOT NULL,
            statut TEXT NOT NULL DEFAULT 'disponible',
            date_vente TEXT,
            numero_client TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("Table 'tickets' prête.")


def charger_csv():
    """Lit tickets.csv et insère les nouveaux tickets dans la base."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    ajoutes = 0
    ignores = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for ligne in reader:
            try:
                cur.execute(
                    """INSERT INTO tickets (code, duree_jours, prix, statut)
                       VALUES (?, ?, ?, ?)""",
                    (ligne["code"], int(ligne["duree_jours"]),
                     int(ligne["prix"]), ligne["statut"])
                )
                ajoutes += 1
            except sqlite3.IntegrityError:
                # Le code existe déjà (colonne UNIQUE) -> on ne le réinsère pas
                ignores += 1

    conn.commit()
    conn.close()
    print(f"{ajoutes} ticket(s) ajouté(s), {ignores} déjà présent(s) et ignoré(s).")


if __name__ == "__main__":
    creer_table()
    charger_csv()
