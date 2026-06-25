# EverTrack — cibles de déploiement
GH ?= gh
REPO ?= GAP01/evertrack-prospect-agent
SNAPSHOT_TAG ?= data-snapshot
SNAPSHOT_ASSET ?= data-snapshot.tar.gz
DATA_DIR ?= agents/data

# Pousse un snapshot des SQLite vers l'asset de la release GitHub.
# Inclut uniquement les bases lues par le dashboard ; exclut secrets/caches.
push-snapshot:
	@echo "[*] Empaquetage des SQLite depuis $(DATA_DIR)..."
	tar -czf $(SNAPSHOT_ASSET) -C $(DATA_DIR) \
		incidents.sqlite scores.sqlite enrichissements.sqlite \
		signaux.sqlite outreach.sqlite
	@echo "[*] Assure l'existence de la release $(SNAPSHOT_TAG)..."
	$(GH) release view $(SNAPSHOT_TAG) --repo $(REPO) >/dev/null 2>&1 || \
		$(GH) release create $(SNAPSHOT_TAG) --repo $(REPO) \
			--prerelease --title "Data snapshot" \
			--notes "Snapshot SQLite du dashboard (ecrase a chaque push)."
	@echo "[*] Upload de l'asset (ecrasement)..."
	$(GH) release upload $(SNAPSHOT_TAG) $(SNAPSHOT_ASSET) \
		--repo $(REPO) --clobber
	rm -f $(SNAPSHOT_ASSET)
	@echo "[ok] Snapshot pousse. Redemarre le service Railway pour rafraichir."

.PHONY: push-snapshot
