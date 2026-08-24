# Stato di avanzamento

Ultimo aggiornamento: **24 agosto 2026**, fine della sessione 2.

Il progetto e' diviso in 13 sessioni di lavoro. Questa tabella dice a che
punto siamo. Va aggiornata **alla fine di ogni sessione**, prima del commit.

Stati possibili: `da fare` · `in corso` · `completata`

---

## Tabella delle sessioni

| # | Sessione | Stato | Che cosa e' stato realizzato |
|---|---|---|---|
| 1 | Fondamenta | **completata** | Struttura del progetto, ambiente virtuale, configurazione da `.env`, collegamento a PostgreSQL, Alembic, avvio del server, registro su file, gestione errori, rotta `/salute`, primi test, file di governo. Dettaglio sotto. |
| 2 | Modello dati R1 | **completata** | Diciannove tabelle come modelli SQLAlchemy, una migrazione Alembic, dati iniziali idempotenti, test del modello, `docs/MODELLO_DATI.md`. Dettaglio sotto. |
| 3 | Accesso e sessioni | da fare | Verifica della password con argon2, pagina di entrata in italiano, cookie di sessione e "ricordami", blocco dopo troppi tentativi falliti, cambio password obbligatorio al primo accesso, scrittura nel registro di audit. |
| 4 | Amministrazione e anagrafiche | da fare | Gestione di utenti, clienti, contatti e classificazioni; matrice dei permessi modificabile dall'interfaccia. Nessuna cancellazione, solo disattivazione. |
| 5 | Prodotti e versioni | da fare | Anagrafica dei prodotti, scomposizione del codice parlante in `code_parts`, versioni e catena delle derivazioni, stati del ciclo di vita. |
| 6 | Progetti, assegnazioni e fasi | da fare | Apertura di un progetto su una versione, squadra e ruoli, scelta del modello di fasi, passaggi di fase con richiesta e approvazione. |
| 7 | Archivio documenti | da fare | Caricamento file, calcolo dell'impronta SHA-256, deposito per impronta, versioni successive, presa in carico, permessi effettivi calcolati sulla matrice. |
| 8 | Revisioni e approvazioni | da fare | Flusso di revisione dei documenti tecnici: bozza, in verifica, rilasciato, superato. |
| 9 | Interfaccia completa | da fare | Struttura di navigazione, ricerca, elenchi con filtri e paginazione, rifinitura del tema scuro. |
| 10 | Notifiche e posta | da fare | Adattatore di posta doppio (locale/Graph), archiviazione dei messaggi, smistamento automatico e quarantena, allegati, modelli dei messaggi, notifiche. |
| 11 | Lavori pianificati e manutenzione | da fare | APScheduler, controlli notturni, procedura di backup e di ripristino. |
| 12 | Rapporti ed esportazioni | da fare | Cruscotto, rapporti di avanzamento, esportazione in CSV e PDF. |
| 13 | Messa in produzione | da fare | Irrobustimento, prestazioni, installazione sul server aziendale, manuale d'uso, consegna. |

> **Nota sul piano.** Il contenuto delle sessioni da 3 a 13 e' stato riscritto
> alla fine della sessione 2, dopo che il modello dati e' stato realizzato tutto
> insieme invece che una tabella per sessione (vedi `docs/DECISIONI.md`, D-021).
> Le sessioni successive non creano piu' tabelle: ci costruiscono sopra il
> comportamento. Resta una **domanda aperta**: le tabelle di distinta base e
> articoli sono del rilascio R3 e in questo piano non compaiono; va chiarito se
> le 13 sessioni coprono il solo R1 o arrivano anche a R2 e R3.

---

## Sessione 2 — Modello dati R1 · completata (24 agosto 2026)

### Realizzato

- **Diciannove tabelle** come modelli SQLAlchemy, un file per tabella in
  `app/models/`, tutte importate in `app/models/__init__.py`:

  | Argomento | Tabelle |
  |---|---|
  | Persone e accessi | `users`, `user_sessions`, `login_attempts` |
  | Anagrafiche | `customers`, `contacts` |
  | Prodotti | `products`, `product_versions` |
  | Progetti | `projects`, `assignments` |
  | Permessi | `classifications`, `permission_rules` |
  | Documenti | `documents`, `document_versions` |
  | Fasi | `phase_templates`, `phases`, `phase_transitions` |
  | Posta | `email_messages`, `email_attachments` |
  | Tracciabilita' | `audit_logs` |

