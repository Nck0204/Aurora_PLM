# Aurora — istruzioni permanenti di progetto

Questo file e' la memoria del progetto. Va letto per intero all'inizio di ogni
sessione di lavoro, prima di scrivere qualunque riga di codice.

Gli altri due file di governo sono:

- `docs/STATO.md` — a che punto siamo, sessione per sessione;
- `docs/DECISIONI.md` — le decisioni tecniche gia' prese e il perche'.

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
   chi, che cosa, su quale oggetto, quando, da quale indirizzo IP.

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
│   ├── models/            tabelle del database (una classe per tabella)
│   ├── routers/           rotte HTTP, raggruppate per argomento
│   ├── services/          logica applicativa, riusabile fuori dalle rotte
│   ├── templates/         pagine Jinja2
│   └── static/            css, js e immagini serviti da noi
│
├── alembic/               migrazioni del database
│   ├── env.py             collegato a Base.metadata e al file .env
│   └── versions/          una migrazione per file
│
├── docs/                  STATO.md, DECISIONI.md e documentazione
├── scripts/               procedure operative (installazione, manutenzione)
├── tests/                 test pytest
├── storage/               archivio dei file caricati (NON in git)
└── logs/                  registro applicativo rotativo (NON in git)
```

Dove mettere una cosa nuova:

- una tabella → un file in `app/models/`, importato in `app/models/__init__.py`
  (se non lo si importa, Alembic non la vede);
- una pagina o una chiamata HTMX → un `APIRouter` in `app/routers/`,
  registrato in `app/main.py` con `app.include_router(...)`;
- un calcolo, un invio, una regola di business → una funzione in
  `app/services/`, cosi' e' richiamabile anche da un lavoro pianificato o da
  un test;
- una procedura che esegue una persona → un file `.md` in `scripts/`.

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
- Usare SQLite, nemmeno "solo per provare".
- Scrivere `DELETE FROM` su una tabella applicativa.
- Mettere una password o un indirizzo di server dentro un file `.py`.
- Modificare a mano una migrazione gia' applicata in produzione: se ne scrive
  una nuova.
- Committare `.env`, il contenuto di `storage/` o i file di `logs/`.
