# Cahier des charges - Modernisation « Telegram-Tools » (production ready)

> Base auditée : commit `fad53cd`. API de référence : **Telegram Bot API 10.3 (24/08/2026)**.
> Objectif : corriger ce qui est cassé, fiabiliser, sécuriser et moderniser l'UI,
> pour un outil réellement distribuable.

## 0. Constats bloquants (à traiter avant tout le reste)

| # | Problème | Décision |
|---|---|---|
| B1 | `inviteChatMember` n'existe pas dans la Bot API - `add-members` ne peut pas fonctionner | Supprimer la promesse « add ». Remplacer par un générateur de lien (`createChatInviteLink`) avec options (expiration, limite, join-request) + approbation de join-request (`approveChatJoinRequest`) |
| B2 | Widgets GUI écrasés en boucle (attributs d'instance réassignés) -> accès par index positionnel | Réécrire l'UI : chaque formulaire est une classe/objet autonome qui expose ses propres champs |
| B3 | `Stop` fait `kill()` -> les messages dumpés ne sont jamais sauvegardés (contraire au README) | Arrêt coopératif (terminate/CTRL_BREAK) **ou** dump exécuté in-process dans un thread avec flag d'annulation + flush |
| B4 | Exe PyInstaller sans interpréteur ni `telegram_tools_cli.py` -> commandes QProcess mortes | Supprimer l'architecture sous-processus : la GUI appelle une couche cœur Python en direct |
| B5 | `test_bot_token` écrit sur le mauvais QLabel (logo) | Corrigé mécaniquement par B2 |

## 1. Architecture cible

```
telegram_tools/
├── core/              # Couche métier PURE, sans I/O console ni Qt
│   ├── client.py      # Session requests (timeouts, retry/backoff, retry_after)
│   ├── api.py         # 1 fonction par opération, renvoie des objets/dataclasses
│   └── errors.py      # Exceptions typées (TelegramAPIError, RateLimited, ...)
├── cli/__main__.py    # argparse -> core, formatage sortie (text/json)
├── gui/               # PyQt6 (ou PySide6), consomme core directement (in-process, threadé)
└── tests/
```

- **Règle d'or** : CLI et GUI partagent **la même** couche `core`. Plus aucune GUI qui relance le CLI en sous-processus.
- `core` ne fait **aucun** `print` : il renvoie des données ou lève des exceptions.

## 2. Reprise fonctionnelle (par commande)

| Actuel | Cible |
|---|---|
| `add-members` (cassé) | **`make-invite`** : `createChatInviteLink` (name, expire_date, member_limit, creates_join_request) ; sous-commande `approve-joins` via `getUpdates`/`approveChatJoinRequest` |
| `get-admins` | conservé ; option `--include-bots` (`return_bots`) |
| `listen-users` | conservé ; long-poll propre avec gestion d'offset et `allowed_updates` ; sortie structurée |
| `get-invite` | migrer vers `createChatInviteLink` (ne plus révoquer le lien primaire) ; garder `exportChatInviteLink` derrière un flag `--primary` |
| `get-member` / `get-rights` | conservés ; accepter `chat_id` numérique **ou** `@username` |
| `dump-messages` -> **`archive-messages`** | voir §2bis (refonte complète de l'itération) |
| Bot Config (GUI) | conservé, appels in-process threadés |
| Chat Preview (GUI) | **renommer / clarifier** : c'est « derniers updates du bot », pas l'historique du chat. Documenter la limite, ou retirer |

## 2bis. Refonte de l'archivage de messages (`archive-messages`)

### Le hack à PRÉSERVER (capacité centrale, volontaire)

**Les `message_id` sont séquentiels par chat.** En partant d'un ID haut et en **décrémentant**, on peut forwarder/copier des messages que le bot n'a **jamais reçus en update** - y compris **antérieurs à son arrivée dans le chat**. C'est ce qui contourne la limite Bot API « pas de lecture d'historique » (updates uniquement, expirés après 24 h, pas de `getMessage`). **Cette déduction d'IDs est LA raison d'être de la commande et ne doit pas être retirée ni « assainie ».**

- Mécanisme de capture = **`forwardMessage` singulier par ID** (décrément) : c'est lui, et lui seul, qui ramène l'objet `Message` **complet (contenu)** dans la réponse HTTP. Il reste le cœur.
- On sonde des IDs **inconnus à l'avance** : succès = message existant capturé, échec = ID absent (gap, service message, suppression), on continue. Ce « probing à l'aveugle » est voulu.

### Améliorations = enveloppes NON destructives autour du hack

Elles fiabilisent sans changer le mécanisme :

- **Écriture incrémentale NDJSON** (1 message/ligne, flush immédiat) -> tout arrêt (Stop, Ctrl+C, crash) préserve le dump. Corrige B3.
- **Rate limiting** : respecter `parameters.retry_after` sur 429 (fini la récursion + `sleep(15)` fixe).
- **Destination d'archive séparée EN OPTION** (canal privé / DM du bot) pour ne pas spammer le groupe source - mais « même chat » reste possible si l'utilisateur le veut. Jamais imposé.
- **Nettoyage optionnel** : `deleteMessage`/`deleteMessages` des copies après capture.

### Modes secondaires (bonus, ne remplacent PAS le hack)

- **Batch `forwardMessages`/`copyMessages` (1-100 IDs)** : utile seulement pour déplacer vite en masse. ⚠️ ne renvoie que des `MessageId`, **pas le contenu**, et ne permet pas de remapper quels IDs source ont réussi -> inadapté à l'archivage de contenu. Donc proposé uniquement comme déplacement/bulk, pas comme archiveur principal.
- **Mode avancé MTProto (hors Bot API)** : connecteur Telethon/Pyrogram (`messages.getHistory`) pour un vrai export d'historique sans copie - derrière un flag explicite, avec avertissement ToS.

### Pré-vol UI

Afficher plage d'IDs, destination (source ou archive), et un **avertissement visible** (copies créées + droits requis) avant de lancer ; compteurs *trouvés / ignorés* en direct.

## 2ter. Annexe - capacités OSINT / anti-scam (features « hack » à cadrer)

Contexte : investigation anti-arnaque. Les features non documentées s'inspirent de writeups OSINT publics. Principe directeur confirmé par ces writeups : **s'ancrer sur l'ID numérique, jamais sur le `@username`** (le pseudo change, l'ID est permanent).

### A. Reste en Bot API (socle actuel - à enrichir)

- **Déduction d'IDs séquentiels + `forwardMessage`** -> récupération de messages antérieurs (cf. §2bis, hack central à préserver).
- **Profiling d'un bot par son token** (type « tosint ») : en plus de `getMe`, exposer `getWebhookInfo`, `getMyCommands`, `getMyName`, `getMyShortDescription`, `getMyDescription`, `getMyDefaultAdministratorRights`, `getChatMenuButton`. Révèle la config d'un bot de scam. *(vérifier la dispo exacte de chaque méthode en codant)*
- **Résolution de chat/canal public visible** : `getChat` + `getChatMemberCount` -> type, titre, description, photo, nb membres.

### B. Exige MTProto (mode avancé, flag explicite + `api_id`/`api_hash`)

Hors Bot API, sous ToS Telegram. C'est là que vivent les features OSINT lourdes :

- **Énumération complète des membres** d'un groupe/canal (cf. Telepathy de Bellingcat, ~5000 max).
- **Résolution `@username` arbitraire -> ID numérique** (non fiable en Bot API).
- **Vrai historique / recherche par date** (`messages.getHistory`, `messages.search`).

### C. Pivots externes (hors Telegram)

- **Corrélation de pseudo cross-plateforme** : export du `@username` -> Sherlock / Maigret.
- **Dorking** `site:t.me` ; annuaires publics (tgstat, SearchGram, tgscan).

### Garde-fous (investigation défendable)

- Journaliser la **provenance** (URL/@username, ID, date/heure, captures) ; archiver les pages publiques (Wayback/archive.today).
- Traiter chaque élément comme **piste à vérifier**, pas comme identité établie.
- Respecter ToS Telegram / RGPD ; le scraping massif est fragile et restreint. Le mode MTProto doit afficher un avertissement explicite.

## 2quater. État d'implémentation (fait)

- **Lot 1 (core)** : `telegram_tools/core/` - client (timeouts/retry/retry_after), api, archive (hack préservé + NDJSON + download média + resume), intel. ✅ testé en réel.
- **Lot 2 (CLI)** : `telegram_tools/cli.py` - toutes commandes + `profile-token`, `archive-messages` (`--auto-start`, `--download-media`, `--resume`), `max-id`, `intel`. ✅
- **Lot 3 (GUI)** : `telegram_tools/gui/` PyQt6, in-process, page « Bot rights » façon Telegram. ✅
- **Tests réels** : `tests/test_live.py` - 12 tests contre la vraie API, validés sur bot/groupe jetables. ✅
- **MTProto (mode avancé)** : `telegram_tools/mtproto/` Telethon - login, resolve, members, history (NDJSON compatible intel), common-chats, dialogs. Code propre ; validation live = `login` par l'utilisateur (api_id/api_hash + code). ✅ structure

## 3. Fiabilité

- **HTTP** : `requests.Session` + timeouts partout (connect/read), `urllib3.Retry` avec backoff, respect de `parameters.retry_after` sur 429 (plus de récursion/`sleep` fixe).
- **Erreurs** : parsing uniforme de `{ok, error_code, description}` -> exceptions typées.
- **Entrées** : `chat_id` négatif et `@username` acceptés ; validations réelles (pas un `QRegExp \d+` qui interdit le `-`).
- **Concurrence GUI** : chaque appel réseau dans un `QThread`/worker ; l'UI ne gèle jamais ; garde contre double-lancement.
- **Logs** : logging structuré, niveau configurable, **token jamais loggé**.

## 4. Sécurité

- Champ token en `EchoMode.Password` ; option de stockage chiffré (keyring) ou variable d'environnement `TELEGRAM_BOT_TOKEN`.
- Ne **jamais** passer le token en argument CLI depuis la GUI (supprimé par B4) ni l'écrire dans une URL de log.
- `.gitignore` : ajouter dumps `*.json`, `dist/`, `build/`, `__pycache__/`, `.venv`.

## 5. UI / UX (modernisation visuelle)

- **Toolkit** : migrer PyQt5 -> **PyQt6** ou **PySide6** (licence LGPL plus souple pour distribution).
- Regrouper par **intention** (Membres / Lecture / Export) plutôt que « 1 onglet = 1 commande CLI brute ».
- Design system : palette cohérente (voir skill dataviz/artifact-design si besoin), espacement 8px, typographie système, **mode clair + sombre**, états *vide / chargement / erreur / succès* explicites.
- Remplacer la console « vert fluo » par un journal lisible avec niveaux colorés sobres.
- Retirer l'emoji du titre de fenêtre ; charger `logo` via chemin ressource (`sys._MEIPASS` compatible), icône redimensionnée **une seule fois**.
- Feedback : spinners/progress non bloquants, toasts de résultat.

## 6. Qualité / packaging

- `pyproject.toml` (deps épinglées), `ruff` + `black` + `mypy`, pre-commit.
- Tests `pytest` sur `core` avec `responses`/`httpretty` (API mockée) ; couverture des cas 429/erreur.
- CI GitHub Actions : lint + tests + build PyInstaller (artefact Windows signé si possible).
- README : corriger les promesses fausses (add-members, Stop, Chat Preview), ajouter la version d'API ciblée.

## 7. Lot de livraison suggéré

1. **Lot 1 - Cœur & correctifs bloquants** : extraction `core`, B1-B5, timeouts/retry. *(débloque tout)*
2. **Lot 2 - CLI** : branchement sur `core`, sortie `--json`, tests.
3. **Lot 3 - GUI** : migration PyQt6, suppression du sous-processus, threads, refonte visuelle.
4. **Lot 4 - Packaging/CI** : pyproject, lint, tests, build.
```
```
