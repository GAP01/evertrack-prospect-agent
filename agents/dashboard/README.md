# Dashboard EverTrack

Interface Streamlit qui expose les agents 1 (Veilleur) et 2 (Évaluateur) à un commercial sans qu'il ait à toucher le CLI.

## Fonctionnalités

- **Top incidents par sévérité**, classés par score, filtrable par tier et sous-catégorie.
- **Vue détail** : motif complet, risques, distributeurs, lien vers la fiche RappelConso officielle, et **breakdown du score** (chaque dimension avec son raw, son poids, sa contribution et la justification).
- **Actions de pipeline** dans la sidebar :
  - *Récupérer* → invoque l'agent 1 (avec choix fenêtre temporelle, catégorie, limite).
  - *Scorer* → invoque l'agent 2 (avec/sans LLM, rescoring forcé, limite).

## Installation

Depuis `agents/`, dans le même venv que les autres agents :

```bash
pip install -r dashboard/requirements.txt
```

Si tu veux le scoring LLM (Claude Haiku) :

```bash
pip install anthropic
```

## Lancement

Depuis `agents/` :

```bash
streamlit run dashboard/app.py
```

Streamlit ouvre l'UI sur `http://localhost:8501`. Premier lancement : la sidebar montrera 0 incident → utilise *Récupérer* puis *Scorer*.

### Configuration optionnelle

```bash
# Active le scoring LLM (sinon fallback table mots-clés, rapport indique "LLM utilisé : 0/N")
export ANTHROPIC_API_KEY=sk-ant-...        # Linux/macOS
$env:ANTHROPIC_API_KEY = "sk-ant-..."      # PowerShell

# Pointe vers un autre dossier de bases SQLite (defaut: ./data)
export EVERTRACK_DATA_DIR=/path/to/data

# Mode démo : masque les boutons d'action de la sidebar, lecture seule.
# À utiliser quand on partage l'UI à un tiers via tunnel.
$env:EVERTRACK_DEMO_MODE = "1"
```

## Partager le dashboard via Cloudflare Tunnel (démo ponctuelle)

Pour faire essayer l'UI à quelqu'un sans déployer (idéal démo client) :

### 1. Installer cloudflared (une seule fois)

Télécharger le binaire Windows : https://github.com/cloudflare/cloudflared/releases/latest (cherche `cloudflared-windows-amd64.exe`). Renomme-le `cloudflared.exe` et place-le dans un dossier de ton PATH (par exemple `C:\Windows\System32\` ou un dossier custom ajouté au PATH).

Vérification :
```powershell
cloudflared --version
```

### 2. Pré-charger les données et activer le mode démo

```powershell
# Dans agents/, depuis ton venv actif
$env:ANTHROPIC_API_KEY = "sk-ant-..."  # ta clé pour scorer en local
python -m veilleur_incidents.cli fetch --since-days 14
python -m evaluateur_severite.cli score
```

### 3. Lancer Streamlit en mode démo

```powershell
# Mode démo activé : la personne ne pourra ni fetch, ni scorer (donc pas de coût LLM à ta charge)
$env:EVERTRACK_DEMO_MODE = "1"
streamlit run dashboard/app.py
```

### 4. Ouvrir le tunnel dans une autre fenêtre PowerShell

```powershell
cloudflared tunnel --url http://localhost:8501
```

Cloudflared imprime une URL du genre `https://xxxxx-yyyyy-zzzzz.trycloudflare.com`. **C'est cette URL que tu partages à ta cible**.

### Pendant la démo

- Ton PC doit rester allumé et le terminal Streamlit ouvert.
- Si tu fermes / relances cloudflared, l'URL change.
- La personne voit exactement ce que toi tu vois (sauf qu'elle ne peut pas déclencher d'action grâce au mode démo).
- Ta clé Anthropic n'est PAS exposée — elle reste en variable d'environnement côté serveur, jamais dans la page.

### Quand tu as fini

`Ctrl+C` dans la fenêtre cloudflared et celle de Streamlit. C'est fini, l'URL n'existe plus.

### Alternative : ngrok

Si tu préfères ngrok (équivalent, demande un compte gratuit) :
```powershell
ngrok http 8501
```

## Structure

```
dashboard/
├── __init__.py
├── app.py             # UI Streamlit (single page avec drill-down)
├── data_access.py     # Lecteur SQLite (read-only, pas d'ecriture ici)
├── actions.py         # Wrappers fetch/score (deleguent aux agents 1 et 2)
├── requirements.txt
└── README.md
```

## Architecture

Le dashboard est **purement une couche d'affichage et d'orchestration** — il ne contient aucune logique métier. Tout passe par les modules des agents :

- Lecture : `data_access.py` requête directement les SQLite produites par les agents.
- Écriture : `actions.py` appelle `veilleur_incidents.veilleur.run_fetch` et `evaluateur_severite.evaluateur.run_score`.

C'est volontaire : si demain on remplace Streamlit par une vraie webapp (FastAPI + React), on garde tout ce qui compte.

## Captures à montrer au client

Trois écrans suffisent pour la démo :

1. **Sidebar avec les actions** → "le commercial déclenche le pipeline depuis le navigateur, pas besoin de connaître Python".
2. **Top du jour avec les badges colorés** → "il voit en 3 secondes ce sur quoi prospecter aujourd'hui".
3. **Vue détail avec le breakdown** → "le score est explicable, on sait *pourquoi* cet incident est critique. Pas une boîte noire."

## Dette assumée

- **Pas d'authentification** — c'est un POC local, on protégera quand on déploiera.
- **Recharge complète à chaque action** (`st.rerun()`) — Streamlit, c'est comme ça. Acceptable pour <500 incidents.
- **Pas de pagination** — on coupe à `--limit` (défaut 25). Quand on aura 1000+ incidents, il faudra ajouter une vraie pagination.
- **Pas d'export CSV** vers Sellsy — à brancher quand on aura validé le format de champs attendu côté CRM.
- **Pas de marquage "traité"** — viendra avec le suivi de prospection (agent 5 ou un agent 6 dédié).