- **`app/models/base.py`** — i pezzi comuni: `UuidPrimaryKeyMixin` (chiave
  primaria UUID generata da Python), `TimestampMixin` (`created_at` e
  `updated_at` con fuso orario), la funzione `pg_enum()` che costruisce i tipi
  enumerati di PostgreSQL con i valori giusti.
- **`app/models/enums.py`** — sei elenchi di stati: `GlobalRole`,
  `SessionKind`, `LifecycleState`, `ProjectRole`, `DocumentState`,
  `EmailAssignmentState`.
- **Migrazione `897359b06e69_modello_dati_r1.py`** — generata con
  `--autogenerate` e corretta a mano in due punti (creazione e cancellazione
  esplicita dei tipi enumerati), entrambi segnalati da un commento nel file.
- **`scripts/seed.py`** — dati iniziali idempotenti: l'utente creatore `admin`
  con password casuale stampata una volta sola, le quattro classificazioni, le
  dodici caselle della matrice dei permessi, il modello di fasi "Standard"
  versione 1 con le sue sei fasi.
- **`tests/conftest.py`** — fixture `db_session` che lavora dentro una
  transazione sempre annullata: i test toccano il database vero senza
  sporcarlo. Se PostgreSQL non risponde o le migrazioni non sono passate, i
  test si saltano invece di fallire.
- **`tests/test_models.py`** — due test: la catena delle derivazioni fra
  versioni di prodotto e il vincolo di unicita' del numero di versione.
- **`docs/MODELLO_DATI.md`** — ogni tabella con la sua riga di spiegazione, il
  dettaglio delle colonne, la mappa dei collegamenti, i tipi enumerati e le
  scelte che vanno confermate.

### Verificato

| Criterio | Esito |
|---|---|
| `alembic upgrade head` crea tutte le tabelle senza errori | superato: 19 tabelle e 6 tipi enumerati |
| `alembic downgrade base` le rimuove senza errori | superato: non resta niente, nemmeno i tipi enumerati |
| Il giro completo si ripete (`upgrade`, `downgrade`, `upgrade`) | superato |
| `alembic check` non trova differenze fra modelli e migrazione | superato |
| `python scripts/seed.py` popola i dati iniziali | superato: 1 utente, 4 classificazioni, 12 regole, 1 modello con 6 fasi |
| Rieseguirlo non duplica niente | superato: al secondo e terzo giro i conteggi non cambiano |
| Test della relazione `derived_from` | superato |
| `pytest` passa | superato: 5 test, nessun avviso |
| `docs/MODELLO_DATI.md` documenta ogni tabella | superato |

### Scelte prese durante la sessione

Otto decisioni nuove in `docs/DECISIONI.md`, dalla D-013 alla D-021. Le tre che
conviene rileggere prima della sessione 3:

- **D-013**, chiavi primarie UUID e codici parlanti come attributi: e' il
  principio che regge tutto il resto del modello;
- **D-019**, i tipi enumerati vanno creati e cancellati a mano nelle
  migrazioni: se lo si dimentica, il `downgrade` sembra funzionare e il
  successivo `upgrade` fallisce;
- **D-021**, il cambio di piano che ha portato tutto il modello dati dentro
  questa sessione.

Tre punti in cui il modello dice qualcosa di piu' di quanto la sessione avesse
specificato sono elencati in `docs/MODELLO_DATI.md`, sezione 6: `products.customer_id`
obbligatorio, `assignments` con `revoked_at` e `revoked_by_id`,
`documents.doc_type` e `documents.classification_id` obbligatori.

### Rimasto in sospeso per la sessione 3

- **La password di `admin` generata durante la verifica e' visibile
  nell'uscita della sessione di lavoro.** L'utente e' segnato
  `must_change_password`, quindi va cambiata al primo accesso; in alternativa
  si azzera il database (`alembic downgrade base`, `upgrade head`,
  `scripts/seed.py`) e se ne genera una nuova.
