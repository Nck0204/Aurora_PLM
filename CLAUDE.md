# Aurora — istruzioni permanenti di progetto

Questo file e' la memoria del progetto. Va letto per intero all'inizio di ogni
sessione di lavoro, prima di scrivere qualunque riga di codice.

Gli altri due file di governo sono:

- `docs/STATO.md` — a che punto siamo, sessione per sessione;
- `docs/DECISIONI.md` — le decisioni tecniche gia' prese e il perche'.

Accanto a loro, da leggere prima di toccare una tabella:

- `docs/MODELLO_DATI.md` — le tabelle del database, una riga di spiegazione
  ciascuna, il dettaglio delle colonne e i principi che le tengono insieme.

E prima di scrivere una pagina:

- `docs/GUIDA_STILE.md` — la palette, i componenti e le regole con cui si
  compone una pagina. **I componenti ci sono gia'**: stanno in
  `app/templates/components/` e si vedono tutti insieme all'indirizzo `/stile`.
  Non se ne inventano di nuovi senza aggiungerli li'.

---

## 1. Che cosa e' Aurora

Sistema di gestione dei progetti e della documentazione tecnica per
un'azienda che sviluppa prodotti elettronici.

Vincoli che discendono dal contesto e che non cambiano:

- gira **in rete locale**, su un **server Windows aziendale**;
- **nessuna dipendenza da servizi cloud**: deve funzionare con la connessione
  a internet staccata;
- gli utenti sono qualche decina, non qualche migliaio: la semplicita' vale
  piu' della scalabilita';
- i dati (disegni, schemi, distinte base, revisioni) sono il patrimonio
  dell'azienda: **non si perdono e non si cancellano**.

## 2. Stack tecnologico

| Ruolo | Strumento |
|---|---|
| Server web | FastAPI + Uvicorn |
| Database | PostgreSQL (18.6 sulla macchina di sviluppo) |
| Accesso al database | SQLAlchemy 2.x, stile ORM dichiarativo (`DeclarativeBase`) |
| Migrazioni | Alembic |
| Driver PostgreSQL | psycopg 3 (`psycopg[binary]`) |
| Pagine | Template Jinja2 generati dal server + HTMX |
| Configurazione | pydantic-settings, da file `.env` |
| Password | argon2-cffi |
| Lettura e scrittura di PDF | pypdf (solo per la filigrana, D-046) |
| Lavori pianificati | APScheduler |
| Test | pytest + httpx |

Le versioni bloccate stanno in `requirements.txt`. Non aggiungere dipendenze
senza annotare la decisione in `docs/DECISIONI.md`.

## 3. Regole permanenti

Queste regole non si discutono e non si aggirano. Se una di esse rende
difficile una soluzione, si cambia la soluzione, non la regola.

1. **Niente CDN.** Nessun CSS, JavaScript, font o icona caricato da un
   indirizzo esterno. Tutto quello che serve al browser sta in
   `app/static/` dentro il repository. L'applicazione deve funzionare su una
   macchina senza accesso a internet.

2. **Niente npm, niente processo di compilazione del frontend.** Nessun
   `package.json`, nessun bundler, nessun React/Vue/Svelte. Le pagine sono
   HTML generato dal server con Jinja2; l'interattivita' si ottiene con HTMX
   e, quando serve, con JavaScript semplice scritto a mano.

3. **Interfaccia in italiano.** Ogni testo che un utente puo' leggere -
   etichette, pulsanti, messaggi di errore, messaggi di posta, pagine di
   errore - e' in italiano.

4. **Identificatori del codice in inglese.** Nomi di variabili, funzioni,
   classi, tabelle, colonne, file e rotte interne in inglese. Commenti e
   docstring in italiano. Le chiavi dei JSON destinati all'interfaccia sono
   in italiano perche' sono testo mostrato, non codice (esempio: la rotta
   `/salute` restituisce `stato`, `versione`, `ora`).

5. **Nessuna cancellazione fisica dei dati.** Non si eseguono mai `DELETE`
   sulle tabelle applicative. Ogni tabella che rappresenta dati aziendali ha
   una colonna di disattivazione (`deleted_at` o `is_active`) e le
   interrogazioni normali escludono le righe disattivate. Vale anche per i
   file: si toglie il collegamento, non il file dall'archivio.

