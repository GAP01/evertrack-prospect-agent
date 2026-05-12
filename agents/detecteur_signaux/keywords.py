"""
Lexique de détection et pondérations de sources.

Séparé du reste pour être facilement ajustable sans toucher au code.
"""

from __future__ import annotations


# --- Mots-clés positifs : symptômes sanitaires agroalimentaires ----------

# Utilisés pour :
#   1. Construire les requêtes Google News / Reddit
#   2. Filtrer les résultats (au moins 1 mot-clé doit apparaître)
SYMPTOM_KEYWORDS = [
    # Pathogènes / contaminations biologiques
    "rappel produit", "rappel alimentaire", "contamination alimentaire",
    "listeria", "listeriose",
    "salmonelle", "salmonellose",
    "e.coli", "escherichia coli",
    "botulisme",
    "norovirus",
    # Corps étrangers
    "corps étranger", "morceau de verre", "fragment de plastique", "fragment de metal",
    # Allergènes
    "allergène non déclaré", "allergène non mentionné",
    # Contamination chimique
    "moisissure", "toxine",
    # Générique
    "intoxication alimentaire", "retrait produit",
]

# Requêtes Google News (1 par thématique, combine mots-clés)
GOOGLE_NEWS_QUERIES = [
    '"rappel produit" OR "rappel alimentaire"',
    '"listeria" OR "listeriose"',
    '"salmonelle" OR "salmonellose"',
    '"intoxication alimentaire"',
    '"corps étranger" aliment',
    '"allergène non déclaré" OR "allergène non mentionné"',
    '"e.coli" produit alimentaire',
    '"moisissure" rappel',
]

# Subreddits à monitorer (FR, généralistes — pas de sub agro spécialisé)
REDDIT_SUBREDDITS = ["france", "Consommateurs", "AskFrance"]

# Mots-clés utilisés pour filtrer les posts Reddit
REDDIT_QUERIES = [
    "rappel",
    "listeria",
    "salmonelle",
    "intoxication alimentaire",
    "corps étranger aliment",
    "allergène non déclaré",
]


# --- Filtres négatifs : faux positifs courants ---------------------------

# Si une de ces expressions apparait dans le titre, on exclut le signal
NEGATIVE_FILTERS = [
    "rappel à l'ordre",
    "rappel des chiens",
    "rappel des troupes",
    "rappel de mémoire",
    "rappel de vaccin",
    "rappel vaccinal",
    "rappel à l'ordre",
    "piqûre de rappel",
    "rappel médicaments",  # hors scope EverTrack (alim seulement)
    "rappel d'automobile",
    "rappel voiture",
    "rappel véhicule",
    "rappel automobile",
    "rappel constructeur",
    "rappel de jouet",     # hors scope alim
]


# --- Pondérations de sources (score source_weight, max 35) ---------------

# Clés = pattern à chercher dans source_name (lower, contains)
# Val   = poids [0-35]
SOURCE_WEIGHTS = {
    # Presse pro agro (forte crédibilité)
    "lsa": 30,
    "lsa conso": 30,
    "process alimentaire": 30,
    "processalimentaire": 30,
    "rayon boissons": 28,
    "linéaires": 28,
    "rungis": 25,
    "agroligne": 25,
    "la revue de l'alimentation": 25,
    # Presse généraliste nationale (forte)
    "le monde": 28,
    "lemonde": 28,
    "le figaro": 25,
    "lefigaro": 25,
    "le parisien": 22,
    "liberation": 22,
    "libération": 22,
    "la tribune": 22,
    "les échos": 25,
    "les echos": 25,
    "france info": 22,
    "franceinfo": 22,
    "bfmtv": 20,
    "tf1 info": 22,
    "tf1": 20,
    "france 3": 20,
    "france 2": 22,
    "europe 1": 20,
    "rtl": 20,
    "rmc": 20,
    # Consommation / vulgarisation
    "60 millions de consommateurs": 25,
    "60 millions": 25,
    "que choisir": 25,
    "quechoisir": 25,
    "ufc-que-choisir": 25,
    "ouest-france": 20,
    "sud ouest": 18,
    "la voix du nord": 18,
    "la dépêche": 18,
    "dna": 18,
    "midi libre": 18,
    "la provence": 18,
    # Presse régionale générique
    "actu.fr": 15,
    "francebleu": 15,
    # Cuisine / lifestyle qui relaient fiablement RappelConso
    "marmiton": 18,
    "cuisine az": 17,
    "cuisineaz": 17,
    "750g": 15,
    "femme actuelle": 18,
    "elle": 15,
    "closer": 12,
    "cosmopolitan": 12,
    "melty": 12,
    "aufeminin": 15,
    "marie claire": 15,
    # Presse régionale moins connue (relais RappelConso)
    "le courrier cauchois": 15,
    "lecourriercauchois": 15,
    "le journal des entreprises": 18,
    "paris normandie": 15,
    "la manche libre": 15,
    "le télégramme": 18,
    "le progrès": 16,
    "l'indépendant": 16,
    "nice-matin": 16,
    "var-matin": 15,
    "la nouvelle république": 16,
    "corse-matin": 15,
    "7sur7": 14,
    "rtbf": 16,
    # SignalConso (DGCCRF) — plaintes brutes consommateurs.
    # Poids bas au démarrage (calibration à observer après 2-3 semaines).
    "signalconso": 12,
    # Reddit (contexte informel, mais peut révéler tôt)
    "r/france": 15,
    "r/consommateurs": 18,
    "r/askfrance": 12,
    # TikTok (comptes officiels pondérés plus haut que le flux générique)
    "tiktok": 10,
    "tiktok @60millions": 25,
    "tiktok @dgccrf": 30,
}

# Score par défaut pour source inconnue (calibré à 12 : Google News relaie
# beaucoup de presse régionale pas forcément dans le dico mais crédible)
DEFAULT_SOURCE_WEIGHT = 12

# --- Hashtags TikTok (sans #, ASCII uniquement) ---------------------------

# Utilisés pour construire les requêtes TikTok API / scraping.
# Ordre : du plus ciblé rappel officiel au plus générique santé.
TIKTOK_HASHTAGS = [
    "rappelproduit", "rappelconso", "intoxalimentaire",
    "salmonelle", "listeria", "alertealimentaire",
    "produitcontamine", "alimentdangereux",
]

# Comptes TikTok cibles pour le tier 1 RSS-Bridge (mode "By user").
# RSS-Bridge stock supporte uniquement le mode user, pas hashtag.
# Source haute valeur : presse conso, autorites, organismes verifies.
TIKTOK_BRIDGE_USERS = [
    "60millions",
]