- **Un modo semplice per non dimenticare il filtro sulle righe disattivate.**
  Il principio di D-006 obbliga ogni interrogazione a escludere le righe con
  `deleted_at` valorizzato, `revoked_at` valorizzato o `is_active` falso.
  Serve una convenzione, da decidere insieme alle prime interrogazioni vere.
- **La funzione che scrive nel registro di audit.** La tabella c'e', chi ci
  scrive dentro no.
- **Una procedura di riassegnazione della password di `admin`**, per il caso in
  cui quella dei dati iniziali vada persa.

---

## Sessione 1 — Fondamenta · completata (24 agosto 2026)

### Realizzato

- **Struttura del progetto** con le cartelle `app/` (con `models/`,
  `routers/`, `services/`, `templates/`, `static/`), `alembic/`, `docs/`,
  `scripts/`, `tests/`, `storage/`, `logs/`.
- **Ambiente virtuale** in `.venv/` e `requirements.txt` con tutte le versioni
  bloccate.
- **`.gitignore`** che esclude ambiente virtuale, cache di Python, `.env`,
  contenuto di `storage/` e registri.
- **`app/config.py`** — configurazione letta dal file `.env` con
  pydantic-settings. Parametri: `DATABASE_URL`, `STORAGE_PATH`, `SECRET_KEY`,
  `APP_NAME`, `LOG_LEVEL`, `MAIL_PROVIDER`, `MAIL_LOCAL_PATH`. I percorsi
  relativi vengono resi assoluti rispetto alla radice del progetto.
- **`.env.example`** commentato in italiano e **`.env`** con i valori di
  sviluppo.
- **`app/db.py`** — engine SQLAlchemy con verifica della connessione prima
  dell'uso, fabbrica delle sessioni, classe `Base` per i modelli, dipendenza
  `get_db()` per FastAPI.
- **Alembic** inizializzato e collegato a `Base.metadata`; l'indirizzo del
  database lo legge da `.env`, non da `alembic.ini`.
- **`app/main.py`** — applicazione FastAPI con:
  - registro su file rotativo in `logs/aurora.log` (5 MB x 11 file), che
    raccoglie anche le righe prodotte da uvicorn;
  - gestore globale delle eccezioni: annota il dettaglio nel registro con un
    codice di riferimento e mostra all'utente una pagina in italiano priva di
    dettagli tecnici (in JSON se la richiesta non viene da un browser);
  - rotta `GET /salute` che verifica la connessione al database e restituisce
    stato, versione e ora.
- **`app/templates/errore.html`** e **`app/static/css/aurora.css`** — l'unica
  pagina HTML prevista in quella sessione, con il tema scuro di base.
  Nessuna risorsa esterna.
- **`scripts/setup_postgres.md`** — procedura di installazione e preparazione
  del database, con verifica finale e tabella dei problemi frequenti.
- **File di governo**: `CLAUDE.md`, `docs/STATO.md`, `docs/DECISIONI.md`.
- **`README.md`** con l'avvio rapido.
- **`tests/test_salute.py`** — tre test.

### Verificato

| Criterio | Esito |
|---|---|
| `uvicorn app.main:app --reload` avvia il server senza errori | superato |
| `/salute` risponde 200 con `stato`, `versione`, `ora` | superato |
| `pytest` passa | superato |
| I tre file di governo esistono e sono compilati | superato |
| Il foglio di stile viene servito dal nostro server | superato |
| La pagina di errore in italiano compare sui 404 | superato |

### Scoperto durante la sessione

1. **Python installato: 3.14.6, non 3.12.** Vedi `docs/DECISIONI.md`, D-008.
2. **PostgreSQL gia' installato, versione 18.6.** Vedi D-009.

### Sospesi della sessione 1, ora chiusi

- Il database `aurora` e l'utente applicativo sono stati preparati: la
  connessione funziona e `/salute` risponde con il database connesso.
- Il piano delle sessioni 2-13 e' stato rivisto alla fine della sessione 2
  (D-021).