6. **Ogni operazione significativa finisce nell'audit trail.** Creazione,
   modifica, disattivazione, approvazione, caricamento e scaricamento di
   documenti, entrata e uscita degli utenti. La registrazione dice sempre:
   chi, che cosa, su quale oggetto, quando, da quale indirizzo IP, e - dalla
   sessione 9 - **una frase in italiano** che si capisce senza conoscere il
   programma, piu' il valore di prima e quello di dopo per le modifiche.

   **Il registro si scrive e non si tocca piu'.** Non e' una buona intenzione:
   l'utente PostgreSQL con cui Aurora si collega ha su `audit_logs` i permessi
   `SELECT` e `INSERT` e nient'altro (`scripts/hardening_db.sql`), e ogni voce
   porta l'impronta di quella precedente, cosi' una manomissione fatta
   scavalcando il programma si vede (`scripts/verifica_audit.py`). Vedi D-063
   e D-064.

7. **Codice leggibile prima che elegante.** Chi manterra' questo programma
   conosce Python e C, non conosce i framework moderni. Preferire sempre la
   soluzione esplicita a quella astratta e brillante: meno decoratori
   inventati, meno metaprogrammazione, piu' funzioni normali con nomi chiari.
   Se una parte del codice richiede una spiegazione, la spiegazione va scritta
   li' accanto in un commento.

8. **La configurazione sta nel file `.env`, mai nel codice.** Nessun
   indirizzo, nessuna password, nessun percorso scritto dentro i sorgenti.
   Il file `.env` non entra in git; `.env.example` si', aggiornato ogni volta
   che si aggiunge un parametro.

   Quando un parametro non e' una riga sola - un'espressione regolare con le
   sue etichette, una tabella di corrispondenze - va in un file dentro
   `config/`, e nel `.env` ci finisce il suo percorso. Quei file **entrano in
   git**: non contengono segreti, contengono regole che l'azienda potrebbe
   cambiare senza che si debba toccare il programma (D-038).

## 4. Struttura delle cartelle

```
aurora/
├── CLAUDE.md              questo file
├── README.md              avvio rapido
├── requirements.txt       dipendenze con versione bloccata
├── pytest.ini             configurazione dei test
├── alembic.ini            configurazione delle migrazioni
├── .env                   configurazione locale (NON in git)
├── .env.example           modello commentato della configurazione
│
├── app/
│   ├── __init__.py        numero di versione
│   ├── main.py            avvio, registro, gestione errori, rotta /salute
│   ├── config.py          lettura del file .env
│   ├── db.py              engine, sessione, Base, get_db
│   ├── dependencies.py    utente_corrente, richiedi_login, richiedi_creatore
│   │                   (richiedi_creatore chiede a permissions.puo)
│   ├── templating.py      motore Jinja2 e funzione pagina()
│   ├── navigation.py      le voci della barra laterale, filtrate per ruolo
│   ├── models/            tabelle del database (una classe per tabella)
│   ├── routers/           rotte HTTP, raggruppate per argomento
│   ├── services/          logica applicativa, riusabile fuori dalle rotte
│   ├── templates/         pagine Jinja2
│   │   └── components/    i componenti riusabili, come macro
│   └── static/            css, js e immagini serviti da noi
│       └── vendor/        librerie di terzi (htmx), scaricate una volta
│
├── alembic/               migrazioni del database
│   ├── env.py             collegato a Base.metadata e al file .env
│   └── versions/          una migrazione per file
│
├── config/                configurazione che non sta nel .env perche' non e'
│                       una riga sola: la scomposizione dei codici prodotto,
│                       l'elenco dei tipi di documento
├── docs/                  STATO.md, DECISIONI.md, MODELLO_DATI.md,
│                       GUIDA_STILE.md
├── scripts/               procedure operative (installazione, manutenzione).
│                       Fra queste: hardening_db.sql, che rende audit_logs
│                       a sola aggiunta; verifica_audit.py, che ricalcola
│                       la catena delle impronte; archivia_audit.py, che
│                       ne copia le voci vecchie su file compresso
├── tests/                 test pytest
├── storage/               archivio dei file caricati (NON in git)
│   ├── objects/           i file, depositati per impronta SHA-256:
│   │                   objects/3f/9a/3f9a2c11... (D-004, D-047)
│   ├── tmp/               i file a meta' scrittura. In condizioni normali e'
│   │                   vuota: quello che ci resta e' un caricamento
│   │                   interrotto, e non lo riferisce nessuno
│   └── posta/             la cartella della posta (MAIL_LOCAL_PATH): i .eml
│                       da leggere, piu' elaborate/ e quarantena/ dove
│                       finiscono dopo l'archiviazione
└── logs/                  registro applicativo rotativo (NON in git)
```

