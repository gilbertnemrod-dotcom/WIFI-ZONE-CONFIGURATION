"""
Étape 3 : le serveur Flask.

Deux routes :
- POST /acheter  : le client indique son numéro + la catégorie voulue.
                    Pour l'instant (sans PayGateGlobal branché), on
                    simule juste la création d'une "demande de paiement"
                    et on répond avec un identifiant de transaction.
- POST /webhook   : simule la confirmation de paiement de PayGateGlobal.
                    C'est CETTE route qui distribue réellement le ticket.

Rien ici ne parle encore à PayGateGlobal -- c'est fait exprès, pour
pouvoir tout tester à 0 FCFA avant de brancher le vrai paiement.
"""

from flask import Flask, request, jsonify, render_template
from distribution import distribuer_ticket, stock_par_categorie, AucunTicketDisponible
from init_db import creer_table, charger_csv
import sqlite3
import uuid
from datetime import datetime

app = Flask(__name__)

DB_PATH = "tickets.db"
CATEGORIES_VALIDES = {100, 200, 300, 500, 2000}


def init_table_transactions():
    """Table qui garde une trace de chaque demande de paiement en attente."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            numero_client TEXT NOT NULL,
            prix_categorie INTEGER NOT NULL,
            statut TEXT NOT NULL DEFAULT 'en_attente',
            date_creation TEXT NOT NULL,
            code_ticket TEXT
        )
    """)
    conn.commit()
    conn.close()


# Tout ceci doit s'exécuter au CHARGEMENT DU MODULE, pas seulement en
# lancement direct (python3 app.py) -- car sur Render, c'est gunicorn
# qui importe ce module, le bloc "if __name__ == '__main__'" plus bas
# n'est jamais exécuté. Sans ces 3 lignes, la base reste vide en
# production : table 'tickets' inexistante -> /stock échoue -> la
# page reste blanche côté client.
creer_table()
charger_csv()
init_table_transactions()


@app.route("/", methods=["GET"])
def accueil():
    """Page que le vendeur ouvrira pour tester -- choix de catégorie."""
    return render_template("index.html")


@app.route("/simuler-paiement", methods=["GET"])
def simuler_paiement():
    """
    Page qui remplace visuellement l'écran Flooz/T-Money le temps
    que PayGateGlobal ne soit pas branché. Boutons "réussi"/"échoué"
    qui appellent /webhook, exactement comme le ferait PayGateGlobal.
    """
    return render_template("simuler_paiement.html")


@app.route("/acheter", methods=["POST"])
def acheter():
    """
    Le client (ou l'app cliente) envoie :
    { "numero_client": "+22890000001", "prix_categorie": 500 }

    On crée une transaction 'en_attente' et on renvoie son identifiant.
    En vrai (plus tard), c'est ici qu'on appellerait l'API PayGateGlobal
    pour générer le lien de paiement Flooz/TMoney.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"erreur": "Corps JSON manquant ou invalide."}), 400

    numero_client = data.get("numero_client")
    prix_categorie = data.get("prix_categorie")

    if not numero_client:
        return jsonify({"erreur": "numero_client requis."}), 400
    if prix_categorie not in CATEGORIES_VALIDES:
        return jsonify({
            "erreur": f"prix_categorie invalide. Valeurs acceptées : {sorted(CATEGORIES_VALIDES)}"
        }), 400

    # Vérifier qu'il reste du stock AVANT de créer la transaction
    # (évite de faire payer un client pour rien)
    stock = stock_par_categorie()
    if stock.get(prix_categorie, 0) == 0:
        return jsonify({
            "erreur": f"Aucun ticket disponible pour la catégorie {prix_categorie} FCFA."
        }), 409

    transaction_id = str(uuid.uuid4())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions (id, numero_client, prix_categorie, statut, date_creation)
        VALUES (?, ?, ?, 'en_attente', ?)
    """, (transaction_id, numero_client, prix_categorie, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    # Plus tard : ici on appellerait PayGateGlobal et on renverrait
    # le vrai lien de paiement. Pour l'instant on renvoie juste l'ID.
    return jsonify({
        "transaction_id": transaction_id,
        "numero_client": numero_client,
        "prix_categorie": prix_categorie,
        "statut": "en_attente",
        "message": "Simulation : en vrai, un lien de paiement PayGateGlobal serait renvoyé ici."
    }), 201


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Simule ce que PayGateGlobal appellerait une fois le paiement confirmé.
    En vrai, il faudra vérifier une SIGNATURE pour être sûr que l'appel
    vient bien de PayGateGlobal et pas d'un tiers malveillant -- pour
    l'instant, en test local, on s'en passe.

    Attendu :
    { "transaction_id": "...", "statut_paiement": "confirme" }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"erreur": "Corps JSON manquant ou invalide."}), 400

    transaction_id = data.get("transaction_id")
    statut_paiement = data.get("statut_paiement")

    if not transaction_id:
        return jsonify({"erreur": "transaction_id requis."}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT numero_client, prix_categorie, statut FROM transactions
        WHERE id = ?
    """, (transaction_id,))
    row = cur.fetchone()

    if row is None:
        conn.close()
        return jsonify({"erreur": "Transaction inconnue."}), 404

    numero_client, prix_categorie, statut_actuel = row

    if statut_actuel != "en_attente":
        # Sécurité importante : un webhook peut être appelé plusieurs fois
        # (PayGateGlobal peut réessayer en cas de doute). Il ne faut JAMAIS
        # redistribuer un ticket pour une transaction déjà traitée.
        conn.close()
        return jsonify({
            "erreur": f"Transaction déjà traitée (statut actuel : {statut_actuel}).",
            "traitement_ignore": True
        }), 409

    if statut_paiement != "confirme":
        cur.execute("UPDATE transactions SET statut = 'echoue' WHERE id = ?", (transaction_id,))
        conn.commit()
        conn.close()
        return jsonify({"statut": "echoue", "message": "Paiement non confirmé."}), 200

    conn.close()  # on ferme avant d'appeler distribuer_ticket, qui ouvre sa propre connexion

    try:
        ticket = distribuer_ticket(numero_client, prix_categorie)
    except AucunTicketDisponible:
        # Cas rare mais réel : le stock s'est épuisé entre la création
        # de la transaction et la confirmation du paiement.
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE transactions SET statut = 'stock_epuise' WHERE id = ?", (transaction_id,))
        conn.commit()
        conn.close()
        return jsonify({
            "statut": "stock_epuise",
            "message": "Paiement confirmé mais stock épuisé -- remboursement à prévoir."
        }), 409

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        UPDATE transactions SET statut = 'complete', code_ticket = ? WHERE id = ?
    """, (ticket["code"], transaction_id))
    conn.commit()
    conn.close()

    # Plus tard : ici on enverrait le code par SMS/WhatsApp au lieu
    # de simplement le renvoyer dans la réponse HTTP.
    return jsonify({
        "statut": "complete",
        "ticket": ticket,
        "message": "Simulation : en vrai, ce code serait envoyé par SMS ici."
    }), 200


@app.route("/stock", methods=["GET"])
def stock():
    """Route utilitaire pour voir le stock en direct pendant les tests."""
    return jsonify(stock_par_categorie())


if __name__ == "__main__":
    # debug=False : ne jamais exposer le débogueur Flask publiquement.
    # host=0.0.0.0 : nécessaire pour que Render puisse atteindre le serveur.
    app.run(debug=False, host="0.0.0.0", port=5000)
