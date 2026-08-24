# Stato di avanzamento

Ultimo aggiornamento: **24 agosto 2026**, fine della sessione 3.

Il progetto e' diviso in 13 sessioni di lavoro. Questa tabella dice a che
punto siamo. Va aggiornata **alla fine di ogni sessione**, prima del commit.

Stati possibili: `da fare` · `in corso` · `completata`

---

## Tabella delle sessioni

| # | Sessione | Stato | Che cosa e' stato realizzato |
|---|---|---|---|
| 1 | Fondamenta | **completata** | Struttura del progetto, ambiente virtuale, configurazione da `.env`, collegamento a PostgreSQL, Alembic, avvio del server, registro su file, gestione errori, rotta `/salute`, primi test, file di governo. Dettaglio sotto. |
| 2 | Modello dati R1 | **completata** | Diciannove tabelle come modelli SQLAlchemy, una migrazione Alembic, dati iniziali idempotenti, test del modello, `docs/MODELLO_DATI.md`. Dettaglio sotto. |
| 3 | Accesso e gestione utenti | **completata** | Password con argon2id, accesso con sessione e "ricordami" rotante, blocco dopo cinque tentativi, cambio password obbligatorio al primo accesso, protezione CSRF, gestione utenti riservata al creatore, registro di audit. Dettaglio sotto. |
| 4 | Interfaccia e anagrafiche | da fare | Grafica delle pagine (quelle della sessione 3 sono grezze di proposito); clienti, contatti e classificazioni; matrice dei permessi modificabile dall'interfaccia. Nessuna cancellazione, solo disattivazione. |
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

## Sessione 3 — Accesso e gestione utenti · completata (24 agosto 2026)

L'interfaccia di questa sessione e' **volutamente grezza**: HTML minimo, quel
tanto di CSS che serve perche' le pagine si leggano. La grafica e' della
sessione 4, e quando arrivera' il blocco in fondo ad `app/static/css/aurora.css`
andra' riscritto per intero.

### Realizzato

**Servizi** (`app/services/`, logica richiamabile anche fuori dalle rotte):

| File | A che cosa serve |
|---|---|
| `passwords.py` | Impronte argon2id, verifica, generazione delle password leggibili, rimozione degli accenti. E' l'unico posto in cui si tratta una password. |
| `parole.txt` | 415 parole italiane, da 4 a 8 lettere, senza accenti: l'elenco da cui si compongono le password assegnate. |
| `auth.py` | Sessioni (creazione, ricerca, revoca), tentativi di accesso e blocco, `esegui_accesso()`, `cambia_password()`. |
| `users.py` | Nome utente proposto, creazione, riassegnazione della password, disattivazione e riattivazione, elenco. |
| `audit.py` | La funzione che scrive nel registro delle operazioni, e i nomi delle azioni come costanti. Era il pezzo che mancava dalla sessione 2. |
| `cookies.py` | I nomi dei tre cookie, i loro attributi di sicurezza, la lista d'attesa (D-027). |
| `csrf.py` | Gettone a doppio invio e sua verifica. |

**Collegamento con FastAPI**:

- `app/dependencies.py` — le tre dipendenze `utente_corrente`,
  `richiedi_login`, `richiedi_creatore`, le due eccezioni di dirottamento e la
  rotazione del "ricordami" (D-022, D-023).
- `app/templating.py` — il motore Jinja2 e la funzione `pagina()`.
- `app/main.py` — dipendenza globale CSRF, middleware che consegna i cookie,
  gestori dei due dirottamenti, registrazione dei tre router.

**Pagine** (`app/routers/`, `app/templates/`):

| Indirizzo | Che cosa fa |
|---|---|
| `GET/POST /entra` | Modulo di accesso con `autocomplete` corretti e casella "Ricordami". |
| `POST /esci` · `POST /esci-ovunque` | Chiude questa sessione, oppure tutte. |
| `GET/POST /cambio-password` | Cambio volontario e cambio obbligatorio del primo accesso. |
| `GET /` | Pagina iniziale: chi sei, che ruolo hai, quante sessioni hai aperte. |
| `GET /utenti` | Elenco con stato, ruolo e sessioni aperte. Solo creatore. |
| `GET/POST /utenti/nuovo` | Creazione, con nome utente proposto e password mostrata una volta sola. |
| `POST /utenti/{id}/reimposta` | Password nuova, `must_change_password`, tutte le sessioni revocate. |
| `POST /utenti/{id}/disattiva` · `/riattiva` | Disattivazione e riattivazione. **Nessuna cancellazione, da nessuna parte.** |