Dove mettere una cosa nuova:

- una tabella → un file in `app/models/`, importato in `app/models/__init__.py`
  (se non lo si importa, Alembic non la vede), documentato in
  `docs/MODELLO_DATI.md`;
- uno stato nuovo → un `Enum` in `app/models/enums.py` **e** una migrazione:
  il tipo enumerato vive nel database (vedi D-014 e D-019);
- una pagina o una chiamata HTMX → un `APIRouter` in `app/routers/`,
  registrato in `app/main.py` con `app.include_router(...)`;
- un calcolo, un invio, una regola di business → una funzione in
  `app/services/`, cosi' e' richiamabile anche da un lavoro pianificato o da
  un test;
- una procedura che esegue una persona → un file `.md` in `scripts/`;
- **una pagina protetta** → una rotta che dichiara `Depends(richiedi_login)`
  oppure `Depends(richiedi_creatore)` (vedi `app/dependencies.py`). Non
  scrivere controlli di permesso dentro il corpo della rotta: nascosti li',
  prima o poi ne manca uno;
- **un modulo che invia con POST** → dentro il `<form>` va la riga
  `{{ csrf(request) }}` (macro in `components/campi.html`), altrimenti la
  richiesta viene rifiutata con un 400 (vedi D-028);
- **una pagina nuova** → si compone con i macro di
  `app/templates/components/`, estendendo `base.html`. Non si riscrive l'HTML
  di un pulsante, di un campo o di una tabella: esistono gia', e sono in
  vetrina all'indirizzo `/stile`;
- **un componente grafico nuovo** → un file in `app/templates/components/` con
  in cima *quando si usa e quando non si usa*, le sue regole in `aurora.css`, un
  esempio in `/stile` e una riga in `docs/GUIDA_STILE.md`. I cinque passi sono
  elencati li' (sezione 10);
- **un colore, una spaziatura, un raggio** → una variabile in `:root`, in cima
  ad `app/static/css/aurora.css`. Mai un valore scritto dentro una regola o
  dentro un template: c'e' un test che lo verifica (D-033).
- **un file da salvare su disco** → si passa da `app/services/storage.py`,
  che lo deposita per impronta e scrive in modo atomico. Non si apre un file
  dentro una rotta: il nome originale sul filesystem, il limite dei 260
  caratteri di Windows e la scrittura interrotta sono tre problemi gia'
  risolti li' (D-004, D-047);
- **un'operazione da registrare** → si aggiunge una riga a
  `audit.CATALOGO` (il nome in inglese, la frase italiana, il gruppo) e si
  chiama `audit.record(..., etichetta=...)` passando il nome con cui una
  persona chiama l'oggetto. Il nome lo compone `app/services/etichette.py`.
  **Non si costruisce mai una riga di `audit_logs` a mano**: senza `record()`
  la voce resta senza numero di sequenza e l'INSERT fallisce - e' il database
  che fa rispettare D-018. C'e' un test che legge i sorgenti e diventa rosso
  se un'azione non e' catalogata (`tests/test_registro.py`);
- **un permesso, di qualunque genere** → si chiede a
  `permissions.puo(db, utente, azione, oggetto)`, che e' **l'unico punto del
  programma in cui un permesso viene deciso** (D-051). Non si scrive un
  controllo dentro una rotta, non si confronta un ruolo dentro un servizio,
  non si mette un `{% if %}` dentro un template: le tre strade - il singolo
  oggetto, l'elenco e il pulsante disegnato - devono dare la stessa risposta,
  e ci sono quattro test che leggono i sorgenti per verificarlo
  (`tests/test_permessi.py`).
  Nelle rotte si usa `permissions.pretendi(...)`, che risponde da sola con il
  codice giusto: **404** se la persona non puo' nemmeno vedere l'oggetto - con
  lo stesso messaggio di uno che non esiste (D-052) - e **403** se lo vede gia'
  e le manca solo il permesso per quella operazione.
  Per gli elenchi c'e' la stessa regola scritta come condizione SQL,
  `filtro_documenti()` e `filtro_progetti()`: il filtro va
  nell'interrogazione, mai nel template, e vale **anche per i conteggi**;
