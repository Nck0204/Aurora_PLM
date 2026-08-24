# Stato di avanzamento

Ultimo aggiornamento: **24 agosto 2026**, fine della sessione 1.

Il progetto e' diviso in 13 sessioni di lavoro. Questa tabella dice a che
punto siamo. Va aggiornata **alla fine di ogni sessione**, prima del commit.

Stati possibili: `da fare` · `in corso` · `completata`

---

## Tabella delle sessioni

| # | Sessione | Stato | Che cosa e' stato realizzato |
|---|---|---|---|
| 1 | Fondamenta | **completata** | Struttura del progetto, ambiente virtuale, configurazione da `.env`, collegamento a PostgreSQL, Alembic, avvio del server, registro su file, gestione errori, rotta `/salute`, primi test, file di governo. Dettaglio sotto. |
| 2 | Utenti, accesso e audit trail | da fare | Tabelle utenti e ruoli, password con argon2, sessione di accesso, pagina di entrata, registrazione delle operazioni. |
| 3 | Anagrafiche di base | da fare | Clienti, fornitori, categorie: le tabelle di appoggio che servono a tutto il resto. |
| 4 | Progetti | da fare | Tabella progetti, stati di avanzamento, elenco e scheda del singolo progetto. |
| 5 | Attivita' e assegnazioni | da fare | Attivita' collegate ai progetti, responsabili, scadenze, stato di completamento. |
| 6 | Archivio documenti | da fare | Caricamento file, calcolo dell'impronta SHA-256, deposito per impronta, versioni successive dello stesso documento. |
| 7 | Distinte base e componenti | da fare | Anagrafica componenti elettronici, distinte base collegate ai progetti, quantita' e alternative. |
| 8 | Revisioni e approvazioni | da fare | Flusso di revisione dei documenti tecnici: bozza, in revisione, approvato, superato. |
| 9 | Interfaccia completa | da fare | Struttura di navigazione, ricerca, elenchi con filtri e paginazione, rifinitura del tema scuro. |
| 10 | Notifiche e posta | da fare | Adattatore di posta doppio (locale/Graph), modelli dei messaggi, notifiche su scadenze e approvazioni. |
| 11 | Lavori pianificati e manutenzione | da fare | APScheduler, controlli notturni, procedura di backup e di ripristino. |
| 12 | Rapporti ed esportazioni | da fare | Cruscotto, rapporti di avanzamento, esportazione in CSV e PDF. |
| 13 | Messa in produzione | da fare | Irrobustimento, prestazioni, installazione sul server aziendale, manuale d'uso, consegna. |

> **Nota.** Il contenuto delle sessioni da 2 a 13 e' una **proposta** costruita
> alla fine della sessione 1 sulla base del dominio applicativo. Va confermato
> o corretto prima di iniziare la sessione 2. Le sessioni 2 e 6 sono quelle da
> cui dipende tutto il resto: conviene non spostarle.

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
  database lo legge da `.env`, non da `alembic.ini`. Nessuna migrazione
  ancora scritta, come previsto.
- **`app/main.py`** — applicazione FastAPI con:
  - registro su file rotativo in `logs/aurora.log` (5 MB x 11 file), che
    raccoglie anche le righe prodotte da uvicorn;
  - gestore globale delle eccezioni: annota il dettaglio nel registro con un
    codice di riferimento e mostra all'utente una pagina in italiano priva di
    dettagli tecnici (in JSON se la richiesta non viene da un browser);
  - rotta `GET /salute` che verifica la connessione al database e restituisce
    stato, versione e ora.
- **`app/templates/errore.html`** e **`app/static/css/aurora.css`** — l'unica
  pagina HTML prevista in questa sessione, con il tema scuro di base.
  Nessuna risorsa esterna.
- **`scripts/setup_postgres.md`** — procedura di installazione e preparazione
  del database, con verifica finale e tabella dei problemi frequenti.
- **File di governo**: `CLAUDE.md`, `docs/STATO.md`, `docs/DECISIONI.md`.
- **`README.md`** con l'avvio rapido.
- **`tests/test_salute.py`** — tre test: `/salute` risponde 200, `/salute`
  dichiara il database connesso (saltato finche' il database non e' pronto),
  un indirizzo inesistente mostra la pagina di errore in italiano.

### Verificato

| Criterio | Esito |
|---|---|
| `uvicorn app.main:app --reload` avvia il server senza errori | superato |
| `/salute` risponde 200 con `stato`, `versione`, `ora` | superato |
| `/salute` dichiara la connessione al database riuscita | **in attesa**: il database va ancora preparato (`scripts/setup_postgres.md`, parte B) |
| `pytest` passa | superato: 2 passati, 1 saltato |
| I tre file di governo esistono e sono compilati | superato |
| Il foglio di stile viene servito dal nostro server | superato |
| La pagina di errore in italiano compare sui 404 | superato |

### Scoperto durante la sessione

Due differenze fra quanto previsto e la macchina reale, entrambe innocue ma
da sapere:

1. **Python installato: 3.14.6, non 3.12.** Tutte le dipendenze hanno wheel
   native per 3.14 e funzionano. Vedi `docs/DECISIONI.md`, decisione D-008.
2. **PostgreSQL e' gia' installato: versione 18.6**, servizio
   `postgresql-x64-18` in esecuzione sulla porta 5432. Mancano solo il
   database `aurora` e l'utente `aurora_app`. Vedi decisione D-009.

### Rimasto in sospeso per la sessione 2

- Preparare database e utente applicativo (`scripts/setup_postgres.md`,
  parte B) e verificare che `/salute` risponda `"stato": "ok"`.
- Confermare o correggere il piano delle sessioni 2-13 di questa tabella.