**Configurazione** — cinque parametri nuovi in `.env` e `.env.example`:
`COOKIE_SECURE`, `SESSION_HOURS`, `REMEMBER_ME_DAYS`, `LOGIN_MAX_ATTEMPTS`,
`LOGIN_WINDOW_MINUTES`.

**Procedure** — `scripts/reimposta_password.py`, la via di soccorso per quando
nessuno riesce piu' a entrare come creatore. Riassegna la password di un utente
dalla riga di comando e, se serve, lo riattiva. Chiude il sospeso della
sessione 2. `scripts/seed.py` e' stato fatto passare dal servizio password,
come previsto dalla nota nel suo stesso file.

**Nessuna migrazione.** Le tabelle `users`, `user_sessions`, `login_attempts` e
`audit_logs` erano gia' complete dalla sessione 2 e non e' stato necessario
toccarle: questa sessione ci ha costruito sopra soltanto comportamento, che e'
esattamente quello che D-021 si aspettava.

### Verificato

**Test automatici: 51, tutti superati** (erano 5 alla fine della sessione 2).

| Criterio di accettazione | Test | Esito |
|---|---|---|
| Login corretto | `test_login_riuscito_apre_una_sessione` | superato |
| Login errato, messaggio generico | `test_login_sbagliato_da_un_messaggio_generico`, `..._utente_inesistente_dice_la_stessa_cosa` | superato |
| Blocco dopo 5 tentativi | `test_blocco_dopo_cinque_tentativi_falliti` | superato |
| Cambio password obbligatorio al primo accesso | `test_primo_accesso_obbliga_a_cambiare_la_password` | superato |
| Revoca sessioni al cambio password | `test_il_cambio_password_revoca_le_altre_sessioni` | superato |
| Accesso negato a un non creatore | `test_un_utente_normale_non_apre_la_gestione_utenti`, `..._non_puo_nemmeno_agire` | superato |
| Funzionamento del "ricordami" | `test_ricordami_fa_rientrare_dopo_la_chiusura_del_browser`, `test_il_gettone_ricordami_usato_non_vale_piu` | superato |
| Giro completo: creo, ricevo la password, entro, sono obbligato a cambiarla, poi entro normalmente | `test_giro_completo_dalla_creazione_al_primo_accesso` | superato |

**Prova a mano nel browser**, con il server avviato e il database di sviluppo:

| Passo | Esito |
|---|---|
| `scripts/reimposta_password.py admin` assegna una password nuova | superato |
| Entrata come `admin` con quella password | superato: dirottato al cambio password |
| Cambio password e arrivo alla pagina iniziale | superato |
| Creazione di "Nicolò D'Angelo" dall'interfaccia | superato: nome utente proposto `nicolo.dangelo`, accento e apostrofo tolti |
| Password mostrata una volta sola, con pulsante copia | superato: quattro parole italiane unite da trattini, copia riuscita |
| Entrata con l'utente nuovo | superato: dirottato al cambio password |
| Dopo il cambio, navigazione normale | superato |
| `/utenti` con un utente non creatore | superato: 403 con messaggio in italiano |
| La barra in cima non mostra "Utenti" a chi non e' creatore | superato |
| `document.cookie` letto dal browser | superato: vuoto, i cookie sono HttpOnly |
| `autocomplete` sui campi del modulo di accesso | superato: `username` e `current-password` |
| Registro di audit dopo il giro | superato: `user.login`, `user.logout`, `user.created`, `user.password_changed`, `user.password_reset`, ciascuna con autore e indirizzo IP |
| `user_sessions` dopo il giro | superato: solo impronte, nessun gettone in chiaro |
| Nessun errore nella consolle del browser e in `logs/aurora.log` | superato |

**Una cosa scoperta proprio da questa prova a mano.** L'utente
"Nicolò D'Angelo" creato dall'interfaccia e' rimasto sul database di sviluppo,
e ha fatto diventare rosso un test che si aspettava di ottenere
`nicolo.dangelo` dal generatore dei nomi utente: trovandolo occupato, il
programma proponeva giustamente `nicolo.dangelo2`.