- **una regola che riguarda una fase in particolare** ("da questa non si torna
  indietro", "questa chiude il progetto") → una **colonna di `phases`**, con la
  sua migrazione, e una spunta nel modulo che crea il modello. Mai un confronto
  sul nome della fase: le fasi sono dati e si cambiano dall'interfaccia (D-055);
- **una regola che l'azienda potrebbe cambiare** (come si legge un codice
  prodotto, quali sono i tipi di documento) → un file in `config/`, con il suo
  percorso dichiarato in `.env`.
  Il programma deve continuare a funzionare anche se quel file e' sbagliato o
  manca: vedi D-038 e D-039;
- **un elenco di scelte per un menu a tendina o un filtro** → si compone in
  Python, nella rotta o nel servizio, e arriva al template gia' pronto. Un
  template che trasforma un valore in un'etichetta contiene una regola, e le
  regole non si provano con un test se stanno dentro l'HTML
  (`docs/GUIDA_STILE.md`, sezione 5);
- **una sorgente di posta nuova** (Microsoft Graph, IMAP, una cartella su un
  altro disco) → una classe che rispetta l'interfaccia `FonteEmail` in
  `app/services/mail_source.py`, e una riga in `fonte_configurata()`. Sono
  quattro metodi e sono tutti quelli che servono; il motore di
  `app/services/emails.py` non va toccato (D-076);
- **una regola su come si legge un messaggio** (un prefisso di risposta in
  piu', un modo diverso di scomporre l'oggetto) → `app/services/email_parsing.py`,
  che **non tocca il database**: sono funzioni pure sui byte di un `.eml`, e si
  provano una per una senza PostgreSQL. Nessuna di loro solleva mai: un file
  rotto produce un risultato povero e finisce in quarantena, non un'eccezione
  che ferma l'acquisizione di tutti gli altri.

## 5. Convenzioni di codice

- **Nomi**: `snake_case` per variabili e funzioni, `PascalCase` per le classi,
  `MAIUSCOLO` per le costanti. Le tabelle hanno nome al plurale
  (`projects`, `documents`), le classi al singolare (`Project`, `Document`).
- **Annotazioni di tipo** sulle firme delle funzioni: sono la documentazione
  piu' economica che esista.
- **Docstring in italiano** su ogni funzione che non sia ovvia: cosa fa, e
  quando e' il caso, perche' e' fatta cosi'.
- **Righe fino a 88 caratteri.**
- **Import**: prima quelli della libreria standard, poi quelli di terze parti,
  poi quelli di Aurora (`from app...`), separati da una riga vuota.
- **Errori**: mai un `except` muto. O si gestisce l'errore, o lo si registra e
  lo si rilancia. Il messaggio scritto nel registro e' tecnico e in italiano;
  quello mostrato all'utente e' in italiano e senza dettagli tecnici.
- **Sessioni del database**: si ottengono con `Depends(get_db)`, mai creando
  una `SessionLocal()` dentro una rotta.
- **Date e ore**: sempre con fuso orario, mai "nude".

## 6. Comandi utili

Tutti dalla radice del progetto (`aurora/`), con l'ambiente virtuale attivo:

```powershell
.venv\Scripts\activate
```

| Cosa | Comando |
|---|---|
| Avviare il server in sviluppo | `uvicorn app.main:app --reload` |
| Controllare che sia vivo | aprire <http://localhost:8000/salute> |
| Documentazione automatica delle rotte | <http://localhost:8000/docs> |
| Eseguire i test | `pytest` |
| Un solo test, con dettaglio | `pytest tests/test_salute.py -v` |
| Creare una migrazione | `alembic revision --autogenerate -m "descrizione"` |
| Applicare le migrazioni | `alembic upgrade head` |
| Tornare indietro di una migrazione | `alembic downgrade -1` |
| A che punto e' il database | `alembic current` |
| Storia delle migrazioni | `alembic history --verbose` |
| Installare le dipendenze | `pip install -r requirements.txt` |
| Leggere il registro | `Get-Content logs\aurora.log -Tail 50 -Wait` |

## 7. Come si conduce una sessione di lavoro

1. Leggere `CLAUDE.md`, `docs/STATO.md` e `docs/DECISIONI.md`.
2. Fare **solo** quello che la sessione prevede. Non anticipare il lavoro
   delle sessioni successive: e' cosi' che i progetti si impantanano.
