"""
Étape 2 : distribuer un ticket de façon sûre.

Le point critique : si deux paiements arrivent en même temps (ou presque),
il ne faut JAMAIS que deux clients reçoivent le même ticket.
On règle ça avec une transaction SQLite atomique : la sélection ET le
marquage "vendu" se font en une seule opération indivisible.
"""

import sqlite3
from datetime import datetime

DB_PATH = "tickets.db"


class AucunTicketDisponible(Exception):
    """Levée quand le stock est vide."""
    pass


def distribuer_ticket(numero_client: str, prix_categorie: int) -> dict:
    """
    Prend le premier ticket 'disponible' DE LA CATÉGORIE DEMANDÉE
    (filtré par prix), le marque 'vendu' et l'attribue au client.

    prix_categorie doit correspondre exactement à une des catégories
    vendues (100, 200, 300, 500, 2000, ...). Un client qui paie 500F
    ne peut recevoir qu'un ticket où prix=500 -- jamais un autre.

    Sûr en cas d'appels simultanés (concurrence) grâce à :
    - isolation_level par défaut de sqlite3 (transaction implicite)
    - une clause WHERE statut='disponible' dans l'UPDATE lui-même,
      qui garantit qu'un ticket déjà pris par un autre appel ne peut
      pas être repris.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()

    try:
        # On sélectionne UN ticket candidat DANS LA BONNE CATÉGORIE
        cur.execute("""
            SELECT id, code, duree_jours, prix FROM tickets
            WHERE statut = 'disponible' AND prix = ?
            ORDER BY id
            LIMIT 1
        """, (prix_categorie,))
        ticket = cur.fetchone()

        if ticket is None:
            raise AucunTicketDisponible(
                f"Stock épuisé pour la catégorie {prix_categorie} FCFA."
            )

        ticket_id, code, duree_jours, prix = ticket

        # On tente de le marquer 'vendu' — la clause WHERE statut='disponible'
        # est la protection réelle : si un autre processus l'a déjà pris
        # entre le SELECT et maintenant, rowcount sera 0 et on retente.
        cur.execute("""
            UPDATE tickets
            SET statut = 'vendu', date_vente = ?, numero_client = ?
            WHERE id = ? AND statut = 'disponible'
        """, (datetime.now().isoformat(), numero_client, ticket_id))

        if cur.rowcount == 0:
            # Quelqu'un d'autre a pris ce ticket entre-temps -> on retente
            conn.rollback()
            conn.close()
            return distribuer_ticket(numero_client, prix_categorie)

        conn.commit()
        conn.close()

        return {
            "code": code,
            "duree_jours": duree_jours,
            "prix": prix,
            "numero_client": numero_client,
        }

    except Exception:
        conn.rollback()
        conn.close()
        raise


def stock_disponible(prix_categorie: int = None) -> int:
    """
    Retourne le nombre de tickets disponibles.
    Si prix_categorie est fourni, ne compte que cette catégorie.
    Sinon, retourne le total toutes catégories confondues.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if prix_categorie is None:
        cur.execute("SELECT COUNT(*) FROM tickets WHERE statut = 'disponible'")
    else:
        cur.execute(
            "SELECT COUNT(*) FROM tickets WHERE statut = 'disponible' AND prix = ?",
            (prix_categorie,)
        )
    n = cur.fetchone()[0]
    conn.close()
    return n


def stock_par_categorie() -> dict:
    """Retourne un dict {prix: quantité disponible} pour toutes les catégories."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT prix, COUNT(*) FROM tickets
        WHERE statut = 'disponible'
        GROUP BY prix
        ORDER BY prix
    """)
    resultat = dict(cur.fetchall())
    conn.close()
    return resultat