Il difetto era nel test, non nel programma, ma e' un difetto che sarebbe
tornato a ogni verifica a mano delle sessioni future. E' stato tolto alla
radice con due convenzioni, scritte in `tests/conftest.py`:

- i test che **si scelgono** il nome utente usano nomi con **due punti**
  (`prova.mario.rossi`); `proponi_username()` ne produce al massimo uno, quindi
  quello spazio di nomi il programma non lo raggiunge e non ci puo' essere
  collisione;
- i test che verificano il nome utente **proposto dal programma** usano
  `cognome_irripetibile()`, un cognome inventato con un pezzo casuale in coda,
  che nel database non puo' gia' esserci.

L'utente "Nicolò D'Angelo" e' stato lasciato dov'e': fa comodo avere sul
database di sviluppo un profilo non creatore con cui provare gli accessi
negati, e cancellarlo sarebbe comunque contro la regola 5.

### Scelte prese durante la sessione

Undici decisioni nuove in `docs/DECISIONI.md`, dalla D-022 alla D-032. Le
quattro da rileggere prima di scrivere una pagina nuova:

- **D-028**, la protezione CSRF e' una dipendenza globale: ogni modulo POST
  nuovo deve contenere il campo nascosto, altrimenti riceve un 400;
- **D-032**, lo stato dell'utente si rilegge dal database a ogni richiesta: nel
  cookie non c'e' nient'altro che il gettone;
- **D-027**, i cookie si mettono in lista d'attesa e li consegna un middleware:
  chi ne aggiunge uno deve passare da `programma_cookie()`;
- **D-029**, il blocco dei tentativi e' una finestra che scorre, e chi martella
  tiene chiuso il proprio blocco da solo.

### Rimasto in sospeso per le sessioni successive

- **La grafica.** Le pagine sono grezze di proposito. Il blocco in fondo ad
  `app/static/css/aurora.css` e' un provvisorio dichiarato, da riscrivere nella
  sessione 4.

- **Il registro di audit non si puo' ancora leggere dall'interfaccia.** Le
  righe si scrivono, ma per rileggerle bisogna interrogare il database. Una
  pagina di consultazione, con filtri per persona e per oggetto, e' materiale
  della sessione 9 o della 12.

- **Le sessioni scadute non vengono mai ripulite.** Restano in tabella,
  revocate o scadute: non fanno danno e non si cancellano (D-006), ma la
  tabella cresce. Se un giorno desse fastidio, e' un lavoro pianificato da
  sessione 11 - e sara' comunque un archiviare, non un cancellare.

- **Un utente non puo' vedere le proprie sessioni aperte una per una.** La
  pagina iniziale ne dice il numero e c'e' "Esci da tutti i dispositivi", ma
  l'elenco con dispositivo, indirizzo e data - che le colonne `ip` e
  `user_agent` gia' consentirebbero - non c'e'. Da valutare nella sessione 9.

- **Il cambio di ruolo non si fa dall'interfaccia.** La sessione 3 chiedeva
  elenco, creazione, riassegnazione della password, disattivazione e
  riattivazione, e c'e' tutto; il ruolo si sceglie alla creazione e poi non si
  cambia piu'. Il codice e' pronto (D-032: il ruolo si rilegge a ogni
  richiesta), manca solo la pagina. Sessione 4, insieme alla matrice dei
  permessi.

- **`COOKIE_SECURE` va acceso in produzione.** In sviluppo vale `false` per
  forza. Nella sessione 13 va verificato che valga `true` e che davanti ci sia
  davvero https, altrimenti la sessione viaggia in chiaro sulla rete aziendale.

- **La password di sviluppo di `admin`.** Durante la verifica di questa sessione
  e' stata riassegnata e poi cambiata. Non e' scritta qui e non va scritta da
  nessuna parte nel repository: una password in git e' una password che resta
  in git per sempre, anche dopo essere stata cambiata. Chi riprende il lavoro
  e non ce l'ha se ne assegna una nuova in dieci secondi:

  ```powershell
  python scripts/reimposta_password.py admin
  ```

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