3. Ogni scelta tecnica non ovvia va annotata in `docs/DECISIONI.md` con data
   e motivazione, nel momento in cui viene presa.
4. Aggiungere i test insieme al codice, non "dopo".
5. Se si aggiunge un parametro di configurazione, aggiornare `.env.example`.
6. Alla fine: aggiornare `docs/STATO.md`, verificare che `pytest` passi, fare
   un commit con messaggio in italiano.

## 8. Cose da non fare mai

- Aggiungere un collegamento a una risorsa esterna in un template.
- Introdurre npm o un passaggio di compilazione del frontend.
- Scrivere un colore dentro una regola CSS o dentro un template.
- Far dipendere da JavaScript qualcosa che deve funzionare per forza: entrare,
  cambiare la password, creare un utente, caricare un documento (vedi D-036).
- Usare SQLite, nemmeno "solo per provare".
- Scrivere `DELETE FROM` su una tabella applicativa.
- Aggiungere un modo di **sostituire** il file di una versione gia'
  caricata. Una versione e' un fatto avvenuto: se il file era sbagliato se
  ne carica un'altra (D-045). C'e' un test che lo verifica.
- Rifiutare un codice prodotto perche' non si scompone: si accetta con
  `code_parts` vuoto e una segnalazione visibile (D-039).
- **Decidere un permesso fuori da `app/services/permissions.py`.** Niente
  `if utente.is_creatore` dentro una rotta o un servizio, niente
  `{% if utente.is_creatore %}` dentro un template, niente interrogazione di
  `permission_rules` da un altro file. La domanda si fa con `permissions.puo()`
  e la risposta arriva al template come un booleano gia' deciso (D-051). Ci
  sono quattro test che lo verificano leggendo i sorgenti.
- Confrontare due stati del ciclo di vita fuori da `app/services/lifecycle.py`:
  i grafi delle transizioni stanno li' e in nessun altro posto. Sono **due**:
  quello di una versione di prodotto e quello di un documento (D-042, D-044).
  Le fasi di un progetto **non sono il terzo grafo** e stanno in
  `app/services/phases.py`: non sono un elenco chiuso scritto in Python, sono
  righe di una tabella in un ordine che sceglie chi crea il modello (D-059).
- **Scrivere un `if` sul nome di una fase.** Le fasi sono dati: aggiungerne
  una, rinominarla o riordinarla non deve costare una riga di programma. Se
  una regola riguarda una fase in particolare, quella regola diventa una
  **colonna di `phases`** - come `blocks_return` e `closes_project` - e la
  spunta la mette chi crea il modello. Ci sono due test che leggono i sorgenti
  e diventano rossi se un nome di fase ricompare dentro `app/` (D-055).
- **Scrivere, modificare o cancellare una riga di `audit_logs` fuori da
  `audit.record()`.** Non c'e' nessuna funzione che corregge il registro e non
  va aggiunta: il database non lo permetterebbe comunque. Se una voce e'
  sbagliata, se ne scrive una nuova che lo dice.
- Cancellare voci vecchie del registro "per fare spazio". La politica di
  conservazione e' l'archiviazione, che **copia** e non sposta
  (`scripts/archivia_audit.py`, D-065).
- **Scrivere una regola di accesso nuova per la posta.** Un messaggio si vede
  con la stessa identica regola di un documento: e' un documento di
  classificazione **"Corrispondenza"** nel progetto della versione a cui e'
  attaccato (D-069). Non c'e' nessuna colonna in piu' e nessuna seconda
  matrice: c'e' una riga di `classifications` che si amministra dalla pagina di
  sempre.
- **Far fallire l'archiviazione di un messaggio perche' il file e' brutto.** Un
  `.eml` troncato, senza intestazioni, con la data illeggibile o con dentro dei
  byte a zero va archiviato lo stesso e messo in quarantena, con scritto
  perche'. "Mai scartare, mai bloccarsi": un messaggio che Aurora non capisce e'
  comunque un messaggio che l'azienda ha ricevuto (D-070, D-074, D-075).
- Mettere una password o un indirizzo di server dentro un file `.py`.
- Modificare a mano una migrazione gia' applicata in produzione: se ne scrive
  una nuova.
- Committare `.env`, il contenuto di `storage/` o i file di `logs/`.
